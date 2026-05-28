"""Channel-split aggregations for the Financials page.

Three-way classification of customers — already encoded on the
``Customer`` model, NOT re-derived from order-sheet provenance at
request time. The partition rule is the single source of truth; both
the totals and the per-customer breakdowns route through it:

* EXCLUDED ⇔ ``is_internal == True`` — BAKERY INTERNAL USE + BAKERY
  WASTAGE (flipped by data migration 0024). Never counted as demand
  by the Financials page; the bakery's own consumption.
* WHOLESALE ⇔ ``is_internal == False`` AND
  ``customer_type == 'wholesale'`` — set by ``import_customers`` on
  every customer whose name appears in the WHOLESALE tab.
* INTERNAL ⇔ ``is_internal == False`` AND NOT WHOLESALE — the
  **complement**, mirroring the spec ("Internal = all other customers
  EXCEPT Bakery Internal Use and Bakery Wastage"). This is critical:
  a customer with a missing / typoed / empty ``customer_type`` is in
  the Orders-page external total but, if INTERNAL were defined as
  ``customer_type == 'internal'`` rather than NOT WHOLESALE, would
  vanish from the Financials grand total. (That was the £22.05
  shortfall on w/c 18 May before this fix.)

Every total here is computed from per-line snapshots
(``OrderLine.unit_price * qty_ordered`` summed in SQL via a single
aggregate) — same convention as ``Order.total_value()`` but pulled
out to one query per page so the dashboard stays fast at the Render
free-tier's 30s budget.
"""
from datetime import date, timedelta
from decimal import Decimal

from collections import defaultdict

from django.db.models import Count, DecimalField, F, Max, Min, Q, Sum

from .models import Customer, Order, OrderLine


def _monday_of(d):
    """Return the Monday that begins the calendar week containing ``d``.

    Mirrors ``views._monday_of`` so callers don't have to import a
    view-layer helper. Pure derivation; nothing stored.
    """
    return d - timedelta(days=d.weekday())


def _line_value_expr():
    """``Sum(qty_ordered * unit_price)`` expression — re-used by every
    aggregation in this module. Cast to a Decimal output field so the
    SQLite test backend produces Decimals rather than floats."""
    return Sum(
        F("qty_ordered") * F("unit_price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def _q2(v):
    """Round to 2dp using the standard banker's-rounding ``Decimal``
    quantizer everything else in this codebase uses for currency."""
    return (v or Decimal("0")).quantize(Decimal("0.01"))


def available_week_range(dept):
    """``(earliest_wc, latest_wc)`` Mondays for which ``dept`` has at
    least one non-excluded order.

    Used by the view to default the range selector to "everything we
    have". The earliest Monday is derived from the order date, never
    stored, in keeping with the rest of the orders system. When the
    department has no orders we return today's Monday twice — the
    selector still renders cleanly with no data.
    """
    agg = Order.objects.filter(
        department=dept, customer__is_internal=False,
    ).aggregate(earliest=Min("order_date"), latest=Max("order_date"))
    if agg["earliest"] is None:
        wc = _monday_of(date.today())
        return wc, wc
    return _monday_of(agg["earliest"]), _monday_of(agg["latest"])


def range_totals(dept, start_wc, end_wc):
    """Internal / wholesale / grand totals for ``[start_wc, end_wc]``.

    ``end_wc`` is the Monday of the LAST week in the range — the
    selector is week-resolution, so the actual day-range is
    ``start_wc .. end_wc + 6 days``. Excludes ``is_internal=True``
    customers entirely. Internal is the **complement** of wholesale
    within the external scope (see module docstring) so any customer
    with an off-piste ``customer_type`` value still lands in a channel
    and the grand total reconciles with the Orders page. Returns
    ``{internal, wholesale, total}`` all as 2dp Decimals.
    """
    end = end_wc + timedelta(days=6)
    agg = OrderLine.objects.filter(
        order__department=dept,
        order__order_date__range=(start_wc, end),
        order__customer__is_internal=False,
    ).aggregate(
        wholesale=Sum(
            F("qty_ordered") * F("unit_price"),
            filter=Q(order__customer__customer_type=Customer.WHOLESALE),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        # Internal = NOT wholesale (within the already-external scope),
        # NOT the literal ``customer_type='internal'`` filter — see the
        # module docstring for why this matters.
        internal=Sum(
            F("qty_ordered") * F("unit_price"),
            filter=~Q(order__customer__customer_type=Customer.WHOLESALE),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
    )
    internal = _q2(agg["internal"])
    wholesale = _q2(agg["wholesale"])
    return {
        "internal": internal,
        "wholesale": wholesale,
        "total": _q2(internal + wholesale),
    }


def per_week_split(dept, start_wc, end_wc):
    """One ``{wc, internal, wholesale, total}`` row per week in range.

    Weeks with no orders still surface as zero rows so the weekly-
    trend bar chart renders the full timeline without gaps in the
    x-axis. Sorted oldest → newest.
    """
    end = end_wc + timedelta(days=6)
    rows = (OrderLine.objects.filter(
        order__department=dept,
        order__order_date__range=(start_wc, end),
        order__customer__is_internal=False,
    ).values(
        "order__order_date",
        "order__customer__customer_type",
    ).annotate(total=_line_value_expr()))

    # Pre-seed every Monday in range so empty weeks render as zeros.
    by_week = {}
    cur = start_wc
    while cur <= end_wc:
        by_week[cur] = {
            "wc": cur,
            "internal": Decimal("0"),
            "wholesale": Decimal("0"),
        }
        cur += timedelta(days=7)

    for r in rows:
        wc = _monday_of(r["order__order_date"])
        bucket = by_week.get(wc)
        if bucket is None:
            # Shouldn't happen — the range filter above keeps every
            # date inside [start_wc, end_wc+6]. Guard anyway so a
            # mis-snapped Sunday-edge order can't KeyError.
            continue
        if r["order__customer__customer_type"] == Customer.WHOLESALE:
            bucket["wholesale"] += r["total"] or Decimal("0")
        else:
            bucket["internal"] += r["total"] or Decimal("0")

    out = []
    for wc, bucket in sorted(by_week.items()):
        bucket["internal"] = _q2(bucket["internal"])
        bucket["wholesale"] = _q2(bucket["wholesale"])
        bucket["total"] = _q2(bucket["internal"] + bucket["wholesale"])
        out.append(bucket)
    return out


def per_customer_in_channel(dept, channel, start_wc, end_wc):
    """Per-customer totals within one channel, biggest first.

    ``channel`` is one of ``Customer.WHOLESALE`` / ``Customer.INTERNAL``.
    Always excludes ``is_internal=True`` (BAKERY INTERNAL USE / BAKERY
    WASTAGE never appear in either channel's breakdown). INTERNAL is
    the complement of WHOLESALE within the external scope — same
    partition rule as :func:`range_totals` and :func:`per_week_split`
    — so every external customer surfaces in exactly one channel's
    table, even if their ``customer_type`` is missing / typoed.
    Returns ``[{customer_id, name, total, pct}]`` where ``pct`` is
    the customer's share of the channel total as a 1-dp Decimal.
    """
    end = end_wc + timedelta(days=6)
    qs = OrderLine.objects.filter(
        order__department=dept,
        order__order_date__range=(start_wc, end),
        order__customer__is_internal=False,
    )
    if channel == Customer.WHOLESALE:
        qs = qs.filter(order__customer__customer_type=Customer.WHOLESALE)
    else:
        qs = qs.exclude(order__customer__customer_type=Customer.WHOLESALE)
    rows = list(qs.values(
        "order__customer_id",
        "order__customer__name",
    ).annotate(total=_line_value_expr()))

    rows.sort(key=lambda r: r["total"] or Decimal("0"), reverse=True)
    channel_total = sum(
        (r["total"] or Decimal("0") for r in rows), Decimal("0"))

    out = []
    for r in rows:
        total = r["total"] or Decimal("0")
        pct = (total / channel_total * Decimal("100")
               if channel_total else Decimal("0"))
        out.append({
            "customer_id": r["order__customer_id"],
            "name": r["order__customer__name"],
            "total": _q2(total),
            "pct": pct.quantize(Decimal("0.1")),
        })
    return out


# ---------------------------------------------------------------------------
# Single-week helpers — power the React dashboard's "week view".
#
# Same partition rule as the range helpers above (external = NOT
# ``is_internal``; WHOLESALE = ``customer_type='wholesale'``; INTERNAL
# = the complement). Every figure is derived from per-line snapshots
# (``qty_ordered * unit_price``) — NEVER the sheet's "Total" columns,
# which are formula cells and often blank / wrong. See CLAUDE.md.
# ---------------------------------------------------------------------------


def available_weeks(dept):
    """All week-start (Monday) dates with at least one external order,
    newest first. Used by the dashboard week-picker so the operator
    can jump straight to any imported week without typing a date."""
    dates = (Order.objects.filter(
        department=dept, customer__is_internal=False,
    ).values_list("order_date", flat=True).distinct())
    weeks = sorted({_monday_of(d) for d in dates}, reverse=True)
    return weeks


def week_daily_totals(dept, week_start):
    """7 rows (Mon..Sun) of ``{date, total}`` for one week.

    Sums DAILY ordered cells × snapshotted price for external customers
    only (``is_internal=False``). Days with no orders surface as £0 so
    the dashboard's daily-trend bar chart always renders the full
    week's shape, never a sparse strip.
    """
    end = week_start + timedelta(days=6)
    rows = (OrderLine.objects.filter(
        order__department=dept,
        order__order_date__range=(week_start, end),
        order__customer__is_internal=False,
    ).values("order__order_date").annotate(total=_line_value_expr()))
    by_date = {r["order__order_date"]: _q2(r["total"]) for r in rows}
    out = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        out.append({"date": d, "total": by_date.get(d, Decimal("0.00"))})
    return out


def week_daily_channel_split(dept, week_start):
    """7 rows (Mon..Sun) of ``{date, internal, wholesale, total}``.

    Same scope and partition rule as :func:`per_week_split`, but at
    day grain so a one-week Business Performance chart has seven real
    points instead of one stretched weekly point.
    """
    end = week_start + timedelta(days=6)
    rows = (OrderLine.objects.filter(
        order__department=dept,
        order__order_date__range=(week_start, end),
        order__customer__is_internal=False,
    ).values(
        "order__order_date",
        "order__customer__customer_type",
    ).annotate(total=_line_value_expr()))

    by_date = {
        week_start + timedelta(days=i): {
            "date": week_start + timedelta(days=i),
            "internal": Decimal("0"),
            "wholesale": Decimal("0"),
        }
        for i in range(7)
    }

    for r in rows:
        bucket = by_date.get(r["order__order_date"])
        if bucket is None:
            continue
        if r["order__customer__customer_type"] == Customer.WHOLESALE:
            bucket["wholesale"] += r["total"] or Decimal("0")
        else:
            bucket["internal"] += r["total"] or Decimal("0")

    out = []
    for d in sorted(by_date):
        bucket = by_date[d]
        bucket["internal"] = _q2(bucket["internal"])
        bucket["wholesale"] = _q2(bucket["wholesale"])
        bucket["total"] = _q2(bucket["internal"] + bucket["wholesale"])
        out.append(bucket)
    return out


def week_channel_split(dept, week_start):
    """``{internal:{total,pct}, wholesale:{total,pct}}`` for one week.

    Thin wrapper over :func:`range_totals` with ``start==end==week_start``
    so the channel-split numbers reconcile EXACTLY with the range view
    when the same week is selected on both pages.
    """
    rt = range_totals(dept, week_start, week_start)
    total = rt["total"] or Decimal("0")

    def _pct(part):
        if not total:
            return Decimal("0.0")
        return (part / total * Decimal("100")).quantize(Decimal("0.1"))

    return {
        "internal": {"total": rt["internal"], "pct": _pct(rt["internal"])},
        "wholesale": {"total": rt["wholesale"], "pct": _pct(rt["wholesale"])},
    }


def week_orders_count(dept, week_start):
    """Number of external order LINES in the week.

    "Lines" rather than "orders" because the dashboard's "total orders"
    tile is really a line-count — one customer ordering 12 products
    counts as 12, not 1. (If a future tile needs distinct orders,
    add a separate helper rather than overloading this one.)
    """
    end = week_start + timedelta(days=6)
    return OrderLine.objects.filter(
        order__department=dept,
        order__order_date__range=(week_start, end),
        order__customer__is_internal=False,
    ).count()


def week_over_week(dept, week_start):
    """Compare ``week_start`` to the immediately PRIOR imported week.

    "Prior imported week" = the most recent week-start (Monday) before
    ``week_start`` that has at least one external order — NOT
    ``week_start - 7 days``, which would silently treat a gap week as
    a -100% drop. Returns ``{prev_week_start, prev_total, total, pct}``;
    ``prev_week_start`` is ``None`` and ``pct`` is ``None`` when this
    is the very first imported week (nothing to compare to).
    """
    cur_total = range_totals(dept, week_start, week_start)["total"]
    # Find the latest external order strictly before this week — its
    # Monday is the previous imported week. Skipping gap weeks matters:
    # otherwise the first week back from a holiday looks like infinite
    # growth and the operator stops trusting the figure.
    prev = (Order.objects.filter(
        department=dept,
        order_date__lt=week_start,
        customer__is_internal=False,
    ).order_by("-order_date").only("order_date").first())
    if prev is None:
        return {
            "prev_week_start": None,
            "prev_total": Decimal("0.00"),
            "total": _q2(cur_total),
            "pct": None,
        }
    prev_start = _monday_of(prev.order_date)
    prev_total = range_totals(dept, prev_start, prev_start)["total"]
    pct = None
    if prev_total:
        pct = float(((cur_total - prev_total) / prev_total * Decimal("100"))
                    .quantize(Decimal("0.1")))
    return {
        "prev_week_start": prev_start,
        "prev_total": _q2(prev_total),
        "total": _q2(cur_total),
        "pct": pct,
    }


def week_top_customers(dept, week_start, channel, n=5):
    """Top ``n`` customers in ``channel`` for one week, biggest first.

    Reuses :func:`per_customer_in_channel` (same partition rule, same
    SQL) so the dashboard's per-customer numbers match the Financials
    page byte-for-byte when both are looking at the same week.
    """
    rows = per_customer_in_channel(dept, channel, week_start, week_start)
    return rows[:n]


def week_product_day_matrix(dept, week_start, top_n=12):
    """Top ``top_n`` products by ordered qty for one week, with per-day
    Mon..Sun quantities for each.

    External customers only (``is_internal=False``) — same scope as the
    rest of the dashboard. Groups by ``OrderLine.product_name`` (the
    SNAPSHOT, not the catalogue SaleProduct) so a discontinued or
    renamed product still shows its true weekly demand. Days with no
    orders for a product surface as ``Decimal("0")`` rather than being
    dropped — the matrix is always 7 columns so the dashboard renders a
    rectangular grid without per-row branching.

    Returns ``[{product, total_qty, daily}]`` ordered biggest-first by
    ``total_qty``. ``daily`` is a list of 7 Decimals aligned to
    Mon..Sun. Empty week → ``[]``.
    """
    end = week_start + timedelta(days=6)
    rows = (OrderLine.objects.filter(
        order__department=dept,
        order__order_date__range=(week_start, end),
        order__customer__is_internal=False,
    ).values("product_name", "order__order_date").annotate(
        qty=Sum("qty_ordered")))

    by_product = defaultdict(lambda: [Decimal("0")] * 7)
    totals = defaultdict(lambda: Decimal("0"))
    for r in rows:
        pname = r["product_name"]
        offset = (r["order__order_date"] - week_start).days
        if not (0 <= offset < 7):
            # Date snapped outside the requested week — guard against a
            # bad timestamp rather than letting it index off the end.
            continue
        qty = r["qty"] or Decimal("0")
        by_product[pname][offset] += qty
        totals[pname] += qty

    top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [
        {"product": name, "total_qty": totals[name], "daily": by_product[name]}
        for name, _ in top
    ]


def recent_order_groups(dept, n=10):
    """The ``n`` most recent customer-day order groups, newest first.

    One row per Order (an Order is already a customer-day group in this
    schema — ``Order.customer`` × ``Order.order_date``). The ``channel``
    field is derived live from the customer's ``is_internal`` /
    ``customer_type`` so a re-classified customer's history reflects
    the current classification (no snapshot needed; partition rule is
    the single source of truth — see module docstring). Excluded
    (``is_internal``) groups are tagged ``"excluded"`` so the
    dashboard can dim or filter them rather than silently dropping
    bakery-internal-use activity from the operator's view.
    """
    orders = list(Order.objects
                  .filter(department=dept)
                  .select_related("customer")
                  .prefetch_related("lines")
                  .order_by("-order_date", "-id")[:n])
    out = []
    for o in orders:
        lines = list(o.lines.all())
        total = sum((line.line_value or Decimal("0") for line in lines),
                    Decimal("0"))
        if o.customer.is_internal:
            channel = "excluded"
        elif o.customer.customer_type == Customer.WHOLESALE:
            channel = "wholesale"
        else:
            channel = "internal"
        out.append({
            "date": o.order_date,
            "customer": o.customer.name,
            "channel": channel,
            "line_count": len(lines),
            "ordered_total": _q2(total),
        })
    return out


# ---------------------------------------------------------------------------
# Business Performance helpers — multi-week commercial-finance view.
#
# Built on the same OrderLine snapshots as everything above. NEVER touch the
# spreadsheet's "Total ££" formula cells; NEVER count is_internal customers
# (BAKERY INTERNAL USE / BAKERY WASTAGE). The partition rule stays single-
# source-of-truth: WHOLESALE = customer_type='wholesale', INTERNAL = NOT
# wholesale within the external scope.
#
# "Period" here is any range of complete weeks. Comparisons are always
# against the equal-length window immediately before the current period
# (not against last week). When the prior window would start before the
# earliest imported week, prior totals + deltas are returned as None so
# the UI can show "—" rather than fake a partial figure.
# ---------------------------------------------------------------------------


def _prior_window(start_wc, end_wc):
    """``(prior_start_wc, prior_end_wc)`` for the equal-length window
    immediately before ``[start_wc, end_wc]``. Both endpoints are Mondays."""
    n_weeks = ((end_wc - start_wc).days // 7) + 1
    prior_end_wc = start_wc - timedelta(days=7)  # Monday one week before start_wc
    prior_start_wc = prior_end_wc - timedelta(weeks=n_weeks - 1)
    return prior_start_wc, prior_end_wc


def _pct_delta(current, prior):
    """``(current - prior) / prior * 100`` as a 1-dp Decimal, or None
    when prior is zero / falsy (no honest comparison possible)."""
    if not prior:
        return None
    return ((current - prior) / prior * Decimal("100")).quantize(Decimal("0.1"))


def period_comparison(dept, start_wc, end_wc):
    """Current-period channel totals + equal-length prior period + deltas.

    The prior period is the equal-length window of weeks immediately
    before ``start_wc`` (an 8-week current period compares against the
    preceding 8 weeks, NOT against ``start_wc - 7 days``). When the
    prior window would start before the department's earliest imported
    week, ``prior`` and ``delta`` are returned as ``None`` and
    ``prior_truncated`` is True — the UI shows "—" rather than a
    misleading partial figure.

    Returns ``{current, prior, delta, n_weeks, prior_from, prior_to,
    prior_truncated}``. ``current``/``prior`` mirror :func:`range_totals`'s
    shape (``{internal, wholesale, total}``); ``delta`` is
    ``{total_pct, wholesale_pct, internal_pct, wholesale_share_pp,
    internal_share_pp}`` — the ``_pp`` figures are percentage-POINT
    changes in channel share, not relative deltas.
    """
    cur = range_totals(dept, start_wc, end_wc)
    n_weeks = ((end_wc - start_wc).days // 7) + 1
    prior_start_wc, prior_end_wc = _prior_window(start_wc, end_wc)

    earliest, _latest = available_week_range(dept)
    truncated = prior_start_wc < earliest

    if truncated:
        return {
            "current": cur,
            "prior": None,
            "delta": None,
            "n_weeks": n_weeks,
            "prior_from": prior_start_wc,
            "prior_to": prior_end_wc,
            "prior_truncated": True,
        }

    prior = range_totals(dept, prior_start_wc, prior_end_wc)

    cur_total = cur["total"] or Decimal("0")
    prior_total = prior["total"] or Decimal("0")

    def _share(part, whole):
        if not whole:
            return Decimal("0.0")
        return (part / whole * Decimal("100")).quantize(Decimal("0.1"))

    cur_wholesale_share = _share(cur["wholesale"], cur_total)
    prior_wholesale_share = _share(prior["wholesale"], prior_total)
    cur_internal_share = _share(cur["internal"], cur_total)
    prior_internal_share = _share(prior["internal"], prior_total)

    delta = {
        "total_pct": _pct_delta(cur["total"], prior["total"]),
        "wholesale_pct": _pct_delta(cur["wholesale"], prior["wholesale"]),
        "internal_pct": _pct_delta(cur["internal"], prior["internal"]),
        "wholesale_share_pp": (cur_wholesale_share - prior_wholesale_share)
                              .quantize(Decimal("0.1")),
        "internal_share_pp": (cur_internal_share - prior_internal_share)
                             .quantize(Decimal("0.1")),
    }

    return {
        "current": cur,
        "prior": prior,
        "delta": delta,
        "n_weeks": n_weeks,
        "prior_from": prior_start_wc,
        "prior_to": prior_end_wc,
        "prior_truncated": False,
    }


def concentration_metrics(dept, channel, start_wc, end_wc):
    """Customer concentration ratios within a channel over a range.

    The "if my top customers all walked, what % of channel revenue walks
    with them" risk indicator. Reuses :func:`per_customer_in_channel`
    (already sorted biggest-first) so concentration reconciles exactly
    with the customer table on the same page.

    Returns ``{top_1_name, top_1_pct, top_3_pct, top_5_pct, band,
    n_customers}``. ``band`` is a 3-state health classifier on top-5
    share: ``healthy`` (<50%), ``watch`` (50–70%), ``concentrated`` (>70%).
    Thresholds are intentionally coarse — finance-team judgment will
    refine them as the dataset grows. Empty channel → all zeros and
    band=``healthy`` (vacuously true).
    """
    rows = per_customer_in_channel(dept, channel, start_wc, end_wc)
    top_1_pct = rows[0]["pct"] if rows else Decimal("0.0")
    top_1_name = rows[0]["name"] if rows else None
    top_3_pct = sum((r["pct"] for r in rows[:3]),
                    Decimal("0")).quantize(Decimal("0.1"))
    top_5_pct = sum((r["pct"] for r in rows[:5]),
                    Decimal("0")).quantize(Decimal("0.1"))

    if top_5_pct < Decimal("50"):
        band = "healthy"
    elif top_5_pct < Decimal("70"):
        band = "watch"
    else:
        band = "concentrated"

    return {
        "top_1_name": top_1_name,
        "top_1_pct": top_1_pct,
        "top_3_pct": top_3_pct,
        "top_5_pct": top_5_pct,
        "band": band,
        "n_customers": len(rows),
    }


def customer_dynamics(dept, channel, start_wc, end_wc,
                      growth_threshold=Decimal("0.10")):
    """Per-customer current + prior totals with state classification.

    For every customer with orders in the current period: pair with their
    prior-period total (same equal-length window as :func:`period_comparison`)
    and classify state:

    * ``new``       — customer's FIRST-EVER external order date falls in
                      the current period (regardless of channel)
    * ``growing``   — active both periods AND current ≥ prior × (1+threshold)
    * ``declining`` — active both periods AND current ≤ prior × (1-threshold)
    * ``stable``    — active both periods AND within ±threshold of prior
    * (``new``-fallback) — active current, NOT in prior, NOT first-ever
                      (e.g. returning after a long gap). Classified as
                      growing so the watchlist surfaces recovering accounts

    Plus a separate ``dormant`` list: customers who were active in the
    prior period but have ZERO orders in the current period — the
    "where did they go" signal that's invisible in any current-period
    table.

    ``growth_threshold`` is the relative band that separates stable from
    growing/declining; default ±10% matches the brief but is a parameter
    so the dashboard can tune it without touching this module.

    Returns ``{rows, dormant, summary, has_prior, prior_from, prior_to}``.
    ``summary`` is the counts per state. When ``has_prior`` is False
    (prior window extends before earliest imported week) every active
    customer is classified as ``new`` (literally) or growing (returning)
    based on first-order date alone.
    """
    n_weeks = ((end_wc - start_wc).days // 7) + 1
    prior_start_wc, prior_end_wc = _prior_window(start_wc, end_wc)
    earliest, _latest = available_week_range(dept)
    has_prior = prior_start_wc >= earliest

    cur_rows = per_customer_in_channel(dept, channel, start_wc, end_wc)
    prior_rows = (per_customer_in_channel(
        dept, channel, prior_start_wc, prior_end_wc) if has_prior else [])
    prior_by_id = {r["customer_id"]: r["total"] for r in prior_rows}

    # First-EVER external order date per current-period customer. Used
    # to distinguish "new this period" from "returning after a gap" —
    # both look the same in the prior_by_id miss case but mean very
    # different things commercially. Scope: external customers only
    # (the cur_rows IDs are already external; the explicit is_internal
    # filter here is belt + braces against a future call passing in
    # internal IDs).
    cur_customer_ids = [r["customer_id"] for r in cur_rows]
    first_orders = {}
    if cur_customer_ids:
        for cid, first in (Order.objects
                           .filter(customer_id__in=cur_customer_ids,
                                   customer__is_internal=False)
                           .values_list("customer_id")
                           .annotate(first=Min("order_date"))):
            first_orders[cid] = first

    out_rows = []
    summary = {"new": 0, "growing": 0, "declining": 0,
               "stable": 0, "dormant": 0}
    end = end_wc + timedelta(days=6)

    for r in cur_rows:
        cid = r["customer_id"]
        current = r["total"]
        prior = prior_by_id.get(cid)
        first = first_orders.get(cid)

        if first is not None and start_wc <= first <= end:
            state = "new"
            delta_pct = None
        elif prior is None or prior == 0:
            # Active now, NOT in prior period, NOT a first-ever order
            # → returning customer. Flag as growing so the watchlist
            # picks them up as recovering activity.
            state = "growing"
            delta_pct = None
        else:
            ratio = (current - prior) / prior
            delta_pct = (ratio * Decimal("100")).quantize(Decimal("0.1"))
            if ratio >= growth_threshold:
                state = "growing"
            elif ratio <= -growth_threshold:
                state = "declining"
            else:
                state = "stable"

        summary[state] += 1
        out_rows.append({
            "customer_id": cid,
            "name": r["name"],
            "current": current,
            "share_pct": r["pct"],
            "prior": _q2(prior) if prior is not None else Decimal("0.00"),
            "delta_pct": delta_pct,
            "state": state,
        })

    # Dormant: was active in prior period, zero in current. These
    # customers DON'T appear in cur_rows so they need their own pass.
    cur_ids = {r["customer_id"] for r in cur_rows}
    dormant_rows = []
    for r in prior_rows:
        if r["customer_id"] not in cur_ids:
            summary["dormant"] += 1
            dormant_rows.append({
                "customer_id": r["customer_id"],
                "name": r["name"],
                "prior": _q2(r["total"]),
            })

    return {
        "rows": out_rows,
        "dormant": dormant_rows,
        "summary": summary,
        "has_prior": has_prior,
        "prior_from": prior_start_wc,
        "prior_to": prior_end_wc,
    }


def range_product_revenue(dept, start_wc, end_wc, top_n=None):
    """Per-product ordered VALUE over a date range, biggest first, with
    cumulative %.

    The Pareto / 80-20 view: which products carry the revenue and how
    few of them you'd need to protect to cover most of the business.
    Aggregates ``qty_ordered × unit_price`` grouped by
    ``OrderLine.product_name`` (the SNAPSHOT, not the catalogue
    ``SaleProduct.name``) so a renamed or discontinued product still
    surfaces under the name it was actually sold as. External
    customers only (``is_internal=False``) — same scope as
    :func:`range_totals`.

    Sorted by ordered VALUE (£), not quantity — the existing
    :func:`week_product_day_matrix` sorts by qty for production
    planning; this helper exists because for commercial finance, a
    high-qty low-price item dominates qty but not revenue.

    Returns ``{rows, total_value, n_products, n_to_80pct,
    top_5_share_pct, top_10_share_pct}``. ``n_to_80pct`` is the number
    of rows needed for cumulative_pct to cross 80% (useful for "show
    top until 80% then collapse" UI). ``top_n`` truncates the row list
    after computation; the summary figures are over ALL products,
    not just the visible top_n.
    """
    end = end_wc + timedelta(days=6)
    rows = list((OrderLine.objects.filter(
        order__department=dept,
        order__order_date__range=(start_wc, end),
        order__customer__is_internal=False,
    ).values("product_name").annotate(
        qty=Sum("qty_ordered"),
        value=_line_value_expr(),
    ).order_by("-value")))

    total_value = sum((r["value"] or Decimal("0") for r in rows),
                      Decimal("0"))

    full = []
    cumulative = Decimal("0")
    for r in rows:
        value = r["value"] or Decimal("0")
        share = ((value / total_value * Decimal("100"))
                 if total_value else Decimal("0"))
        cumulative += share
        full.append({
            "product": r["product_name"],
            "qty": r["qty"] or Decimal("0"),
            "value": _q2(value),
            "share_pct": share.quantize(Decimal("0.1")),
            "cumulative_pct": cumulative.quantize(Decimal("0.1")),
        })

    n_to_80pct = next(
        (i + 1 for i, r in enumerate(full)
         if r["cumulative_pct"] >= Decimal("80")),
        len(full),
    )
    top_5_share = sum((r["share_pct"] for r in full[:5]),
                     Decimal("0")).quantize(Decimal("0.1"))
    top_10_share = sum((r["share_pct"] for r in full[:10]),
                      Decimal("0")).quantize(Decimal("0.1"))

    visible = full[:top_n] if top_n is not None else full

    return {
        "rows": visible,
        "total_value": _q2(total_value),
        "n_products": len(full),
        "n_to_80pct": n_to_80pct,
        "top_5_share_pct": top_5_share,
        "top_10_share_pct": top_10_share,
    }


def range_week_stats(dept, start_wc, end_wc):
    """Best / worst week + spread + variability across a range.

    Reuses :func:`per_week_split` so the figures reconcile byte-for-
    byte with the trend chart. Variability = stddev / mean as a
    percentage (coefficient of variation) — finance-friendly single
    figure for "how predictable is this period". Empty period → all
    Nones.
    """
    rows = per_week_split(dept, start_wc, end_wc)
    nonzero = [r for r in rows if r["total"]]
    if not nonzero:
        return {
            "best_week": None,
            "worst_week": None,
            "spread": Decimal("0.00"),
            "mean": Decimal("0.00"),
            "variability_pct": None,
            "n_active_weeks": 0,
        }
    hi = max(nonzero, key=lambda r: r["total"])
    lo = min(nonzero, key=lambda r: r["total"])
    spread = hi["total"] - lo["total"]
    totals = [r["total"] for r in nonzero]
    mean = sum(totals, Decimal("0")) / Decimal(len(totals))
    # Population standard deviation (we have the whole period, not a sample).
    variance = sum(((t - mean) ** 2 for t in totals), Decimal("0")) / Decimal(len(totals))
    # Decimal lacks sqrt; lift to float just for this scalar derivation
    # (every other figure in this module stays Decimal).
    stddev = Decimal(str(float(variance) ** 0.5))
    variability = ((stddev / mean * Decimal("100"))
                   .quantize(Decimal("0.1")) if mean else None)
    return {
        "best_week": {"week": hi["wc"], "total": hi["total"]},
        "worst_week": {"week": lo["wc"], "total": lo["total"]},
        "spread": _q2(spread),
        "mean": _q2(mean),
        "variability_pct": variability,
        "n_active_weeks": len(nonzero),
    }

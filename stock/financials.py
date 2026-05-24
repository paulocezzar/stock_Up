"""Channel-split aggregations for the Financials page.

Three-way classification of customers — already encoded on the
``Customer`` model, NOT re-derived from order-sheet provenance at
request time:

* ``customer_type == 'wholesale'`` — set by ``import_customers`` on
  every customer whose name appears in the WHOLESALE tab.
* ``customer_type == 'internal'`` AND ``is_internal == False`` — the
  Estate outlets (Garden Cafe, Farmshop, CBK, …) that fund the
  bakery's external "internal channel".
* ``is_internal == True`` — BAKERY INTERNAL USE + BAKERY WASTAGE
  (flipped by data migration 0024). EXCLUDED from every Financials
  total / channel / breakdown — they're the bakery's own consumption,
  not demand from anyone.

Every total in this module is computed from per-line snapshots
(``OrderLine.unit_price * qty_ordered`` summed in SQL via a single
aggregate) — same convention as ``Order.total_value()`` but pulled
out to one query per page so the dashboard stays fast at the Render
free-tier's 30s budget.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import DecimalField, F, Max, Min, Q, Sum

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
    customers entirely. Returns ``{internal, wholesale, total}`` all
    as 2dp Decimals.
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
        internal=Sum(
            F("qty_ordered") * F("unit_price"),
            filter=Q(order__customer__customer_type=Customer.INTERNAL),
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
    Always excludes ``is_internal=True`` (a safety net — those rows
    happen to be ``customer_type='internal'`` today but the safety
    net keeps the contract clean if that ever drifts). Returns
    ``[{customer_id, name, total, pct}]`` where ``pct`` is the
    customer's share of the channel total as a 1-dp Decimal.
    """
    end = end_wc + timedelta(days=6)
    rows = list(OrderLine.objects.filter(
        order__department=dept,
        order__order_date__range=(start_wc, end),
        order__customer__customer_type=channel,
        order__customer__is_internal=False,
    ).values(
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

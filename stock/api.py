"""DRF endpoints powering the React dashboard at /dashboard.

The dashboard is a thin frontend on top of the same aggregation
primitives the /financials/ page already uses — :mod:`stock.financials`.
Every figure here is COMPUTED from those primitives; this module owns
ZERO new SQL aggregation. If something can't be computed cheaply from
``range_totals`` / ``per_week_split`` / ``per_customer_in_channel`` /
the ``week_*`` helpers, we return ``None`` rather than fake it (see the
brief: "no hardcoded numbers, no re-derived aggregation").

Two modes, dispatched by presence of ``?week`` in the query string:

* **Week mode** (``?week=YYYY-MM-DD`` or just ``?week=``) — single-week
  view used by the dashboard's primary cards (daily trend, channel
  split, top customers, recent orders, WoW). Defaults the week to the
  latest imported week when the date is missing / invalid. Payload
  shape is documented inline on ``_build_week_payload``.

* **Range mode** (``?from=&to=`` or no params) — backwards-compatible
  multi-week view used by the original SPA scaffolding. Same payload
  shape this module shipped with so the older client keeps working
  while the SPA is being upgraded.

Strict label discipline: figures are "ordered / demand", never revenue /
sales / waste / margin. The bakery's own consumption (``is_internal``)
is already excluded by financials.py and never surfaces here.
"""
import csv
from datetime import date, timedelta
from decimal import Decimal

from django.http import HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .financials import (
    available_week_range, available_weeks,
    per_customer_in_channel, per_week_split, range_totals,
    recent_order_groups, week_channel_split, week_daily_totals,
    week_orders_count, week_over_week, week_product_day_matrix,
    week_top_customers,
)
from .models import Customer, Order, OrderLine
from .views import current_department


def _monday_of(d):
    return d - timedelta(days=d.weekday())


def _snap(raw, fallback):
    raw = (raw or "").strip()
    if not raw:
        return fallback
    try:
        return _monday_of(date.fromisoformat(raw))
    except ValueError:
        return fallback


def _q2(v):
    """Currency 2dp. Mirrors financials._q2 so payloads round identically."""
    return (v or Decimal("0")).quantize(Decimal("0.01"))


def _q1(v):
    """Percentage 1dp."""
    return (v or Decimal("0")).quantize(Decimal("0.1"))


def _pct(part, whole):
    if not whole:
        return Decimal("0.0")
    return _q1(part / whole * Decimal("100"))


def _empty_range_payload(from_wc, to_wc):
    """Zero-shape range payload — same keys as the real one so the SPA
    renders cleanly when there are no orders / no department yet."""
    zero = Decimal("0.00")
    return {
        "from": from_wc.isoformat(),
        "to": to_wc.isoformat(),
        "grand_total": str(zero),
        "internal": {"total": str(zero), "pct": "0.0"},
        "wholesale": {"total": str(zero), "pct": "0.0"},
        "avg_week": str(zero),
        "avg_day": str(zero),
        "latest_week": None,
        "weekly_trend": [],
        "top_wholesale": [],
        "top_internal": [],
        "summary": {
            "highest_week": None,
            "lowest_week": None,
            "top_wholesale": None,
            "top_internal": None,
            "internal_pct": "0.0",
            "wholesale_pct": "0.0",
        },
    }


def _empty_week_payload(week_wc):
    """Zero-shape week payload — every key still present so the SPA
    can render its skeletons without conditional chains."""
    zero = Decimal("0.00")
    return {
        "week_start": week_wc.isoformat(),
        "prev_week_start": None,
        "available_weeks": [],
        "total_ordered": str(zero),
        "total_orders": 0,
        "internal": {"total": str(zero), "pct": "0.0"},
        "wholesale": {"total": str(zero), "pct": "0.0"},
        "avg_day": str(zero),
        "wow": {"total": str(zero), "pct": None},
        "daily_trend": [
            {"date": (week_wc + timedelta(days=i)).isoformat(),
             "total": str(zero), "prev_week_total": str(zero)}
            for i in range(7)
        ],
        "top_wholesale": [],
        "top_internal": [],
        "recent_orders": [],
        "highest_day": None,
        "lowest_day": None,
        "product_day_matrix": [],
    }


def _build_range_payload(dept, from_wc, to_wc):
    """Backwards-compatible range view (multi-week)."""
    totals = range_totals(dept, from_wc, to_wc)
    weekly = per_week_split(dept, from_wc, to_wc)
    wholesale_rows = per_customer_in_channel(
        dept, Customer.WHOLESALE, from_wc, to_wc)
    internal_rows = per_customer_in_channel(
        dept, Customer.INTERNAL, from_wc, to_wc)

    grand = totals["total"]
    internal_pct = _pct(totals["internal"], grand)
    wholesale_pct = _pct(totals["wholesale"], grand)

    n_weeks = len(weekly) or 1
    avg_week = _q2(grand / n_weeks) if grand else Decimal("0.00")
    avg_day = _q2(grand / (n_weeks * 7)) if grand else Decimal("0.00")

    latest_week = None
    if weekly:
        last = weekly[-1]
        wow_pct = None
        if len(weekly) >= 2:
            prev = weekly[-2]["total"]
            if prev:
                wow_pct = float(
                    ((last["total"] - prev) / prev * Decimal("100"))
                    .quantize(Decimal("0.1")))
        latest_week = {
            "week": last["wc"].isoformat(),
            "total": str(last["total"]),
            "wow_pct": wow_pct,
        }

    highest_week = None
    lowest_week = None
    if weekly:
        hi = max(weekly, key=lambda r: r["total"])
        lo = min(weekly, key=lambda r: r["total"])
        highest_week = {"week": hi["wc"].isoformat(), "total": str(hi["total"])}
        lowest_week = {"week": lo["wc"].isoformat(), "total": str(lo["total"])}

    def _rows(rows):
        return [
            {"name": r["name"], "value": str(r["total"]), "pct": str(r["pct"])}
            for r in rows
        ]

    def _trend(rows):
        return [
            {
                "week": r["wc"].isoformat(),
                "internal": str(r["internal"]),
                "wholesale": str(r["wholesale"]),
                "total": str(r["total"]),
            }
            for r in rows
        ]

    return {
        "from": from_wc.isoformat(),
        "to": to_wc.isoformat(),
        "grand_total": str(grand),
        "internal": {"total": str(totals["internal"]),
                     "pct": str(internal_pct)},
        "wholesale": {"total": str(totals["wholesale"]),
                      "pct": str(wholesale_pct)},
        "avg_week": str(avg_week),
        "avg_day": str(avg_day),
        "latest_week": latest_week,
        "weekly_trend": _trend(weekly),
        "top_wholesale": _rows(wholesale_rows),
        "top_internal": _rows(internal_rows),
        "summary": {
            "highest_week": highest_week,
            "lowest_week": lowest_week,
            "top_wholesale": wholesale_rows[0]["name"] if wholesale_rows else None,
            "top_internal": internal_rows[0]["name"] if internal_rows else None,
            "internal_pct": str(internal_pct),
            "wholesale_pct": str(wholesale_pct),
        },
    }


def _build_week_payload(dept, week_wc, weeks):
    """Single-week view. ``weeks`` is the cached ``available_weeks(dept)``
    so we can compute ``available_weeks[]`` and locate prev-week daily
    totals without re-querying.
    """
    split = week_channel_split(dept, week_wc)
    total_ordered = _q2(split["internal"]["total"] + split["wholesale"]["total"])
    total_orders = week_orders_count(dept, week_wc)
    avg_day = _q2(total_ordered / Decimal("7")) if total_ordered else Decimal("0.00")
    wow = week_over_week(dept, week_wc)

    daily = week_daily_totals(dept, week_wc)
    # Per-day previous-week comparison: if we have a prior imported
    # week, fetch its daily totals once and zip in by weekday offset
    # (i = 0..6 → Mon..Sun). Otherwise prev_week_total is £0 across
    # the strip so the chart line renders flat at the baseline rather
    # than vanishing.
    prev_daily_by_offset = {}
    if wow["prev_week_start"] is not None:
        prev_rows = week_daily_totals(dept, wow["prev_week_start"])
        for i, r in enumerate(prev_rows):
            prev_daily_by_offset[i] = r["total"]
    daily_trend = []
    for i, r in enumerate(daily):
        daily_trend.append({
            "date": r["date"].isoformat(),
            "total": str(r["total"]),
            "prev_week_total": str(
                prev_daily_by_offset.get(i, Decimal("0.00"))),
        })

    top_wholesale = week_top_customers(dept, week_wc, Customer.WHOLESALE, n=5)
    top_internal = week_top_customers(dept, week_wc, Customer.INTERNAL, n=5)

    def _rows(rows):
        return [
            {"name": r["name"], "value": str(r["total"]), "pct": str(r["pct"])}
            for r in rows
        ]

    recent = recent_order_groups(dept, n=10)
    recent_payload = [
        {
            "date": g["date"].isoformat(),
            "customer": g["customer"],
            "channel": g["channel"],
            "line_count": g["line_count"],
            "ordered_total": str(g["ordered_total"]),
        }
        for g in recent
    ]

    # highest / lowest day picked from days with non-zero totals so a
    # quiet Tuesday doesn't masquerade as the trough when the bakery
    # genuinely had orders all week. Empty week → both null.
    nonzero = [r for r in daily if r["total"]]
    highest_day = None
    lowest_day = None
    if nonzero:
        hi = max(nonzero, key=lambda r: r["total"])
        lo = min(nonzero, key=lambda r: r["total"])
        highest_day = {"date": hi["date"].isoformat(), "total": str(hi["total"])}
        lowest_day = {"date": lo["date"].isoformat(), "total": str(lo["total"])}

    matrix = week_product_day_matrix(dept, week_wc, top_n=12)
    matrix_payload = [
        {
            "product": r["product"],
            "total_qty": str(r["total_qty"]),
            "daily": [str(q) for q in r["daily"]],
        }
        for r in matrix
    ]

    return {
        "week_start": week_wc.isoformat(),
        "prev_week_start": wow["prev_week_start"].isoformat()
                           if wow["prev_week_start"] else None,
        "available_weeks": [w.isoformat() for w in weeks],
        "total_ordered": str(total_ordered),
        "total_orders": total_orders,
        "internal": {"total": str(split["internal"]["total"]),
                     "pct": str(split["internal"]["pct"])},
        "wholesale": {"total": str(split["wholesale"]["total"]),
                      "pct": str(split["wholesale"]["pct"])},
        "avg_day": str(avg_day),
        "wow": {"total": str(wow["prev_total"]), "pct": wow["pct"]},
        "daily_trend": daily_trend,
        "top_wholesale": _rows(top_wholesale),
        "top_internal": _rows(top_internal),
        "recent_orders": recent_payload,
        "highest_day": highest_day,
        "lowest_day": lowest_day,
        "product_day_matrix": matrix_payload,
    }


@api_view(["GET"])
def dashboard_summary(request):
    """``GET /api/dashboard/summary/`` → JSON dashboard payload.

    Mode dispatch by query string:

    * ``?week=YYYY-MM-DD`` (or just ``?week=``) — single-week payload.
      The date snaps to its Monday so any day within the week resolves
      to that week; empty / missing / invalid defaults to the latest
      imported week.
    * ``?from=YYYY-MM-DD&to=YYYY-MM-DD`` (or no params at all) —
      multi-week range payload. Same snap-to-Monday rule and same
      defaults as the original implementation, kept verbatim for
      backwards compat with the older SPA client.
    """
    dept = current_department(request)
    if dept is None:
        wc = _monday_of(date.today())
        if "week" in request.GET:
            return Response(_empty_week_payload(wc))
        return Response(_empty_range_payload(wc, wc))

    if "week" in request.GET:
        weeks = available_weeks(dept)
        if weeks:
            default_week = weeks[0]
        else:
            default_week = _monday_of(date.today())
        week_wc = _snap(request.GET.get("week"), default_week)
        return Response(_build_week_payload(dept, week_wc, weeks))

    default_from, default_to = available_week_range(dept)
    from_wc = _snap(request.GET.get("from"), default_from)
    to_wc = _snap(request.GET.get("to"), default_to)
    if to_wc < from_wc:
        from_wc, to_wc = to_wc, from_wc

    return Response(_build_range_payload(dept, from_wc, to_wc))


@api_view(["GET"])
def dashboard_export_csv(request):
    """``GET /api/dashboard/export.csv?week=YYYY-MM-DD`` → CSV of every
    OrderLine in that week, EXCLUDING the bakery's own consumption
    (``is_internal``) — same external-only scope as the rest of the
    dashboard.

    Columns: ``date, customer, channel, product, qty, unit_price,
    line_value``. All currency 2dp; ``channel`` resolved live from the
    customer's classification (same partition rule as the dashboard).
    Week defaults to the latest imported week when missing / invalid.

    SessionAuth + IsAuthenticated come from the project-wide DRF
    defaults — same gate as :func:`dashboard_summary`.
    """
    dept = current_department(request)
    response = HttpResponse(content_type="text/csv")
    if dept is None:
        response["Content-Disposition"] = 'attachment; filename="orders.csv"'
        writer = csv.writer(response)
        writer.writerow([
            "date", "customer", "channel",
            "product", "qty", "unit_price", "line_value",
        ])
        return response

    weeks = available_weeks(dept)
    default_week = weeks[0] if weeks else _monday_of(date.today())
    week_wc = _snap(request.GET.get("week"), default_week)
    end = week_wc + timedelta(days=6)

    response["Content-Disposition"] = (
        f'attachment; filename="orders-{week_wc.isoformat()}.csv"')
    writer = csv.writer(response)
    writer.writerow([
        "date", "customer", "channel",
        "product", "qty", "unit_price", "line_value",
    ])

    lines = (OrderLine.objects
             .filter(order__department=dept,
                     order__order_date__range=(week_wc, end),
                     order__customer__is_internal=False)
             .select_related("order__customer")
             .order_by("order__order_date", "order__customer__name", "id"))
    for line in lines:
        cust = line.order.customer
        channel = ("wholesale" if cust.customer_type == Customer.WHOLESALE
                   else "internal")
        unit_price = line.unit_price if line.unit_price is not None else ""
        line_value = line.line_value if line.line_value is not None else ""
        writer.writerow([
            line.order.order_date.isoformat(),
            cust.name,
            channel,
            line.display_name,
            str(line.qty_ordered),
            str(unit_price),
            str(line_value),
        ])
    return response

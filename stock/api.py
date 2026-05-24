"""DRF endpoints powering the React dashboard at /dashboard.

The dashboard is a thin frontend on top of the same aggregation
primitives the /financials/ page already uses — :mod:`stock.financials`.
Every figure here is COMPUTED from those primitives; this module owns
ZERO new SQL aggregation. If something can't be computed cheaply from
``range_totals`` / ``per_week_split`` / ``per_customer_in_channel``, we
return ``None`` rather than fake it (see the brief: "no hardcoded
numbers, no re-derived aggregation").

Strict label discipline: figures are "ordered / demand", never revenue /
sales / waste / margin. The bakery's own consumption (``is_internal``)
is already excluded by financials.py and never surfaces here.
"""
from datetime import date, timedelta
from decimal import Decimal

from rest_framework.decorators import api_view
from rest_framework.response import Response

from .financials import (
    available_week_range, per_customer_in_channel,
    per_week_split, range_totals,
)
from .models import Customer
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


def _empty_payload(from_wc, to_wc):
    """Zero-shape payload — same keys as the real one so the SPA
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


@api_view(["GET"])
def dashboard_summary(request):
    """``GET /api/dashboard/summary/?from=&to=`` → JSON dashboard payload.

    Defaults the range to the full data window via
    :func:`available_week_range`. Dates snap to their Monday so any day
    within a week resolves to that week (same convention as
    ``/financials/``). Returns 2dp currency strings and 1dp percentage
    strings so the SPA shows exactly the same numbers the Django
    Financials page does — no client-side rounding skew.
    """
    dept = current_department(request)
    if dept is None:
        wc = _monday_of(date.today())
        return Response(_empty_payload(wc, wc))

    default_from, default_to = available_week_range(dept)
    from_wc = _snap(request.GET.get("from"), default_from)
    to_wc = _snap(request.GET.get("to"), default_to)
    if to_wc < from_wc:
        from_wc, to_wc = to_wc, from_wc

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

    # latest_week + week-on-week %. Only meaningful when there are >=2
    # weeks AND the previous week is non-zero — otherwise wow_pct is
    # null (the SPA renders "—" rather than an Infinity / divide-by-0).
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

    # highest / lowest weeks for the summary block.
    highest_week = None
    lowest_week = None
    if weekly:
        hi = max(weekly, key=lambda r: r["total"])
        lo = min(weekly, key=lambda r: r["total"])
        highest_week = {"week": hi["wc"].isoformat(), "total": str(hi["total"])}
        lowest_week = {"week": lo["wc"].isoformat(), "total": str(lo["total"])}

    def _rows(rows):
        return [
            {
                "name": r["name"],
                "value": str(r["total"]),
                "pct": str(r["pct"]),
            }
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

    return Response({
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
    })

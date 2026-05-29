"""Template helpers for the shared design-system pages.

`startswith` mirrors the Business Performance React rail's active-item
rule (`path === href || path.startsWith(href)`) so a detail page like
/products/12/ keeps its section highlighted.

`gbp` / `order_count` produce BP's display formats for KPI-tile slots
(currency with a thousands separator + 2dp; a pluralised order count),
returning an em dash for empty values to match the dashboard's blanks.
"""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

DASH = "—"  # em dash, matches the dashboard's empty marker


@register.filter
def startswith(value, prefix):
    return str(value).startswith(str(prefix))


@register.filter
def gbp(value):
    """Format money the BP way: "£18,001.30". Empty/zero/None -> em dash."""
    if value is None:
        return DASH
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return DASH
    if amount == 0:
        return DASH
    return f"£{amount:,.2f}"


@register.filter
def order_count(value):
    """"4 orders" / "1 order"; empty/zero/None -> em dash."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DASH
    if n == 0:
        return DASH
    return f"{n} order{'' if n == 1 else 's'}"

"""Template filters for human-readable pack-size formatting.

Pack weights are stored in the ingredient's base unit (g/ml/each). For
display we promote to kg / L when the number is at least 1000.
"""

from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()


def _fmt(d):
    try:
        d = Decimal(d)
    except (InvalidOperation, TypeError, ValueError):
        return ""
    s = format(d.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


@register.filter
def pack_size(weight, unit):
    """Render a pack weight nicely.

    25000, "g"  -> "25 kg"
    1500,  "g"  -> "1.5 kg"
    500,   "g"  -> "500 g"
    1500,  "ml" -> "1.5 L"
    500,   "ml" -> "500 ml"
    12,    "ea" -> "12 ea"
    """
    if weight is None or weight == "":
        return ""
    try:
        w = Decimal(weight)
    except (InvalidOperation, TypeError, ValueError):
        return ""
    if unit == "g":
        return f"{_fmt(w / 1000)} kg" if w >= 1000 else f"{_fmt(w)} g"
    if unit == "ml":
        return f"{_fmt(w / 1000)} L" if w >= 1000 else f"{_fmt(w)} ml"
    return f"{_fmt(w)} ea"

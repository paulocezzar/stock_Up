"""Template helpers for the shared design-system navigation.

`startswith` mirrors the Business Performance React rail's active-item
rule (`path === href || path.startsWith(href)`) so a detail page like
/products/12/ keeps its section highlighted.
"""

from django import template

register = template.Library()


@register.filter
def startswith(value, prefix):
    return str(value).startswith(str(prefix))

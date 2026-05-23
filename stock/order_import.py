"""Import a customer's weekly orders from the bakery order sheet.

The order-sheet workbook has one customer per tab. Each tab is shaped
like the Garden Café form:

    row 4 col 1   "BAKERY ORDER FORM" (header marker)
    row 4 col 6   "Ordered by" value (operator contact)
    row 7         day-of-week labels ("Monday" .. "Sunday") at cols
                  3, 6, 9, 12, 15, 18, 21 (every day uses 3 columns:
                  Ordered / Sent / Comments)
    row 8         the 7 dates of the week at the same columns
    row 9         column-group headers (``SKU, Product, Price``,
                  then ``Ordered, Sent, Comments`` × 7, then
                  ``Total``)
    row 10+       product rows: SKU at col 0, name at col 1, price
                  at col 2, ordered qty per day at cols 3 / 6 / 9
                  / 12 / 15 / 18 / 21 — blank/zero cells skipped.
                  A blank row in the middle of the products section
                  is skipped (the sheet sometimes inserts spacing).
                  A totals row at the bottom (col 0 / col 1 blank,
                  numbers in the day columns) terminates the scan.

``import_orders_for_tab`` is the reusable entry-point used by both
the ``import_orders`` management command and the matching tests.
It's idempotent on ``(customer, date)``: every existing order for
that customer on each of the seven sheet-dates is wiped and rebuilt
from the workbook, so re-running on a deploy converges to the
sheet's current state. Lines whose product can't be resolved
(unknown Sage code AND no matching product name) are recorded in
``failures`` and skipped — one bad row never aborts the rest.
"""
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
import datetime

from django.db import transaction

# Day-column offsets within each tab — 3-cell stride (Ordered /
# Sent / Comments). The "ordered" cell is the one we care about.
DAY_COL_ORDERED = [3, 6, 9, 12, 15, 18, 21]
DAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday"]

# openpyxl row indices are 1-based. Mapped to the GARDEN CAFE layout
# (and the rest of the order-sheet tabs that follow the same template):
#   row 8  — day-of-week labels (Monday .. Sunday)
#   row 9  — the seven dates (Mon..Sun)
#   row 10 — column-group headers (SKU / Product / Price / Ordered ...)
#   row 11 — first product row
DATE_ROW = 9
PRODUCT_FIRST_ROW = 11


def _as_text(v):
    if v is None:
        return ""
    s = str(v).strip()
    if isinstance(v, float) and v.is_integer():
        s = str(int(v))
    return s


def _as_qty(v):
    """Parse a quantity cell. Blank / 0 / non-numeric → None (skip)."""
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    if d <= 0:
        return None
    return d


def _date_from_cell(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return None


def read_tab_dates(ws):
    """Return the 7 (Mon..Sun) order dates from row 8 of the tab.

    Raises ``ValueError`` if the row doesn't look like a 7-date strip
    (any column blank, or the days aren't 1-day apart Mon..Sun). The
    week-commencing Monday is always derived from the dates — we
    never read it from a header field.
    """
    rows = list(ws.iter_rows(min_row=DATE_ROW, max_row=DATE_ROW,
                             values_only=True))
    if not rows:
        raise ValueError("date row missing")
    row = rows[0]
    dates = []
    for col in DAY_COL_ORDERED:
        if col >= len(row):
            raise ValueError(f"date row too short — column {col} missing")
        d = _date_from_cell(row[col])
        if d is None:
            raise ValueError(f"date column {col} doesn't carry a date")
        dates.append(d)
    # Mon..Sun: each date is one day after the previous, and the first
    # is a Monday (weekday() == 0).
    if dates[0].weekday() != 0:
        raise ValueError(
            f"first date {dates[0]} is a {dates[0].strftime('%A')}, "
            "not a Monday")
    for i in range(1, 7):
        if dates[i] - dates[i - 1] != datetime.timedelta(days=1):
            raise ValueError(
                f"dates aren't consecutive: {dates[i-1]} -> {dates[i]}")
    return dates


def iter_product_rows(ws):
    """Yield ``{sage, name, price, qtys}`` dicts for each non-empty
    product row in the tab.

    ``qtys`` is a list of 7 Decimals-or-None aligned to Mon..Sun
    (cells with no qty come back as ``None``). Rows whose SKU and
    Product name are both blank are silently skipped (the sheet
    sometimes inserts spacing or a totals row above the data). The
    scan terminates the first time it sees a row whose product name
    is blank AND any day-Ordered column carries a number — the bakery
    totals row at the bottom of the sheet.
    """
    for row in ws.iter_rows(min_row=PRODUCT_FIRST_ROW, values_only=True):
        sku = _as_text(row[0]) if len(row) > 0 else ""
        name = _as_text(row[1]) if len(row) > 1 else ""
        # Totals row (no product name, but numbers in day columns) — stop.
        if not name:
            day_has_number = any(
                isinstance(row[c], (int, float)) and row[c] not in (None, 0)
                for c in DAY_COL_ORDERED if c < len(row))
            if day_has_number:
                return
            # Otherwise a blank spacer row — skip and keep scanning.
            continue
        price = _parse_price(row[2] if len(row) > 2 else None)
        qtys = []
        for col in DAY_COL_ORDERED:
            qtys.append(_as_qty(row[col]) if col < len(row) else None)
        yield {"sage": sku, "name": name, "price": price, "qtys": qtys}


def _parse_price(v):
    """Best-effort Decimal from a Price cell. Strips a leading "£" so
    string cells like "£6.25" round-trip. Returns ``None`` on blanks
    or unparseable values — historical lines may carry a name with no
    price, and the importer should still record them rather than
    silently dropping the row."""
    if v is None or v == "":
        return None
    if isinstance(v, str):
        v = v.strip().lstrip("£").strip()
        if not v:
            return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _build_product_lookups(dept):
    """Index this dept's SaleProducts by Sage no. and by name (both
    case-insensitive, whitespace-trimmed) so the importer's hot loop
    doesn't hammer the database."""
    from .models import SaleProduct
    by_sage = {}
    by_name = {}
    for sp in SaleProduct.objects.filter(department=dept):
        sage_key = (sp.sage_number or "").strip().lower()
        if sage_key and sage_key != "0":
            by_sage.setdefault(sage_key, sp)
        name_key = (sp.name or "").strip().lower()
        if name_key:
            by_name.setdefault(name_key, sp)
    return by_sage, by_name


def _match_product(row, by_sage, by_name):
    """Resolve a sheet row to a SaleProduct.

    Sage No. wins when present (it's the operator's authoritative
    code); exact-name match is the fallback so products without a
    Sage code on the sheet still link if their name matches a known
    SKU verbatim. Returns ``None`` when neither matches — the caller
    surfaces the row as a failure.
    """
    sage = (row.get("sage") or "").strip().lower()
    if sage and sage != "0":
        sp = by_sage.get(sage)
        if sp is not None:
            return sp
    name = (row.get("name") or "").strip().lower()
    if name:
        sp = by_name.get(name)
        if sp is not None:
            return sp
    return None


@transaction.atomic
def import_orders_for_tab(workbook, tab_name, customer, dept):
    """Import every product × day cell on ``tab_name`` for ``customer``.

    Replaces (idempotently) every existing order for ``customer`` on
    each of the seven sheet-dates: their OrderLines are wiped first,
    then re-created from the workbook. Orders left with no lines
    after the rebuild (e.g. a product row whose week is entirely
    blank) are deleted so the database mirrors the sheet exactly.

    Returns ``{dates, lines_imported, products_matched,
    products_unmatched, failures}``:
      * ``dates`` — the 7 Mon..Sun dates resolved from the sheet
      * ``lines_imported`` — the count of OrderLines now in place
      * ``products_matched`` — distinct SaleProducts that landed lines
      * ``products_unmatched`` — list of ``(sage, name)`` for rows
        whose SaleProduct couldn't be resolved
      * ``failures`` — free-text notes for malformed rows
    """
    from .models import Order, OrderLine
    if tab_name not in workbook.sheetnames:
        raise ValueError(f"workbook has no '{tab_name}' tab")
    ws = workbook[tab_name]
    dates = read_tab_dates(ws)
    by_sage, by_name = _build_product_lookups(dept)

    # Wipe existing lines for this customer × dates so re-running the
    # importer converges to the sheet. Done in one queryset to avoid
    # N+1 deletes. Orders themselves are kept (and recreated below if
    # missing) so a later qty_sent column has a stable row to write to.
    OrderLine.objects.filter(
        order__customer=customer,
        order__department=dept,
        order__order_date__in=dates,
    ).delete()

    lines_imported = 0
    products_matched = set()
    products_unmatched = []
    failures = []

    # Cache (date → Order) so the per-row loop never refetches.
    order_by_date = {
        o.order_date: o
        for o in Order.objects.filter(
            customer=customer, department=dept, order_date__in=dates)
    }

    for row in iter_product_rows(ws):
        sp = _match_product(row, by_sage, by_name)
        # Snapshot the sheet's name + price on EVERY line — even when
        # no current catalogue product matches. Historical lines
        # (discontinued SKUs like "Almond Pastry", "Hot Cross Buns")
        # need to keep their financial value; matched lines also keep
        # the price the customer was actually charged on the day,
        # which protects the total from later catalogue edits.
        sheet_name = (row.get("name") or "").strip()
        sheet_price = row.get("price")  # Decimal or None
        if sp is None:
            products_unmatched.append((row.get("sage") or "",
                                       sheet_name))
        for i, qty in enumerate(row["qtys"]):
            if qty is None:
                continue
            day = dates[i]
            order = order_by_date.get(day)
            if order is None:
                order = Order.objects.create(
                    customer=customer, department=dept,
                    order_date=day)
                order_by_date[day] = order
            OrderLine.objects.create(
                order=order, sale_product=sp,
                product_name=sheet_name,
                unit_price=sheet_price,
                qty_ordered=qty)
            lines_imported += 1
            if sp is not None:
                products_matched.add(sp.pk)

    # Sweep orders that ended up with no lines after the rebuild —
    # mirrors the sheet exactly (a customer with no orders on a given
    # day has no Order row for it).
    Order.objects.filter(
        customer=customer, department=dept, order_date__in=dates,
        lines__isnull=True,
    ).delete()

    return {
        "dates": dates,
        "lines_imported": lines_imported,
        "products_matched": len(products_matched),
        "products_unmatched": products_unmatched,
        "failures": failures,
    }


def import_orders(file_or_path, *, tabs=None):
    """Read one or more customer tabs from the order-sheet workbook.

    ``tabs`` defaults to ``["GARDEN CAFE"]`` — chunk 2 only imports the
    Garden Café tab so the whole pipeline can be verified end-to-end
    on a single customer before scaling. Returns a dict per tab plus
    a top-level summary.

    Streams the workbook in ``read_only=True, data_only=True`` mode
    so a heavily formatted source doesn't blow the deploy worker's
    memory (the same defensive pattern the recipe importer uses).
    Tabs that fail to import (missing customer, malformed dates,
    etc.) are recorded in ``failures`` and don't abort the rest.
    """
    from openpyxl import load_workbook
    from .models import Customer, Department

    if tabs is None:
        tabs = ["GARDEN CAFE"]

    wb = load_workbook(file_or_path, read_only=True, data_only=True)
    try:
        results = OrderedDict()
        failures = []
        for tab in tabs:
            try:
                customer = Customer.objects.filter(name__iexact=tab).first()
                if customer is None:
                    failures.append(
                        (tab, "no Customer with that name — run "
                              "import_customers first"))
                    continue
                dept = customer.department or Department.objects.filter(
                    name="Bakery").first()
                if dept is None:
                    failures.append(
                        (tab, "customer has no department and no Bakery "
                              "fallback exists"))
                    continue
                results[tab] = import_orders_for_tab(wb, tab, customer, dept)
            except Exception as e:  # noqa: BLE001 — keep going past a bad tab
                failures.append((tab, f"{type(e).__name__}: {e}"))
                continue
        return {
            "tabs_processed": len(tabs),
            "tabs_imported": len(results),
            "per_tab": results,
            "failures": failures,
        }
    finally:
        wb.close()

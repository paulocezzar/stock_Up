"""Import customers from the bakery order-sheet workbook.

Usage:
    python manage.py import_customers data/order_sheet.xlsm
    python manage.py import_customers data/order_sheet.xlsm --department Bakery

Reads two sheets:

  Customers    columns "Customer Name", "Location", "Ordered by" — one row
               per Estate outlet or named contact. Some rows have only an
               "Ordered by" with no name (staff-only entries); those are
               skipped.
  WHOLESALE    column 1 ("Wholesale Customer") from row 11 down — the
               authoritative list of wholesale accounts. A customer is
               classified ``wholesale`` iff their name appears here
               (case-insensitive). Everything else is ``internal``.

Wholesale accounts that exist ONLY in the WHOLESALE tab (e.g. PINKMANS
branches, SOCIETY branches) are imported too, with empty location/contact.

Idempotent on name: re-running updates location / ordered_by / type but
leaves ``is_type_manual=True`` records' types alone (so an operator's
manual classification survives the next import — same pattern as
``Recipe.is_sold_manual``).
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook

from stock.models import Customer, Department


def _norm(s):
    if s is None:
        return ""
    return str(s).strip()


def _read_customers_tab(ws):
    """Yield ``{name, location, ordered_by}`` dicts from the Customers sheet.

    Header row (row 1) is skipped. Rows with no Customer Name in column 0
    are skipped — they're the trailing staff-only "Ordered by" entries.
    """
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = _norm(row[0]) if row else ""
        if not name:
            continue
        location = _norm(row[1]) if len(row) > 1 else ""
        # Column 2 is a blank spacer in the workbook; "Ordered by" is at 3.
        ordered_by = _norm(row[3]) if len(row) > 3 else ""
        out.append({"name": name, "location": location,
                    "ordered_by": ordered_by})
    return out


def _read_wholesale_names(ws):
    """Distinct names from column 0 of the WHOLESALE sheet, row 11 down.

    Preserves the first-seen casing for each name (matters for display).
    The "Wholesale Customer" label in the header row is skipped.
    """
    out = []
    seen = set()
    for row in ws.iter_rows(min_row=11, values_only=True):
        if not row:
            continue
        v = row[0]
        if v is None:
            continue
        name = str(v).strip()
        if not name:
            continue
        if name.lower() == "wholesale customer":
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


class Command(BaseCommand):
    help = "Import customers from an order-sheet .xlsm (Customers + WHOLESALE tabs)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the order-sheet workbook")
        parser.add_argument(
            "--department", default="Bakery",
            help="Department to attach the customers to (default: Bakery)")

    @transaction.atomic
    def handle(self, *args, **opts):
        wb = load_workbook(opts["path"], data_only=True)
        for required in ("Customers", "WHOLESALE"):
            if required not in wb.sheetnames:
                raise CommandError(f"workbook has no '{required}' sheet")

        dept, _ = Department.objects.get_or_create(name=opts["department"])

        customer_rows = _read_customers_tab(wb["Customers"])
        wholesale_names = _read_wholesale_names(wb["WHOLESALE"])
        wholesale_keys = {n.lower() for n in wholesale_names}

        created = updated = preserved_manual = 0
        n_internal = n_wholesale = 0

        # Case-insensitive lookup of existing Customer rows by name so we
        # don't accidentally fork a "TEALS" / "Teals" pair on later runs.
        existing_by_key = {c.name.lower(): c for c in Customer.objects.all()}

        def _upsert(name, location, ordered_by, is_wholesale):
            nonlocal created, updated, preserved_manual
            target_type = Customer.WHOLESALE if is_wholesale else Customer.INTERNAL
            key = name.lower()
            existing = existing_by_key.get(key)
            if existing is None:
                c = Customer.objects.create(
                    name=name, location=location, ordered_by=ordered_by,
                    customer_type=target_type, is_type_manual=False,
                    department=dept,
                )
                existing_by_key[key] = c
                created += 1
                return c
            # Update common fields; respect a manual type override.
            existing.location = location
            existing.ordered_by = ordered_by
            existing.department = dept
            if existing.is_type_manual:
                preserved_manual += 1
            else:
                existing.customer_type = target_type
            existing.save()
            updated += 1
            return existing

        seen_keys = set()

        for row in customer_rows:
            key = row["name"].lower()
            seen_keys.add(key)
            is_wholesale = key in wholesale_keys
            _upsert(row["name"], row["location"], row["ordered_by"], is_wholesale)
            if is_wholesale:
                n_wholesale += 1
            else:
                n_internal += 1

        # Wholesale-only accounts: in WHOLESALE tab but not in Customers tab.
        for w_name in wholesale_names:
            if w_name.lower() in seen_keys:
                continue
            seen_keys.add(w_name.lower())
            _upsert(w_name, "", "", True)
            n_wholesale += 1

        self.stdout.write(self.style.SUCCESS(
            f"Imported customers into '{dept.name}':"))
        self.stdout.write(
            f"  {created} created, {updated} updated")
        self.stdout.write(
            f"  {n_internal} internal, {n_wholesale} wholesale")
        if preserved_manual:
            self.stdout.write(self.style.WARNING(
                f"  Preserved {preserved_manual} manual type override(s)"))

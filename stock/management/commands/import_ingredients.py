"""Import the ingredient master from the supplier spec spreadsheet.

Usage:
    python manage.py import_ingredients data/ingredients.xlsx
    python manage.py import_ingredients data/ingredients.xlsx --department Bakery
    python manage.py import_ingredients data/ingredients.xlsx --supplier "Master Catalog"

Reads two tabs:
  Ingredients      master row per ingredient (NPD-I code, name, cost, supply unit, category)
  Units Of Measure converts a supply unit to a reference weight (e.g. Trade Paper Sack = 16 Kilograms)

For each ingredient row a Product is created/updated keyed on code. The pack weight comes
from the matching UOM row, normalised to base units (g for kg/grams, ml for litres).
Ingredients with no usable UOM row are still imported, but with no pack price - the command
prints them at the end so they can be addressed manually.
"""
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook
from stock.models import Department, Supplier, Product, SupplierPrice


CATEGORY_MAP = {
    "dry goods": "dry_goods",
    "dairy & eggs": "dairy_eggs",
    "dairy and eggs": "dairy_eggs",
    "frozen goods": "frozen_goods",
    "fruit & veg": "fruit_veg",
    "fruit and veg": "fruit_veg",
    "unassigned": "unassigned",
}

# RUOM (reference unit) → (multiplier to base unit, base unit). Anything not listed
# here (e.g. another supply-unit name) is resolved indirectly via the same code's
# other UOM rows.
BASE_UNITS = {
    "kilograms": (Decimal("1000"), "g"),
    "kilogram": (Decimal("1000"), "g"),
    "kilos": (Decimal("1000"), "g"),
    "kilo": (Decimal("1000"), "g"),
    "kg": (Decimal("1000"), "g"),
    "grams": (Decimal("1"), "g"),
    "gram": (Decimal("1"), "g"),
    "g": (Decimal("1"), "g"),
    "litres": (Decimal("1000"), "ml"),
    "litre": (Decimal("1000"), "ml"),
    "liters": (Decimal("1000"), "ml"),
    "l": (Decimal("1000"), "ml"),
    "millilitres": (Decimal("1"), "ml"),
    "ml": (Decimal("1"), "ml"),
}


def norm(s):
    if s is None:
        return ""
    return str(s).strip().lower()


def dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def resolve_weight(code, supply_unit, uom_by_code, _seen=None):
    """Walk the UOM rows for this code to find (pack_weight, base_unit).

    UOM rows can chain (e.g. Box → 40 Pack → 0.25 Kilograms). We follow the
    chain until we hit a recognised base unit, with a guard against cycles.
    If the supply unit is itself a base unit name (e.g. "Kilograms"), we treat
    the pack as 1 × that unit — no UOM row needed.
    Returns (Decimal pack_weight in base unit, base unit code) or None.
    """
    _seen = _seen or set()
    key = norm(supply_unit)
    if not key or key in _seen:
        return None
    if key in BASE_UNITS:
        mult, base = BASE_UNITS[key]
        return (mult, base)
    _seen.add(key)
    rows = uom_by_code.get(code, [])
    for row in rows:
        if norm(row["uom"]) != key:
            continue
        qty = row["quantity"] or Decimal("1")
        ref_qty = row["ref_quantity"]
        ruom = row["ruom"]
        if ref_qty is None:
            continue
        ruom_key = norm(ruom)
        if ruom_key in BASE_UNITS:
            mult, base = BASE_UNITS[ruom_key]
            return (qty * ref_qty * mult, base)
        # RUOM is another supply unit on the same code - resolve recursively.
        nested = resolve_weight(code, ruom, uom_by_code, _seen)
        if nested:
            inner_weight, base = nested
            return (qty * ref_qty * inner_weight, base)
    return None


class Command(BaseCommand):
    help = "Import ingredients (Products + SupplierPrices) from the Excel master."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to ingredients.xlsx")
        parser.add_argument("--department", default="Bakery",
                            help="Department to assign ingredients to (default: Bakery)")
        parser.add_argument("--supplier", default="Master Catalog",
                            help="Supplier name to attach pack prices to (default: Master Catalog)")

    @transaction.atomic
    def handle(self, *args, **opts):
        wb = load_workbook(opts["path"], data_only=True)
        if "Ingredients" not in wb.sheetnames:
            raise CommandError("workbook has no 'Ingredients' sheet")
        if "Units Of Measure" not in wb.sheetnames:
            raise CommandError("workbook has no 'Units Of Measure' sheet")

        dept, _ = Department.objects.get_or_create(name=opts["department"])
        supplier, _ = Supplier.objects.get_or_create(name=opts["supplier"])

        uom_by_code = self._read_uom(wb["Units Of Measure"])

        created = updated = priced = no_uom = 0
        flagged = []  # ingredients with no usable pack weight
        for row in wb["Ingredients"].iter_rows(min_row=2, values_only=True):
            code = row[0]
            if not code or str(code).strip() == "":
                continue
            code = str(code).strip()
            name = (row[1] or "").strip()
            cost = dec(row[33])
            supply_unit = row[34]
            category_raw = norm(row[35])
            category = CATEGORY_MAP.get(category_raw, "unassigned")

            weight_info = resolve_weight(code, supply_unit, uom_by_code)
            base_unit = weight_info[1] if weight_info else "g"

            product, was_created = Product.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "unit": base_unit,
                    "department": dept,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

            if weight_info and cost is not None:
                pack_weight, _ = weight_info
                existing = (SupplierPrice.objects
                            .filter(product=product, supplier=supplier)
                            .order_by("-effective_date", "-id").first())
                if existing:
                    existing.pack_weight = pack_weight
                    existing.pack_price = cost
                    existing.save()
                else:
                    SupplierPrice.objects.create(
                        product=product, supplier=supplier,
                        pack_weight=pack_weight, pack_price=cost,
                    )
                priced += 1
            else:
                no_uom += 1
                flagged.append((code, name, supply_unit, "no UOM" if not weight_info else "no cost"))

        self.stdout.write(self.style.SUCCESS(
            f"Imported ingredients into '{dept.name}' via supplier '{supplier.name}':"))
        self.stdout.write(f"  {created} created, {updated} updated")
        self.stdout.write(f"  {priced} with pack weight + price, {no_uom} flagged (no pack info)")
        if flagged:
            self.stdout.write(self.style.WARNING("  Flagged ingredients (needs attention):"))
            for code, name, supply_unit, reason in flagged:
                self.stdout.write(f"    {code}  {name}  [{supply_unit}]  - {reason}")

    def _read_uom(self, ws):
        """Index UOM rows by code so we can resolve indirect chains."""
        out = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            code = row[0]
            if not code:
                continue
            code = str(code).strip()
            out.setdefault(code, []).append({
                "uom": row[2],
                "quantity": dec(row[3]) or Decimal("1"),
                "ruom": row[4],
                "ref_quantity": dec(row[5]),
            })
        return out

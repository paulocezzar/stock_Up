"""Import sale products (sellable SKUs) from the order-sheet workbook.

Usage:
    python manage.py import_sale_products data/order_sheet.xlsm
    python manage.py import_sale_products data/order_sheet.xlsm --department Bakery

Reads the "Products" tab and creates / updates SaleProduct rows
idempotently by name. Auto-links each to a Recipe by Sage No. first,
then exact name as fallback. Manual links and hand-created rows are
preserved across re-runs — same protection pattern as Customers.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from stock.models import Department
from stock.sale_product_import import import_sale_products


class Command(BaseCommand):
    help = "Import sale products from an order-sheet .xlsm's Products tab."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the order-sheet workbook")
        parser.add_argument(
            "--department", default="Bakery",
            help="Department to attach the sale products to (default: Bakery)")

    @transaction.atomic
    def handle(self, *args, **opts):
        dept, _ = Department.objects.get_or_create(name=opts["department"])
        try:
            stats = import_sale_products(opts["path"], dept)
        except ValueError as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.SUCCESS(
            f"Imported sale products into '{dept.name}':"))
        self.stdout.write(
            f"  {stats['rows']} row(s) read, "
            f"{stats['created']} created, {stats['updated']} updated")
        self.stdout.write(
            f"  Linked: {stats['linked_via_sage']} via Sage, "
            f"{stats['linked_via_name']} via exact name; "
            f"{stats['unlinked']} unlinked")
        if stats["skipped_manual"]:
            self.stdout.write(self.style.WARNING(
                f"  Skipped {stats['skipped_manual']} hand-created row(s) "
                "(is_manual_entry=True)"))

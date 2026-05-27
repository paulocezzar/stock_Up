"""Import a week's orders from the bakery order-sheet workbook.

Usage:
    python manage.py import_orders data/order_sheet.xlsm
    python manage.py import_orders data/order_sheet.xlsm --tab "GARDEN CAFE"

Chunk 2 scope: imports the Garden Café tab only by default. The
workbook has one tab per customer; the per-tab parser is reusable
so adding more tabs later is a one-line change. Idempotent on
(customer, date): re-running converges to the sheet's current state.
"""
from django.core.management.base import BaseCommand, CommandError

from stock.order_import import import_orders


class Command(BaseCommand):
    help = ("Import a customer week from the bakery order-sheet workbook. "
            "Defaults to the GARDEN CAFE tab.")

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the order-sheet .xlsm")
        parser.add_argument(
            "--tab", action="append",
            help="Customer tab to import (repeat for several; defaults to "
                 "GARDEN CAFE)")

    def handle(self, *args, **opts):
        tabs = opts.get("tab") or ["GARDEN CAFE"]
        try:
            summary = import_orders(opts["path"], tabs=tabs)
        except FileNotFoundError as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.SUCCESS("Imported orders:"))
        self.stdout.write(
            f"  {summary['tabs_processed']} tab(s) requested, "
            f"{summary['tabs_imported']} imported")
        for tab, result in summary["per_tab"].items():
            extra = ""
            if "customers_imported" in result:
                extra = f", {result['customers_imported']} wholesale customer(s)"
            self.stdout.write(
                f"  {tab}: {result['lines_imported']} line(s), "
                f"{result['products_matched']} product(s) matched{extra}")
            if result.get("products_unmatched"):
                self.stdout.write(self.style.WARNING(
                    f"    {len(result['products_unmatched'])} unmatched row(s):"))
                for sage, name in result["products_unmatched"]:
                    self.stdout.write(f"      sage={sage!r} name={name!r}")
        unmatched_names = summary.get("wholesale_customer_unmatched") or []
        if unmatched_names:
            self.stdout.write(self.style.WARNING(
                f"  {len(unmatched_names)} wholesale name(s) with no Customer "
                f"row — add them manually to capture their revenue:"))
            for name in unmatched_names:
                self.stdout.write(f"    {name!r}")
        if summary.get("failures"):
            self.stdout.write(self.style.WARNING("  Tab failures:"))
            for tab, reason in summary["failures"]:
                self.stdout.write(f"    {tab}: {reason}")

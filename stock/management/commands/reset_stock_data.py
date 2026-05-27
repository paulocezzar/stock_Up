"""Wipe all stock-related data so the catalogue can be re-imported clean.

Usage:
    python manage.py reset_stock_data --yes

Deletes Products, SupplierPrices, Stocktakes, StockLines, Deliveries, Batches and
Adjustments. Leaves Departments, Suppliers, users and any other auth/app structure
intact. Requires --yes to actually run, to make accidental invocation harder.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from stock.models import (
    Product, SupplierPrice, Stocktake, StockLine,
    Delivery, Batch, Adjustment,
)


class Command(BaseCommand):
    help = "Delete all stock content (products, prices, stocktakes, deliveries, etc.). Run deliberately."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true",
                            help="Confirm the wipe. Without this nothing is deleted.")

    @transaction.atomic
    def handle(self, *args, **opts):
        counts_before = {
            "Adjustments": Adjustment.objects.count(),
            "Batches": Batch.objects.count(),
            "Deliveries": Delivery.objects.count(),
            "StockLines": StockLine.objects.count(),
            "Stocktakes": Stocktake.objects.count(),
            "SupplierPrices": SupplierPrice.objects.count(),
            "Products": Product.objects.count(),
        }

        if not opts["yes"]:
            self.stdout.write(self.style.WARNING(
                "Refusing to delete without --yes. Counts that would be cleared:"))
            for label, n in counts_before.items():
                self.stdout.write(f"  {label}: {n}")
            return

        # Order matters: child rows first to avoid PROTECT failures.
        Adjustment.objects.all().delete()
        Batch.objects.all().delete()
        Delivery.objects.all().delete()
        StockLine.objects.all().delete()
        Stocktake.objects.all().delete()
        SupplierPrice.objects.all().delete()
        Product.objects.all().delete()

        self.stdout.write(self.style.SUCCESS("Stock data wiped:"))
        for label, n in counts_before.items():
            self.stdout.write(f"  {label}: {n} deleted")

"""Import every Recipe Report sheet from a multi-recipe workbook.

Usage:
    python manage.py import_recipes_bulk data/recipes_bulk_93.xlsx
    python manage.py import_recipes_bulk data/recipes_bulk_93.xlsx --department Bakery

Each worksheet in the input workbook is treated as its own Recipe Report
(same layout the existing ``import_recipe`` command handles). The
per-recipe parsing is reused unchanged — we just loop over the sheets.

Idempotent on NPD-R code: re-importing the same workbook overwrites
each recipe's lines (same semantics as the single-recipe importer).
Sheets that don't parse are recorded as failures and skipped — one bad
sheet must not abort the whole import. NOT wired into build.sh.
"""
from django.core.management.base import BaseCommand, CommandError

from stock.models import Department, RecipeCycleError
from stock.recipe_import import (
    parse_recipe_workbook_bulk, save_recipes, summarize_parse_bulk,
)


class Command(BaseCommand):
    help = "Import every recipe sheet from a multi-recipe Recipe Report workbook."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the multi-recipe .xlsx")
        parser.add_argument(
            "--department", default="Bakery",
            help="Department to assign recipes to (default: Bakery)")

    def handle(self, *args, **opts):
        dept, _ = Department.objects.get_or_create(name=opts["department"])
        parsed, failures, sheets_processed = parse_recipe_workbook_bulk(opts["path"])

        try:
            stats = save_recipes(parsed, dept)
        except RecipeCycleError as e:
            raise CommandError(f"Refusing to save: {e}")

        summary = summarize_parse_bulk(parsed, failures, sheets_processed)
        self.stdout.write(self.style.SUCCESS(
            f"Bulk-imported recipes into '{dept.name}':"))
        self.stdout.write(
            f"  {sheets_processed} sheet(s) processed, "
            f"{len(failures)} failed")
        self.stdout.write(
            f"  {len(stats['created'])} recipe(s) created, "
            f"{len(stats['updated'])} updated "
            f"({summary['unique_recipe_codes']} unique codes across all sheets)")
        if stats["stub_subrecipes"]:
            self.stdout.write(self.style.WARNING(
                f"  {len(stats['stub_subrecipes'])} sub-recipe stub(s) created"))
        if stats["stub_products"]:
            self.stdout.write(self.style.WARNING(
                f"  {len(stats['stub_products'])} unknown ingredient(s) stubbed "
                "(add supplier prices later)"))
        if failures:
            self.stdout.write(self.style.WARNING("  Sheets that failed to parse:"))
            for title, reason in failures:
                self.stdout.write(f"    {title!r}: {reason}")

"""Import a single Recipe Breakdown Excel export.

Usage:
    python manage.py import_recipe data/recipe_sample.xlsx
    python manage.py import_recipe data/recipe_sample.xlsx --department Bakery

Idempotent (keyed on recipe code). Mirrors the upload screen in the Recipes
section — both go through stock.recipe_import.
"""
from django.core.management.base import BaseCommand, CommandError

from stock.models import Department, RecipeCycleError
from stock.recipe_import import (
    parse_recipe_workbook, save_recipes, RecipeParseError,
)


class Command(BaseCommand):
    help = "Import a Recipe Breakdown (.xlsx) and any nested sub-recipes."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the recipe .xlsx export")
        parser.add_argument(
            "--department", default="Bakery",
            help="Department to assign recipes to (default: Bakery)",
        )

    def handle(self, *args, **opts):
        dept, _ = Department.objects.get_or_create(name=opts["department"])
        try:
            parsed = parse_recipe_workbook(opts["path"])
        except RecipeParseError as e:
            raise CommandError(str(e))

        try:
            stats = save_recipes(parsed, dept)
        except RecipeCycleError as e:
            raise CommandError(f"Refusing to save: {e}")

        main = parsed[0]
        self.stdout.write(self.style.SUCCESS(
            f"Imported recipe {main['code']} - {main['name']} into '{dept.name}':"))
        self.stdout.write(
            f"  {len(stats['created'])} created, {len(stats['updated'])} updated"
            f" ({len(parsed)} recipes in the workbook)")
        if stats["stub_subrecipes"]:
            self.stdout.write(self.style.WARNING(
                f"  {len(stats['stub_subrecipes'])} sub-recipe stub(s) created "
                "(referenced but not sectioned in the workbook):"))
            for s in stats["stub_subrecipes"]:
                self.stdout.write(f"    {s.code}  {s.name}")
        if stats["stub_products"]:
            self.stdout.write(self.style.WARNING(
                f"  {len(stats['stub_products'])} unknown ingredient(s) "
                "created as stub Products — add a supplier price to use them:"))
            for parent, code, name in stats["unknown_ingredients"]:
                self.stdout.write(f"    {code}  {name}  (in {parent})")

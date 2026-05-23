"""Import one historical week's orders across every customer tab.

Usage:
    python manage.py import_historical_orders data/historical/order_sheet_2026_03_30.xlsm
    python manage.py import_historical_orders <path> --force

Designed for the ``data/historical/`` archive: each file is a single
week of orders, and the deploy loops these. The importer is idempotent
on the week as a whole — it refuses to re-import a week whose Orders
already exist (so re-running this on a deploy never disturbs
hand-edits). Meta tabs (Start, Products, Customers, WHOLESALE, …) are
skipped; unknown customer tabs are reported but never abort the run.
"""
from django.core.management.base import BaseCommand, CommandError

from stock.order_import import import_historical_workbook


class Command(BaseCommand):
    help = ("Import a historical week's orders across every customer "
            "tab in the workbook. Idempotent on week — re-running skips "
            "files whose orders already exist.")

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to a single historical .xlsm")
        parser.add_argument(
            "--force", action="store_true",
            help="Re-import even if orders already exist for that week. "
                 "Use sparingly — wipes and rebuilds every customer's "
                 "lines for the week, which clobbers any hand-edits.")

    def handle(self, *args, **opts):
        path = opts["path"]
        try:
            summary = import_historical_workbook(path, force=opts["force"])
        except FileNotFoundError as e:
            raise CommandError(str(e))

        if summary["skipped"]:
            self.stdout.write(self.style.WARNING(
                f"Skipped {path}: {summary.get('reason', 'no reason given')}"))
            return

        wk = summary.get("week_start")
        self.stdout.write(self.style.SUCCESS(
            f"Imported {path} (w/c {wk.isoformat() if wk else '?'}):"))
        self.stdout.write(
            f"  {summary['tabs_imported']} customer tab(s), "
            f"{summary['lines_imported']} line(s), "
            f"{summary['products_matched']} product(s) matched, "
            f"{summary['products_unmatched_count']} unmatched (kept as "
            f"discontinued / no catalogue link)")
        for tab, result in summary["per_tab"].items():
            unmatched = len(result.get("products_unmatched", []))
            extra = ""
            if "customers_imported" in result:
                extra = f", {result['customers_imported']} wholesale customer(s)"
            self.stdout.write(
                f"    {tab}: {result['lines_imported']} line(s), "
                f"{result['products_matched']} matched, "
                f"{unmatched} unmatched{extra}")
        unmatched_names = summary.get("wholesale_customer_unmatched") or []
        if unmatched_names:
            self.stdout.write(self.style.WARNING(
                f"  {len(unmatched_names)} wholesale name(s) with no Customer "
                f"row — add them manually to capture their revenue:"))
            for name in unmatched_names:
                self.stdout.write(f"    {name!r}")
        if summary.get("failures"):
            self.stdout.write(self.style.WARNING(
                f"  {len(summary['failures'])} tab failure(s):"))
            for tab, reason in summary["failures"]:
                self.stdout.write(f"    {tab}: {reason}")

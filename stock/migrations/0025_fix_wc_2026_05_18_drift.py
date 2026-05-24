"""Data migration: fix the £22.05 prod drift on w/c 2026-05-18 (external).

Diagnosed by reconciling prod against a fresh local re-import of the
committed ``data/historical/order_sheet_2026_05_18.xlsm``: prod's data
for that week was last imported from an earlier snapshot, so eight rows
across four wholesale customers + one cafe diverged. The other seven
imported weeks reconcile to the penny — drift is contained.

Eight corrections, matched on NATURAL KEYS
(customer.name, order_date, product_name) because prod and local row
IDs differ:

  3 qty updates  — GARDEN CAFE 2026-05-22, three loose pastries 4 → 6
  4 inserts      — wholesale rows missing on prod (KILVER COURT,
                   NUMBER ONE BRUTON, THE PRESSOIR)
  1 delete       — THE PRESSOIR 2026-05-23 phantom Baguette line
                   (source cell is blank; prod has a stale 4× row)

Both apply and reverse are idempotent; both are safe to re-run, and
both no-op when the underlying state already matches the target.
"""
from datetime import date
from decimal import Decimal

from django.db import migrations


UPDATES = [
    # (customer_name, order_date, product_name, new_qty, old_qty)
    ("GARDEN CAFE", date(2026, 5, 22), "Croissant (Loose)", Decimal("6"), Decimal("4")),
    ("GARDEN CAFE", date(2026, 5, 22), "Pain au Chocolat (Loose)", Decimal("6"), Decimal("4")),
    ("GARDEN CAFE", date(2026, 5, 22), "Sticky Apple & Cinnamon Bun (Loose) - WHOLESALE ONLY", Decimal("6"), Decimal("4")),
]

INSERTS = [
    # (customer_name, order_date, product_name, qty, unit_price)
    ("KILVER COURT",      date(2026, 5, 22), "TN Rosemary Focaccia_1.75KG", Decimal("1"), Decimal("3.75")),
    ("KILVER COURT",      date(2026, 5, 23), "TN Rosemary Focaccia_1.75KG", Decimal("2"), Decimal("3.75")),
    ("NUMBER ONE BRUTON", date(2026, 5, 23), "Sultana Pain Suisse (Loose)", Decimal("2"), Decimal("1.65")),
    ("THE PRESSOIR",      date(2026, 5, 23), "TN Rosemary Focaccia_3.5KG",  Decimal("1"), Decimal("7.50")),
]

DELETES = [
    # (customer_name, order_date, product_name, expected_qty, expected_price)
    ("THE PRESSOIR", date(2026, 5, 23), "Baguette (Sourdough) (Loose)", Decimal("4"), Decimal("1.90")),
]

WC_START = date(2026, 5, 18)
WC_END   = date(2026, 5, 24)
EXPECTED_TOTAL = Decimal("17884.90")


def _get_order(apps, cust_name, order_date):
    Order = apps.get_model("stock", "Order")
    Customer = apps.get_model("stock", "Customer")
    cust = Customer.objects.filter(name=cust_name).first()
    if cust is None:
        return None
    return Order.objects.filter(customer=cust, order_date=order_date).first()


def _external_total_for_week(apps):
    OrderLine = apps.get_model("stock", "OrderLine")
    rows = OrderLine.objects.filter(
        order__order_date__range=(WC_START, WC_END),
        order__customer__is_internal=False,
        qty_ordered__isnull=False,
        unit_price__isnull=False,
    ).values_list("qty_ordered", "unit_price")
    total = Decimal("0")
    for q, p in rows:
        total += q * p
    return total.quantize(Decimal("0.01"))


def apply_corrections(apps, schema_editor):
    OrderLine = apps.get_model("stock", "OrderLine")
    SaleProduct = apps.get_model("stock", "SaleProduct")
    changes = 0

    for cn, dt, pn, new_qty, _old in UPDATES:
        order = _get_order(apps, cn, dt)
        if order is None:
            continue
        for line in OrderLine.objects.filter(order=order, product_name=pn):
            if line.qty_ordered != new_qty:
                line.qty_ordered = new_qty
                line.save()
                changes += 1

    for cn, dt, pn, qty, price in INSERTS:
        order = _get_order(apps, cn, dt)
        if order is None:
            # Prod was probed: all four target orders exist. Anywhere else
            # (test DB, fresh local), the order may legitimately be absent
            # — skip, the corresponding rows we'd insert aren't there to
            # fix either.
            continue
        # Idempotent: a line with this product_name on this order means a
        # prior apply already inserted it (or the source already had it).
        if OrderLine.objects.filter(order=order, product_name=pn).exists():
            continue
        # Match the local import's sale_product link by name when available
        # (prod sale_product PKs differ from local, so look up by name not id).
        sp = SaleProduct.objects.filter(name=pn).first()
        OrderLine.objects.create(
            order=order, sale_product=sp,
            product_name=pn, qty_ordered=qty, unit_price=price,
        )
        changes += 1

    for cn, dt, pn, ex_qty, ex_price in DELETES:
        order = _get_order(apps, cn, dt)
        if order is None:
            continue
        # Match strict (qty + price) so a legitimate later re-entry with
        # different values isn't swept up by accident.
        deleted, _ = OrderLine.objects.filter(
            order=order, product_name=pn,
            qty_ordered=ex_qty, unit_price=ex_price,
        ).delete()
        if deleted:
            changes += 1

    # Safety net: when this migration actually changed something, the
    # external total for w/c 2026-05-18 must land on £17,884.90. Skipped
    # when nothing changed (test DB with no fixtures; re-apply after the
    # first successful run) so we don't fail spuriously on empty DBs.
    if changes:
        total = _external_total_for_week(apps)
        if total != EXPECTED_TOTAL:
            raise RuntimeError(
                f"Post-correction external total = £{total}, "
                f"expected £{EXPECTED_TOTAL}; rolling back."
            )


def reverse_corrections(apps, schema_editor):
    OrderLine = apps.get_model("stock", "OrderLine")
    SaleProduct = apps.get_model("stock", "SaleProduct")

    for cn, dt, pn, _new_qty, old_qty in UPDATES:
        order = _get_order(apps, cn, dt)
        if order is None:
            continue
        for line in OrderLine.objects.filter(order=order, product_name=pn):
            if line.qty_ordered != old_qty:
                line.qty_ordered = old_qty
                line.save()

    for cn, dt, pn, qty, price in INSERTS:
        order = _get_order(apps, cn, dt)
        if order is None:
            continue
        OrderLine.objects.filter(
            order=order, product_name=pn,
            qty_ordered=qty, unit_price=price,
        ).delete()

    for cn, dt, pn, ex_qty, ex_price in DELETES:
        order = _get_order(apps, cn, dt)
        if order is None:
            continue
        if OrderLine.objects.filter(
            order=order, product_name=pn,
            qty_ordered=ex_qty, unit_price=ex_price,
        ).exists():
            continue
        sp = SaleProduct.objects.filter(name=pn).first()
        OrderLine.objects.create(
            order=order, sale_product=sp,
            product_name=pn, qty_ordered=ex_qty, unit_price=ex_price,
        )


class Migration(migrations.Migration):
    dependencies = [("stock", "0024_customer_is_internal")]
    operations = [
        migrations.RunPython(apply_corrections, reverse_corrections),
    ]

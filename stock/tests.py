import datetime
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from .models import Department, Supplier, Product, SupplierPrice, Stocktake, StockLine, Delivery, Batch


class StockLineValueTests(TestCase):
    def test_value_is_count_times_pack_price(self):
        dept = Department.objects.create(name="Test Dept")
        sup = Supplier.objects.create(name="Test Sup")
        product = Product.objects.create(name="Thing", department=dept, unit="ea", minimum=0)
        SupplierPrice.objects.create(
            product=product, supplier=sup,
            pack_weight=Decimal("1"), pack_price=Decimal("11.54"))
        st = Stocktake.objects.create(department=dept, date=datetime.date.today())
        line = StockLine.objects.create(stocktake=st, product=product, current=Decimal("10"))
        self.assertEqual(line.value, Decimal("115.40"))

    def test_value_ignores_pack_weight(self):
        dept = Department.objects.create(name="Dept2")
        sup = Supplier.objects.create(name="Sup2")
        product = Product.objects.create(name="Bulk", department=dept, unit="g", minimum=0)
        SupplierPrice.objects.create(
            product=product, supplier=sup,
            pack_weight=Decimal("1000"), pack_price=Decimal("11.54"))
        st = Stocktake.objects.create(department=dept, date=datetime.date.today())
        line = StockLine.objects.create(stocktake=st, product=product, current=Decimal("10"))
        self.assertEqual(line.value, Decimal("115.40"))


class DeliveryBatchTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        self.sup = Supplier.objects.create(name="Acme Mill")
        self.product = Product.objects.create(name="Flour", department=self.dept, unit="ea", minimum=0)
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)

    def test_delivery_of_8_packs_creates_batch_and_updates_on_hand(self):
        delivery = Delivery.objects.create(department=self.dept, supplier=self.sup,
                                           date=datetime.date.today())
        batch = Batch.objects.create(
            delivery=delivery, product=self.product,
            batch_code="A123", use_by=datetime.date(2026, 12, 31),
            qty_received=Decimal("8"), qty_remaining=Decimal("8"))
        self.assertEqual(batch.qty_remaining, Decimal("8"))
        self.assertEqual(self.product.on_hand_from_batches, Decimal("8"))

    def test_delivery_form_creates_delivery_and_batch(self):
        c = Client(); assert c.login(username="alice", password="pw")
        c.get(f"/switch/{self.dept.pk}/")
        r = c.post("/deliveries/new/", {
            "supplier": str(self.sup.pk),
            "date": datetime.date.today().isoformat(),
            "note": "docket 42",
            "product": [str(self.product.pk)],
            "batch_code": ["A123"],
            "use_by": [""],
            "qty": ["8"],
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Delivery.objects.count(), 1)
        self.assertEqual(Batch.objects.count(), 1)
        b = Batch.objects.get()
        self.assertEqual(b.qty_received, Decimal("8"))
        self.assertEqual(b.qty_remaining, Decimal("8"))
        self.assertEqual(b.batch_code, "A123")
        self.assertEqual(self.product.on_hand_from_batches, Decimal("8"))

    def test_on_hand_sums_across_batches(self):
        delivery = Delivery.objects.create(department=self.dept, supplier=self.sup,
                                           date=datetime.date.today())
        Batch.objects.create(delivery=delivery, product=self.product,
                             qty_received=Decimal("3"), qty_remaining=Decimal("3"))
        Batch.objects.create(delivery=delivery, product=self.product,
                             qty_received=Decimal("5"), qty_remaining=Decimal("5"))
        self.assertEqual(self.product.on_hand_from_batches, Decimal("8"))

import datetime
import re
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, Client
from .models import Department, Supplier, Product, SupplierPrice, Stocktake, StockLine, Delivery, Batch, Adjustment
from .ai_extract import parse_lines_json, auto_match
from .templatetags.pack_format import pack_size


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

    def test_has_supplier_price_false_when_no_matching_price(self):
        delivery = Delivery.objects.create(department=self.dept, supplier=self.sup,
                                           date=datetime.date.today())
        batch = Batch.objects.create(delivery=delivery, product=self.product,
                                     qty_received=Decimal("3"), qty_remaining=Decimal("3"))
        self.assertFalse(batch.has_supplier_price)

    def test_has_supplier_price_true_when_matching_price_exists(self):
        SupplierPrice.objects.create(product=self.product, supplier=self.sup,
                                     pack_weight=Decimal("1"), pack_price=Decimal("10"))
        delivery = Delivery.objects.create(department=self.dept, supplier=self.sup,
                                           date=datetime.date.today())
        batch = Batch.objects.create(delivery=delivery, product=self.product,
                                     qty_received=Decimal("3"), qty_remaining=Decimal("3"))
        self.assertTrue(batch.has_supplier_price)

    def test_form_save_still_succeeds_when_supplier_has_no_price_for_product(self):
        c = Client(); assert c.login(username="alice", password="pw")
        c.get(f"/switch/{self.dept.pk}/")
        r = c.post("/deliveries/new/", {
            "supplier": str(self.sup.pk),
            "date": datetime.date.today().isoformat(),
            "product": [str(self.product.pk)],
            "batch_code": ["X1"],
            "use_by": [""],
            "qty": ["8"],
        })
        self.assertEqual(r.status_code, 302)
        b = Batch.objects.get()
        self.assertEqual(b.qty_remaining, Decimal("8"))
        self.assertFalse(b.has_supplier_price)


class AIExtractTests(TestCase):
    def test_parse_lines_json_plain(self):
        out = parse_lines_json('[{"description": "Flour 25kg", "qty": 4}]')
        self.assertEqual(out, [{"description": "Flour 25kg", "qty": 4.0}])

    def test_parse_lines_json_with_markdown_fence(self):
        out = parse_lines_json('```json\n[{"description":"Sugar","qty":2}]\n```')
        self.assertEqual(out, [{"description": "Sugar", "qty": 2.0}])

    def test_parse_lines_json_handles_garbage(self):
        self.assertEqual(parse_lines_json("not json at all"), [])
        self.assertEqual(parse_lines_json(""), [])
        self.assertEqual(parse_lines_json("{}"), [])
        self.assertEqual(parse_lines_json('[{"description":"","qty":3}]'), [])
        self.assertEqual(parse_lines_json('[{"description":"x","qty":0}]'), [])

    def test_parse_lines_json_extracts_embedded_array(self):
        out = parse_lines_json('Here you go: [{"description":"Eggs","qty":12}] cheers!')
        self.assertEqual(out, [{"description": "Eggs", "qty": 12.0}])


class AutoMatchTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="D")
        self.sup_a = Supplier.objects.create(name="A")
        self.sup_b = Supplier.objects.create(name="B")
        self.flour = Product.objects.create(name="Flour", department=self.dept, unit="ea", minimum=0)
        self.sugar = Product.objects.create(name="Caster Sugar", department=self.dept, unit="ea", minimum=0)
        self.salt = Product.objects.create(name="Salt", department=self.dept, unit="ea", minimum=0)
        SupplierPrice.objects.create(product=self.flour, supplier=self.sup_a,
                                     pack_weight=Decimal("1"), pack_price=Decimal("3"))
        SupplierPrice.objects.create(product=self.sugar, supplier=self.sup_b,
                                     pack_weight=Decimal("1"), pack_price=Decimal("2"))

    def test_matches_by_substring(self):
        p, conf = auto_match("Strong White Flour 25kg", self.sup_a, self.dept)
        self.assertEqual(p, self.flour)
        self.assertTrue(conf)

    def test_prefers_supplier_catalog(self):
        # Both flour and salt are dept products; flour is in sup_a's catalog; if the
        # description mentions both, the priced one wins.
        p, _ = auto_match("Flour and Salt mix", self.sup_a, self.dept)
        self.assertEqual(p, self.flour)

    def test_falls_back_to_other_products(self):
        # sugar isn't in sup_a's catalog but should still be matched if it's the only fit
        p, conf = auto_match("Caster Sugar 1kg", self.sup_a, self.dept)
        self.assertEqual(p, self.sugar)
        self.assertTrue(conf)

    def test_no_match_returns_none(self):
        p, conf = auto_match("Mystery Item", self.sup_a, self.dept)
        self.assertIsNone(p)
        self.assertFalse(conf)


class DeliveryScanFlowTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        self.sup = Supplier.objects.create(name="Acme Mill")
        self.flour = Product.objects.create(name="Flour", department=self.dept, unit="ea", minimum=0)
        self.sugar = Product.objects.create(name="Sugar", department=self.dept, unit="ea", minimum=0)
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        SupplierPrice.objects.create(product=self.flour, supplier=self.sup,
                                     pack_weight=Decimal("1"), pack_price=Decimal("3"))
        self.client = Client()
        assert self.client.login(username="alice", password="pw")
        self.client.get(f"/switch/{self.dept.pk}/")

    @patch("stock.views.extract_lines")
    def test_scan_prefills_form_with_matched_and_unmatched_lines(self, mock_extract):
        mock_extract.return_value = [
            {"description": "Strong White Flour 25kg", "qty": 4.0},
            {"description": "Caster Sugar 1kg", "qty": 2.0},
            {"description": "Mystery Item XYZ", "qty": 1.0},
        ]
        fake_file = SimpleUploadedFile("test.jpg", b"\xff\xd8fake-jpg-bytes",
                                       content_type="image/jpeg")
        r = self.client.post("/deliveries/scan/", {
            "supplier": str(self.sup.pk),
            "file": fake_file,
        })
        # extract_lines was called with the file bytes and mime type
        mock_extract.assert_called_once()
        args, _ = mock_extract.call_args
        self.assertEqual(args[1], "image/jpeg")
        self.assertIn(b"fake-jpg-bytes", args[0])

        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Supplier preselected
        self.assertIn(f'<option value="{self.sup.pk}" selected>Acme Mill</option>', body)
        # Flour line: data-prefill = flour.pk, qty=4.0
        self.assertIn(f'data-prefill="{self.flour.pk}"', body)
        self.assertIn('value="4.0"', body)
        # Sugar line: data-prefill = sugar.pk, qty=2.0
        self.assertIn(f'data-prefill="{self.sugar.pk}"', body)
        self.assertIn('value="2.0"', body)
        # Unmatched line: raw description shown, no data-prefill for that row's qty
        self.assertIn("Mystery Item XYZ", body)
        self.assertIn('value="1.0"', body)
        # form posts to delivery_new (the existing save endpoint)
        self.assertIn('action="/deliveries/new/"', body)

    @patch("stock.views.extract_lines")
    def test_zero_lines_falls_back_to_manual_form_with_message(self, mock_extract):
        mock_extract.return_value = []
        f = SimpleUploadedFile("x.png", b"png-bytes", content_type="image/png")
        r = self.client.post("/deliveries/scan/", {"supplier": str(self.sup.pk), "file": f})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("No line items came back", body)
        # Still the delivery form; supplier preselected
        self.assertIn(f'<option value="{self.sup.pk}" selected>Acme Mill</option>', body)

    @patch("stock.views.extract_lines")
    def test_api_failure_falls_back_to_manual_form(self, mock_extract):
        from .ai_extract import ExtractError
        mock_extract.side_effect = ExtractError("could not reach scanning service")
        f = SimpleUploadedFile("x.png", b"png-bytes", content_type="image/png")
        r = self.client.post("/deliveries/scan/", {"supplier": str(self.sup.pk), "file": f})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("could not reach scanning service", body)
        self.assertIn(f'<option value="{self.sup.pk}" selected>Acme Mill</option>', body)

    def test_no_supplier_redirects_back_to_scan(self):
        f = SimpleUploadedFile("x.png", b"png-bytes", content_type="image/png")
        r = self.client.post("/deliveries/scan/", {"supplier": "", "file": f})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/deliveries/scan/")

    def test_get_renders_upload_form(self):
        r = self.client.get("/deliveries/scan/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Scan delivery note", body)
        self.assertIn('name="file"', body)


class UsageHistoryTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        self.sup = Supplier.objects.create(name="Mill")
        self.flour = Product.objects.create(
            name="Flour", department=self.dept, unit="ea", minimum=0)

    def _count(self, date, current):
        st = Stocktake.objects.create(department=self.dept, date=date)
        StockLine.objects.create(
            stocktake=st, product=self.flour,
            current=Decimal(current), carried_over=False)
        return st

    def _delivery(self, date, qty):
        d = Delivery.objects.create(department=self.dept, supplier=self.sup, date=date)
        return Batch.objects.create(
            delivery=d, product=self.flour,
            qty_received=Decimal(qty), qty_remaining=Decimal(qty))

    def test_delivery_between_counts_is_included_in_usage(self):
        # 10 on Jan 1, delivery of 8 on Jan 5, 12 on Jan 8 → usage 10 + 8 - 12 = 6
        self._count(datetime.date(2026, 1, 1), 10)
        self._delivery(datetime.date(2026, 1, 5), 8)
        self._count(datetime.date(2026, 1, 8), 12)
        rows = self.flour.usage_history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["delivered"], Decimal("8"))
        self.assertEqual(rows[0]["usage"], Decimal("6"))
        self.assertFalse(rows[0]["clamped"])
        self.assertEqual(rows[0]["days"], 7)

    def test_delivery_on_previous_count_date_is_excluded(self):
        # "Strictly between" - delivery on the same day as the previous count
        # is part of that count's snapshot and must not be double-counted.
        self._count(datetime.date(2026, 1, 1), 10)
        self._delivery(datetime.date(2026, 1, 1), 5)
        self._count(datetime.date(2026, 1, 8), 8)
        rows = self.flour.usage_history()
        self.assertEqual(rows[0]["delivered"], Decimal("0"))
        self.assertEqual(rows[0]["usage"], Decimal("2"))

    def test_delivery_on_current_count_date_is_included(self):
        # "On/before this stocktake's date" - delivery on the day we counted
        # is part of the inflow for that period.
        self._count(datetime.date(2026, 1, 1), 10)
        self._delivery(datetime.date(2026, 1, 8), 5)
        self._count(datetime.date(2026, 1, 8), 12)
        rows = self.flour.usage_history()
        self.assertEqual(rows[0]["delivered"], Decimal("5"))
        self.assertEqual(rows[0]["usage"], Decimal("3"))

    def test_first_ever_count_has_no_usage_data(self):
        self._count(datetime.date(2026, 1, 8), 10)
        self.assertEqual(self.flour.usage_history(), [])
        self.assertIsNone(self.flour.average_weekly_usage())
        self.assertIsNone(self.flour.days_of_cover(on_hand=Decimal("10")))

    def test_negative_usage_clamps_to_zero(self):
        # 5 on hand, no delivery, then 12 on hand - impossible without an
        # unlogged delivery or miscount. Clamp at 0 and flag it.
        self._count(datetime.date(2026, 1, 1), 5)
        self._count(datetime.date(2026, 1, 8), 12)
        rows = self.flour.usage_history()
        self.assertEqual(rows[0]["usage"], Decimal("0"))
        self.assertTrue(rows[0]["clamped"])

    def test_average_over_multiple_counts(self):
        self._count(datetime.date(2026, 1, 1), 20)
        self._count(datetime.date(2026, 1, 8), 15)   # usage 5
        self._count(datetime.date(2026, 1, 15), 5)   # usage 10
        self.assertEqual(self.flour.average_weekly_usage(n=4), Decimal("7.50"))

    def test_days_of_cover_from_average(self):
        # avg 5 packs/week, 10 on hand → 10 / 5 * 7 = 14 days
        self._count(datetime.date(2026, 1, 1), 15)
        self._count(datetime.date(2026, 1, 8), 10)
        self.assertEqual(self.flour.days_of_cover(on_hand=Decimal("10")), 14)

    def test_carried_over_lines_are_not_data_points(self):
        # A carried-over line is just a copy of the prior count - it must not
        # appear in usage history (would produce a spurious 0-usage row).
        self._count(datetime.date(2026, 1, 1), 10)
        st = Stocktake.objects.create(department=self.dept, date=datetime.date(2026, 1, 8))
        StockLine.objects.create(stocktake=st, product=self.flour,
                                 current=Decimal("10"), carried_over=True)
        self.assertEqual(self.flour.usage_history(), [])


class AdjustmentTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        self.sup = Supplier.objects.create(name="Mill")
        self.flour = Product.objects.create(
            name="Flour", code="FLR1", department=self.dept, unit="g", minimum=0)
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        self.client = Client()
        assert self.client.login(username="alice", password="pw")
        self.client.get(f"/switch/{self.dept.pk}/")

    def _batch(self, qty):
        d = Delivery.objects.create(department=self.dept, supplier=self.sup,
                                    date=datetime.date(2026, 5, 1))
        return Batch.objects.create(delivery=d, product=self.flour,
                                    qty_received=Decimal(qty), qty_remaining=Decimal(qty))

    def test_waste_reduces_on_hand(self):
        self._batch(10)
        self.assertEqual(self.flour.on_hand_from_batches, Decimal("10"))
        Adjustment.objects.create(
            department=self.dept, product=self.flour,
            quantity=Decimal("3"), reason="waste", user=self.user,
            date=datetime.date(2026, 5, 10))
        self.assertEqual(self.flour.on_hand_from_batches, Decimal("10"))  # batches unchanged
        self.assertEqual(self.flour.on_hand, Decimal("7"))                # adjusted figure
        self.assertEqual(self.flour.adjustments_net, Decimal("-3"))

    def test_found_increases_on_hand(self):
        self._batch(5)
        Adjustment.objects.create(
            department=self.dept, product=self.flour,
            quantity=Decimal("2"), reason="found", user=self.user,
            date=datetime.date(2026, 5, 10))
        self.assertEqual(self.flour.on_hand, Decimal("7"))
        self.assertEqual(self.flour.adjustments_net, Decimal("2"))

    def test_waste_in_period_is_excluded_from_usage(self):
        # Without waste: P=20, D=0, C=14 → usage 6
        # With waste of 4 in the period: P=20, D=0, C=14, W=4 → real usage 2
        st1 = Stocktake.objects.create(department=self.dept,
                                       date=datetime.date(2026, 5, 1))
        StockLine.objects.create(stocktake=st1, product=self.flour,
                                 current=Decimal("20"), carried_over=False)
        Adjustment.objects.create(
            department=self.dept, product=self.flour,
            quantity=Decimal("4"), reason="waste", user=self.user,
            date=datetime.date(2026, 5, 5))
        st2 = Stocktake.objects.create(department=self.dept,
                                       date=datetime.date(2026, 5, 8))
        StockLine.objects.create(stocktake=st2, product=self.flour,
                                 current=Decimal("14"), carried_over=False)

        rows = self.flour.usage_history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["adjustments"], Decimal("-4"))
        self.assertEqual(rows[0]["usage"], Decimal("2"))
        self.assertFalse(rows[0]["clamped"])

    def test_found_in_period_adds_to_inflows_for_usage(self):
        # P=10, D=0, F=5 (found), C=12 → real usage 3
        st1 = Stocktake.objects.create(department=self.dept,
                                       date=datetime.date(2026, 5, 1))
        StockLine.objects.create(stocktake=st1, product=self.flour,
                                 current=Decimal("10"), carried_over=False)
        Adjustment.objects.create(
            department=self.dept, product=self.flour,
            quantity=Decimal("5"), reason="found", user=self.user,
            date=datetime.date(2026, 5, 5))
        st2 = Stocktake.objects.create(department=self.dept,
                                       date=datetime.date(2026, 5, 8))
        StockLine.objects.create(stocktake=st2, product=self.flour,
                                 current=Decimal("12"), carried_over=False)
        rows = self.flour.usage_history()
        self.assertEqual(rows[0]["adjustments"], Decimal("5"))
        self.assertEqual(rows[0]["usage"], Decimal("3"))

    def test_adjustment_outside_period_does_not_affect_usage(self):
        # Waste on the date of the previous count is "strictly between"-excluded
        st1 = Stocktake.objects.create(department=self.dept,
                                       date=datetime.date(2026, 5, 1))
        StockLine.objects.create(stocktake=st1, product=self.flour,
                                 current=Decimal("10"), carried_over=False)
        Adjustment.objects.create(  # same day as prev count
            department=self.dept, product=self.flour,
            quantity=Decimal("3"), reason="waste", user=self.user,
            date=datetime.date(2026, 5, 1))
        st2 = Stocktake.objects.create(department=self.dept,
                                       date=datetime.date(2026, 5, 8))
        StockLine.objects.create(stocktake=st2, product=self.flour,
                                 current=Decimal("7"), carried_over=False)
        rows = self.flour.usage_history()
        self.assertEqual(rows[0]["adjustments"], Decimal("0"))
        self.assertEqual(rows[0]["usage"], Decimal("3"))

    def test_post_creates_adjustment_and_appears_in_log(self):
        r = self.client.post("/adjustments/", {
            "product": str(self.flour.pk),
            "quantity": "2.5",
            "reason": "waste",
            "note": "dropped bag",
        })
        self.assertEqual(r.status_code, 302)
        a = Adjustment.objects.get()
        self.assertEqual(a.product, self.flour)
        self.assertEqual(a.department, self.dept)
        self.assertEqual(a.quantity, Decimal("2.5"))
        self.assertEqual(a.reason, "waste")
        self.assertEqual(a.user, self.user)
        self.assertEqual(a.note, "dropped bag")

        r = self.client.get("/adjustments/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Flour", body)
        self.assertIn("dropped bag", body)
        # Waste shows with a minus sign in the qty column
        self.assertIn("−3", body)  # 2.5 rounded to 3 by floatformat:0 with leading minus

    def test_post_rejects_bad_payload(self):
        for bad in (
            {"product": "", "quantity": "1", "reason": "waste"},
            {"product": str(self.flour.pk), "quantity": "0", "reason": "waste"},
            {"product": str(self.flour.pk), "quantity": "-3", "reason": "waste"},
            {"product": str(self.flour.pk), "quantity": "1", "reason": "bogus"},
        ):
            r = self.client.post("/adjustments/", bad)
            self.assertEqual(r.status_code, 302)
        self.assertFalse(Adjustment.objects.exists())

    def test_adjustment_page_requires_login(self):
        c = Client()
        r = c.get("/adjustments/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r.headers["Location"])

    def test_adjustment_log_is_department_scoped(self):
        # Adjustments in another department must not appear here
        other = Department.objects.create(name="Butchery")
        other_product = Product.objects.create(
            name="Beef", department=other, unit="g", minimum=0)
        Adjustment.objects.create(
            department=other, product=other_product,
            quantity=Decimal("3"), reason="waste",
            date=datetime.date(2026, 5, 5))
        r = self.client.get("/adjustments/")
        self.assertNotIn("Beef", r.content.decode())


class ReorderTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        self.sup = Supplier.objects.create(name="Acme Mill")
        # Flour: minimum 10, on-hand 2 -> suggested order 8.
        self.flour = Product.objects.create(
            name="Flour", code="FLR1", department=self.dept,
            unit="g", minimum=Decimal("10"))
        SupplierPrice.objects.create(
            product=self.flour, supplier=self.sup,
            pack_weight=Decimal("25000"), pack_price=Decimal("30.00"))
        st = Stocktake.objects.create(department=self.dept,
                                      date=datetime.date(2026, 5, 22))
        StockLine.objects.create(stocktake=st, product=self.flour,
                                 current=Decimal("2"), carried_over=False)
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        self.client = Client()
        assert self.client.login(username="alice", password="pw")
        self.client.get(f"/switch/{self.dept.pk}/")

    def test_reorder_page_renders_editable_qty_input(self):
        r = self.client.get("/reorder/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Editable input with suggested value 8 = 10 - 2
        self.assertIn(f'name="qty_{self.flour.pk}"', body)
        self.assertIn('value="8"', body)
        # Pack price exposed for live JS recomputation
        self.assertIn('data-pack-price="30.00"', body)
        # Form posts to reorder_csv
        self.assertIn('action="/reorder/csv/"', body)
        # Single combined table with supplier sub-header row
        self.assertEqual(body.count('id="reorder-tbl"'), 1)
        self.assertIn('class="sup-row"', body)
        self.assertIn("Acme Mill", body)

    def test_reorder_csv_get_uses_suggested_qty_and_new_columns(self):
        r = self.client.get("/reorder/csv/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv")
        body = r.content.decode()
        # New column order
        self.assertEqual(body.splitlines()[0],
                         "Supplier,Ingredient,Order qty,Pack size,Pack price,Est. cost")
        # Suggested qty 8 @ £30 = £240; pack_size formatted by pack_format ("25 kg")
        self.assertIn("Acme Mill,Flour,8.00,25 kg,30.00,240.00", body)

    def test_reorder_csv_post_uses_overridden_qty(self):
        r = self.client.post("/reorder/csv/", {
            f"qty_{self.flour.pk}": "12",
        })
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Override 12 @ £30 = £360
        self.assertIn("Acme Mill,Flour,12,25 kg,30.00,360.00", body)

    def test_reorder_csv_post_falls_back_to_suggested_when_override_blank(self):
        r = self.client.post("/reorder/csv/", {f"qty_{self.flour.pk}": ""})
        body = r.content.decode()
        self.assertIn("Acme Mill,Flour,8.00,25 kg,30.00,240.00", body)


class DeliveryDetailTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        self.sup = Supplier.objects.create(name="Acme Mill")
        self.flour = Product.objects.create(
            name="Flour", code="FLR1", department=self.dept,
            unit="g", minimum=0)
        self.sugar = Product.objects.create(
            name="Sugar", code="SUG1", department=self.dept,
            unit="g", minimum=0)
        SupplierPrice.objects.create(
            product=self.flour, supplier=self.sup,
            pack_weight=Decimal("25000"), pack_price=Decimal("30"))
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        self.client = Client()
        assert self.client.login(username="alice", password="pw")
        self.client.get(f"/switch/{self.dept.pk}/")

    def test_delivery_detail_renders_with_lines(self):
        delivery = Delivery.objects.create(
            department=self.dept, supplier=self.sup,
            date=datetime.date(2026, 5, 22), note="docket 99")
        Batch.objects.create(
            delivery=delivery, product=self.flour, batch_code="A123",
            use_by=datetime.date(2026, 12, 31),
            qty_received=Decimal("8"), qty_remaining=Decimal("8"))
        Batch.objects.create(
            delivery=delivery, product=self.sugar, batch_code="B7",
            qty_received=Decimal("4"), qty_remaining=Decimal("4"))

        r = self.client.get(f"/deliveries/{delivery.pk}/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()

        # Header bits
        self.assertIn("Acme Mill", body)
        self.assertIn("22 May 2026", body)
        self.assertIn("docket 99", body)

        # Header stats: 2 lines, 12 packs in
        self.assertRegex(body, r"Lines</div><div class=\"v\">2<")
        self.assertRegex(body, r"Packs in</div><div class=\"v\">12<")

        # Both batches present with qty and batch code
        self.assertIn("Flour", body)
        self.assertIn("FLR1", body)
        self.assertIn("A123", body)
        self.assertIn("Sugar", body)
        self.assertIn("B7", body)
        self.assertIn("31 Dec 2026", body)

        # Ingredient links through to product detail
        self.assertIn(f'href="/products/{self.flour.pk}/"', body)
        self.assertIn(f'href="/products/{self.sugar.pk}/"', body)

        # Back link
        self.assertIn('href="/deliveries/"', body)

        # has_supplier_price flag: flour has a price, sugar does not
        # The "no price" tag should appear once (sugar row).
        self.assertEqual(body.count("no price"), 1)

    def test_delivery_detail_blocked_for_other_department(self):
        other = Department.objects.create(name="Butchery")
        delivery = Delivery.objects.create(
            department=other, supplier=self.sup, date=datetime.date(2026, 5, 22))
        r = self.client.get(f"/deliveries/{delivery.pk}/")
        self.assertEqual(r.status_code, 403)

    def test_delivery_detail_requires_login(self):
        delivery = Delivery.objects.create(
            department=self.dept, supplier=self.sup, date=datetime.date(2026, 5, 22))
        c = Client()
        r = c.get(f"/deliveries/{delivery.pk}/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r.headers["Location"])

    def test_deliveries_list_rows_link_to_detail(self):
        delivery = Delivery.objects.create(
            department=self.dept, supplier=self.sup, date=datetime.date(2026, 5, 22))
        r = self.client.get("/deliveries/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'href="/deliveries/{delivery.pk}/"', r.content.decode())

    def test_delivery_with_no_batches_still_renders(self):
        delivery = Delivery.objects.create(
            department=self.dept, supplier=self.sup, date=datetime.date(2026, 5, 22))
        r = self.client.get(f"/deliveries/{delivery.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("No batches on this delivery.", r.content.decode())


class StocktakeCSVTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        self.sup = Supplier.objects.create(name="Mill")
        self.flour = Product.objects.create(
            name="Flour", code="FLR1", department=self.dept,
            unit="g", minimum=Decimal("5"))
        SupplierPrice.objects.create(
            product=self.flour, supplier=self.sup,
            pack_weight=Decimal("25000"), pack_price=Decimal("30.00"))
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        self.client = Client()
        assert self.client.login(username="alice", password="pw")
        self.client.get(f"/switch/{self.dept.pk}/")

    def test_csv_includes_counted_line_with_value(self):
        st = Stocktake.objects.create(department=self.dept,
                                      date=datetime.date(2026, 1, 15))
        StockLine.objects.create(stocktake=st, product=self.flour,
                                 current=Decimal("3"), carried_over=False)
        r = self.client.get(f"/stocktakes/{st.pk}/csv/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv")
        self.assertIn("stocktake-bakery-2026-01-15.csv", r["Content-Disposition"])
        body = r.content.decode()
        lines = body.splitlines()
        self.assertEqual(lines[0], "Ingredient,Code,Minimum,Count,Needed,Value")
        # value = 3 packs * £30.00 = £90.00; needed = 5 - 3 = 2
        self.assertIn("Flour,FLR1,5.00,3.00,2.00,90.00", body)

    def test_csv_renders_uncounted_line_with_blank_count(self):
        st = Stocktake.objects.create(department=self.dept,
                                      date=datetime.date(2026, 2, 1))
        StockLine.objects.create(stocktake=st, product=self.flour, current=None)
        r = self.client.get(f"/stocktakes/{st.pk}/csv/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Uncounted: Count, Needed, Value all blank
        self.assertIn("Flour,FLR1,5.00,,,", body)

    def test_csv_blocked_for_other_department(self):
        other = Department.objects.create(name="Butchery")
        st = Stocktake.objects.create(department=other,
                                      date=datetime.date(2026, 1, 15))
        r = self.client.get(f"/stocktakes/{st.pk}/csv/")
        self.assertEqual(r.status_code, 403)

    def test_csv_requires_login(self):
        c = Client()
        st = Stocktake.objects.create(department=self.dept,
                                      date=datetime.date(2026, 1, 15))
        r = c.get(f"/stocktakes/{st.pk}/csv/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r.headers["Location"])

    def test_total_value_shown_on_count_page_and_csv(self):
        # Two ingredients, two counts. Total = 3*30 + 4*5 = 90 + 20 = 110.
        sugar = Product.objects.create(
            name="Sugar", code="SUG1", department=self.dept,
            unit="g", minimum=Decimal("2"))
        SupplierPrice.objects.create(
            product=sugar, supplier=self.sup,
            pack_weight=Decimal("1000"), pack_price=Decimal("5.00"))
        st = Stocktake.objects.create(department=self.dept,
                                      date=datetime.date(2026, 3, 1))
        StockLine.objects.create(stocktake=st, product=self.flour,
                                 current=Decimal("3"), carried_over=False)
        StockLine.objects.create(stocktake=st, product=sugar,
                                 current=Decimal("4"), carried_over=False)

        # Page shows the total
        r = self.client.get(f"/stocktakes/{st.pk}/count/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Total stock value", body)
        self.assertIn("£110.00", body)

        # CSV has per-line rows AND a TOTAL row
        r = self.client.get(f"/stocktakes/{st.pk}/csv/")
        body = r.content.decode()
        self.assertIn("Flour,FLR1,5.00,3.00,2.00,90.00", body)
        self.assertIn("Sugar,SUG1,2.00,4.00,0,20.00", body)
        # TOTAL row last, with the summed value
        lines = body.strip().splitlines()
        self.assertEqual(lines[-1], "TOTAL,,,,,110.00")

    def test_total_value_skips_uncounted_lines(self):
        # One counted, one blank — total reflects only the counted one.
        sugar = Product.objects.create(
            name="Sugar", code="SUG1", department=self.dept,
            unit="g", minimum=0)
        SupplierPrice.objects.create(
            product=sugar, supplier=self.sup,
            pack_weight=Decimal("1000"), pack_price=Decimal("5.00"))
        st = Stocktake.objects.create(department=self.dept,
                                      date=datetime.date(2026, 3, 8))
        StockLine.objects.create(stocktake=st, product=self.flour,
                                 current=Decimal("3"), carried_over=False)
        StockLine.objects.create(stocktake=st, product=sugar, current=None)

        r = self.client.get(f"/stocktakes/{st.pk}/count/")
        self.assertIn("£90.00", r.content.decode())
        r = self.client.get(f"/stocktakes/{st.pk}/csv/")
        self.assertIn("TOTAL,,,,,90.00", r.content.decode())

    def test_count_page_links_to_csv(self):
        st = Stocktake.objects.create(department=self.dept,
                                      date=datetime.date(2026, 1, 15))
        r = self.client.get(f"/stocktakes/{st.pk}/count/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'/stocktakes/{st.pk}/csv/', r.content.decode())


class PackUnitConversionTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        self.client = Client()
        assert self.client.login(username="alice", password="pw")
        self.client.get(f"/switch/{self.dept.pk}/")

    def test_add_ingredient_in_kg_stores_grams(self):
        r = self.client.post("/products/", {
            "name": "Flour", "code": "FLR1",
            "quantity": "23", "unit": "kg",
            "supplier": "Mill", "cost": "30",
            "minimum": "5",
        })
        self.assertEqual(r.status_code, 302)
        p = Product.objects.get(code="FLR1")
        self.assertEqual(p.unit, "g")
        sp = SupplierPrice.objects.get(product=p)
        self.assertEqual(sp.pack_weight, Decimal("23000"))

    def test_add_ingredient_in_litres_stores_millilitres(self):
        r = self.client.post("/products/", {
            "name": "Oil", "code": "OIL1",
            "quantity": "2", "unit": "L",
            "supplier": "Mill", "cost": "10",
            "minimum": "1",
        })
        self.assertEqual(r.status_code, 302)
        p = Product.objects.get(code="OIL1")
        self.assertEqual(p.unit, "ml")
        sp = SupplierPrice.objects.get(product=p)
        self.assertEqual(sp.pack_weight, Decimal("2000"))

    def test_add_ingredient_in_grams_unchanged(self):
        r = self.client.post("/products/", {
            "name": "Salt", "code": "SLT1",
            "quantity": "500", "unit": "g",
            "supplier": "Mill", "cost": "1.50",
        })
        self.assertEqual(r.status_code, 302)
        p = Product.objects.get(code="SLT1")
        self.assertEqual(p.unit, "g")
        sp = SupplierPrice.objects.get(product=p)
        self.assertEqual(sp.pack_weight, Decimal("500"))

    def test_add_ingredient_in_kg_without_supplier_price_still_normalises_unit(self):
        # No supplier/cost - just creating the ingredient. The unit picker
        # should still produce a "g"-unit product.
        r = self.client.post("/products/", {"name": "Sugar", "code": "SUG1", "unit": "kg"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Product.objects.get(code="SUG1").unit, "g")

    def test_supplier_price_entry_in_kg_stores_grams(self):
        # Existing g-unit product; add a supplier price in kg.
        product = Product.objects.create(
            name="Flour", department=self.dept, unit="g", minimum=0)
        r = self.client.post(f"/products/{product.pk}/", {
            "supplier": "Mill",
            "pack_weight": "23",
            "pack_unit": "kg",
            "pack_price": "30",
        })
        self.assertEqual(r.status_code, 302)
        sp = SupplierPrice.objects.get(product=product)
        self.assertEqual(sp.pack_weight, Decimal("23000"))

    def test_supplier_price_entry_in_litres_stores_millilitres(self):
        product = Product.objects.create(
            name="Oil", department=self.dept, unit="ml", minimum=0)
        r = self.client.post(f"/products/{product.pk}/", {
            "supplier": "Mill",
            "pack_weight": "2",
            "pack_unit": "L",
            "pack_price": "10",
        })
        self.assertEqual(r.status_code, 302)
        sp = SupplierPrice.objects.get(product=product)
        self.assertEqual(sp.pack_weight, Decimal("2000"))

    def test_re_adding_same_code_with_kg_updates_product_unit_and_pack(self):
        # First add as grams
        self.client.post("/products/", {
            "name": "Flour", "code": "FLR9",
            "quantity": "500", "unit": "g",
            "supplier": "Mill", "cost": "1",
        })
        # Re-add same code with kg - product is updated in place; the price
        # save creates a new dated history row instead of overwriting.
        self.client.post("/products/", {
            "name": "Flour", "code": "FLR9",
            "quantity": "25", "unit": "kg",
            "supplier": "Mill", "cost": "30",
        })
        p = Product.objects.get(code="FLR9")
        self.assertEqual(p.unit, "g")
        prices = SupplierPrice.objects.filter(product=p, supplier__name="Mill")
        self.assertEqual(prices.count(), 2)
        latest = prices.order_by("-effective_date", "-id").first()
        self.assertEqual(latest.pack_weight, Decimal("25000"))
        # old row is preserved as history
        self.assertTrue(prices.filter(pack_weight=Decimal("500")).exists())


class PriceHistoryTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        self.sup = Supplier.objects.create(name="Mill")
        self.other_sup = Supplier.objects.create(name="Acme")
        self.flour = Product.objects.create(
            name="Flour", code="FLR1", department=self.dept,
            unit="g", minimum=Decimal("5"))
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        self.client = Client()
        assert self.client.login(username="alice", password="pw")
        self.client.get(f"/switch/{self.dept.pk}/")

    def _price(self, supplier, pack_price, pack_weight=Decimal("25000"), date=None):
        return SupplierPrice.objects.create(
            product=self.flour, supplier=supplier,
            pack_weight=pack_weight, pack_price=pack_price,
            effective_date=date or datetime.date.today())

    def test_saving_a_second_price_creates_a_new_record(self):
        # Old then new price for the same supplier should leave two rows.
        self._price(self.sup, Decimal("25.00"), date=datetime.date(2026, 1, 1))
        r = self.client.post(f"/products/{self.flour.pk}/", {
            "supplier": "Mill", "pack_weight": "25", "pack_unit": "kg",
            "pack_price": "30.00",
        })
        self.assertEqual(r.status_code, 302)
        prices = SupplierPrice.objects.filter(product=self.flour, supplier=self.sup)
        self.assertEqual(prices.count(), 2)
        # Both prices preserved
        self.assertTrue(prices.filter(pack_price=Decimal("25.00")).exists())
        self.assertTrue(prices.filter(pack_price=Decimal("30.00")).exists())

    def test_latest_price_is_used_by_cheapest_value_and_reorder(self):
        # Mill has an old £25 price; today saves £30. Acme is at £28 today.
        # Today's latest for Mill (£30) loses to Acme's £28 — even though
        # the old £25 row exists in history.
        self._price(self.sup, Decimal("25.00"),
                    pack_weight=Decimal("25000"),
                    date=datetime.date(2026, 1, 1))
        self._price(self.sup, Decimal("30.00"),
                    pack_weight=Decimal("25000"),
                    date=datetime.date(2026, 5, 22))
        self._price(self.other_sup, Decimal("28.00"),
                    pack_weight=Decimal("25000"),
                    date=datetime.date(2026, 5, 22))

        cheapest = self.flour.cheapest_price
        self.assertEqual(cheapest.supplier, self.other_sup)
        self.assertEqual(cheapest.pack_price, Decimal("28.00"))

        # StockLine.value uses cheapest_price.pack_price -> latest cheapest
        st = Stocktake.objects.create(department=self.dept,
                                      date=datetime.date(2026, 5, 22))
        line = StockLine.objects.create(stocktake=st, product=self.flour,
                                        current=Decimal("3"), carried_over=False)
        self.assertEqual(line.value, Decimal("84.00"))  # 3 * £28

        # Reorder est cost also uses latest cheapest
        r = self.client.get("/reorder/")
        body = r.content.decode()
        self.assertIn("Acme", body)
        # minimum 5, on-hand 3 -> order 2 packs @ £28 = £56
        self.assertIn("£56.00", body)

    def test_old_price_is_retained_and_shown_in_history(self):
        self._price(self.sup, Decimal("25.00"), date=datetime.date(2026, 1, 1))
        self._price(self.sup, Decimal("30.00"), date=datetime.date(2026, 5, 22))
        r = self.client.get(f"/products/{self.flour.pk}/")
        body = r.content.decode()
        self.assertIn("Price history", body)
        # both prices appear in the history
        self.assertIn("£25.00", body)
        self.assertIn("£30.00", body)
        # current is tagged on the newest row
        self.assertIn("current", body)
        # old date present
        self.assertIn("01 Jan 2026", body)

    def test_more_than_10_percent_jump_is_flagged(self):
        self._price(self.sup, Decimal("20.00"), date=datetime.date(2026, 1, 1))
        self._price(self.sup, Decimal("25.00"), date=datetime.date(2026, 5, 22))
        history = self.flour.price_history()
        latest_entry = history[0]["entries"][0]
        # +25% jump
        self.assertEqual(latest_entry["delta_pct"], Decimal("25.0"))
        self.assertTrue(latest_entry["notable"])
        # Template renders the notable tag
        r = self.client.get(f"/products/{self.flour.pk}/")
        body = r.content.decode()
        self.assertIn("+25.0%", body)

    def test_small_change_is_not_flagged(self):
        self._price(self.sup, Decimal("20.00"), date=datetime.date(2026, 1, 1))
        self._price(self.sup, Decimal("21.00"), date=datetime.date(2026, 5, 22))
        latest = self.flour.price_history()[0]["entries"][0]
        # +5%
        self.assertEqual(latest["delta_pct"], Decimal("5.0"))
        self.assertFalse(latest["notable"])

    def test_latest_prices_returns_one_per_supplier(self):
        self._price(self.sup, Decimal("25.00"), date=datetime.date(2026, 1, 1))
        self._price(self.sup, Decimal("30.00"), date=datetime.date(2026, 5, 22))
        self._price(self.other_sup, Decimal("28.00"), date=datetime.date(2026, 5, 22))
        latest = self.flour.latest_prices()
        self.assertEqual(len(latest), 2)
        by_sup = {sp.supplier_id: sp for sp in latest}
        self.assertEqual(by_sup[self.sup.pk].pack_price, Decimal("30.00"))
        self.assertEqual(by_sup[self.other_sup.pk].pack_price, Decimal("28.00"))

    def test_first_entry_has_no_delta(self):
        self._price(self.sup, Decimal("25.00"), date=datetime.date(2026, 5, 22))
        entries = self.flour.price_history()[0]["entries"]
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0]["delta_pct"])

    def test_deliveries_supplier_filter_dedupes_history(self):
        # Two prices for (flour, sup) shouldn't make the delivery form think
        # the supplier stocks the ingredient twice.
        self._price(self.sup, Decimal("25.00"), date=datetime.date(2026, 1, 1))
        self._price(self.sup, Decimal("30.00"), date=datetime.date(2026, 5, 22))
        r = self.client.get("/deliveries/new/")
        # Page renders; supplier_ids list on the product is deduped
        p = (Product.objects.filter(pk=self.flour.pk)
             .prefetch_related("prices").first())
        ids = sorted({sp.supplier_id for sp in p.prices.all()})
        self.assertEqual(ids, [self.sup.pk])


class SectionNavigationTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        self.client = Client()
        assert self.client.login(username="alice", password="pw")
        self.client.get(f"/switch/{self.dept.pk}/")
        # Keep the home page off the network in tests. Tests that need to
        # exercise the weather card explicitly override the return value.
        self._weather_patch = patch("stock.views.fetch_weather", return_value=None)
        self._weather_patch.start()
        self.addCleanup(self._weather_patch.stop)

    def test_home_renders_for_logged_in_user(self):
        r = self.client.get("/home/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Welcome / weather / urgent hero cards
        self.assertIn("alice", body)
        self.assertIn("Welcome to your dashboard", body)
        self.assertIn("Glastonbury", body)
        self.assertIn("Urgent Tasks", body)
        # Stock alerts card below
        self.assertIn("Stock alerts", body)

    def test_home_below_minimum_appears_in_urgent_card_and_alerts_table(self):
        # An ingredient counted below its minimum should:
        #   - bump the urgent badge to 1
        #   - appear as an aggregate line in the urgent card
        #   - render as a row in the per-ingredient stock alerts table
        #     with a Reorder action.
        flour = Product.objects.create(
            name="Flour", code="FLR1", department=self.dept, unit="g",
            minimum=Decimal("10"))
        st = Stocktake.objects.create(department=self.dept,
                                      date=datetime.date.today())
        StockLine.objects.create(stocktake=st, product=flour,
                                 current=Decimal("2"), carried_over=False)
        r = self.client.get("/home/")
        body = r.content.decode()

        urgent = body[body.index('class="panel strip urgent"'):body.index('id="stock-alerts"')]
        # Aggregate line in the urgent card + link to /reorder/
        self.assertIn("1 ingredient below minimum", urgent)
        self.assertIn('href="/reorder/"', urgent)
        # Badge shows the urgent count
        self.assertRegex(urgent, r'class="badge">\s*1\s*<')

        table = body[body.index('id="stock-alerts"'):]
        # Per-ingredient row with the ingredient name, alert label, detail
        # and Reorder action
        self.assertIn("Flour", table)
        self.assertIn("Below minimum", table)
        self.assertIn("2 / 10 packs", table)
        self.assertIn("Reorder", table)

    def test_home_renders_when_weather_fetch_fails(self):
        # Stop the default None-mock and replace with one that raises;
        # fetch_weather catches it and returns None, the page must still
        # render with a "weather unavailable" placeholder.
        self._weather_patch.stop()
        with patch("stock.views.fetch_weather", side_effect=RuntimeError("nope")) as p:
            try:
                r = self.client.get("/home/")
            except RuntimeError:
                self.fail("home view propagated weather error")
            else:
                # If side_effect doesn't get suppressed inside the view, the
                # request raises. Otherwise the fall-through is None, which
                # we want.
                self.assertEqual(r.status_code, 200)
                body = r.content.decode()
                self.assertIn("weather unavailable", body)
                self.assertIn("Glastonbury", body)
        # Restart the default patch so addCleanup's stop() still pairs.
        self._weather_patch.start()

    def test_home_renders_weather_card_when_fetch_succeeds(self):
        self._weather_patch.stop()
        weather = {
            "temperature": 12.4,
            "code": 1,
            "condition": "Partly cloudy",
            "icon": "◐",
            "time": "2026-05-22T15:00",
        }
        with patch("stock.views.fetch_weather", return_value=weather):
            r = self.client.get("/home/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("12°C", body)
        self.assertIn("Partly cloudy", body)
        self.assertIn("Live", body)
        self.assertIn("15:00", body)
        self._weather_patch.start()

    def test_home_calm_state_when_nothing_is_urgent(self):
        r = self.client.get("/home/")
        body = r.content.decode()
        urgent = body[body.index("Urgent Tasks"):body.index('id="stock-alerts"')]
        self.assertIn("All caught up", urgent)
        table = body[body.index('id="stock-alerts"'):]
        self.assertIn("Stock looks healthy", table)

    def test_stock_section_landing_renders_with_stock_submenu(self):
        # /stock/ is a Stock section page — its navbar carries the Stock
        # sub-menu (Dashboard / Stocktakes / Deliveries / ...). Body is minimal.
        r = self.client.get("/stock/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        nav = body[body.index("<nav>"):body.index("</nav>")]
        for url in ("/", "/stocktakes/", "/deliveries/", "/adjustments/",
                    "/reorder/", "/products/", "/suppliers/"):
            self.assertIn(f'href="{url}"', nav)

    def test_placeholder_sections_render_with_coming_soon(self):
        for path, title in (("/recipes/", "Recipes"), ("/production/", "Production"),
                            ("/rota/", "Rota"), ("/notes/", "Notes")):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, f"{path} returned {r.status_code}")
            body = r.content.decode()
            self.assertIn(title, body)
            self.assertIn("coming soon", body.lower())

    def test_profile_shows_username_departments_and_logout(self):
        r = self.client.get("/profile/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("alice", body)
        self.assertIn("Bakery", body)
        self.assertIn('action="/logout/"', body)

    def test_profile_shows_admin_link_only_for_superusers(self):
        r = self.client.get("/profile/")
        self.assertNotIn("/admin/", r.content.decode())

        U = get_user_model()
        boss = U.objects.create_superuser("boss", password="pw")
        c = Client()
        c.login(username="boss", password="pw")
        r = c.get("/profile/")
        self.assertIn("/admin/", r.content.decode())

    def _nav(self, body):
        nav = body[body.index("<nav>"):body.index("</nav>")]
        return nav, [m.group(1) for m in re.finditer(r">([A-Za-z]+)<", nav)]

    def test_home_navbar_shows_seven_top_sections(self):
        # Home's contextual navbar is the section picker:
        # Home | Stock | Recipes | Production | Rota | Notes | Profile,
        # with Home itself marked active.
        r = self.client.get("/home/")
        nav, labels = self._nav(r.content.decode())
        for top in ("Home", "Stock", "Recipes", "Production",
                    "Rota", "Notes", "Profile"):
            self.assertIn(top, labels)
        self.assertRegex(nav, r'href="/home/"\s+class="on"')

    def test_stock_section_nav_shows_sub_items(self):
        # Any Stock page (e.g. the dashboard) renders the Stock contextual
        # sub-menu in the top nav: Home + Dashboard / Stocktakes / Deliveries
        # / Adjustments / Reorder / Ingredients / Suppliers.
        r = self.client.get("/")
        body = r.content.decode()
        nav = body[body.index("<nav>"):body.index("</nav>")]
        for label in (">Home<", ">Dashboard<", ">Stocktakes<", ">Deliveries<",
                      ">Adjustments<", ">Reorder<", ">Ingredients<", ">Suppliers<"):
            self.assertIn(label, nav)
        # The Stock top-level link is NOT shown — the nav is contextual.
        self.assertNotIn('href="/stock/"', nav)

    def test_stock_sub_pages_highlight_themselves_not_a_top_link(self):
        for path, link in (
            ("/", '/'),
            ("/stocktakes/", '/stocktakes/'),
            ("/deliveries/", '/deliveries/'),
            ("/adjustments/", '/adjustments/'),
            ("/reorder/", '/reorder/'),
            ("/products/", '/products/'),
            ("/suppliers/", '/suppliers/'),
        ):
            r = self.client.get(path)
            body = r.content.decode()
            nav = body[body.index("<nav>"):body.index("</nav>")]
            self.assertRegex(
                nav, r'href="' + link + r'"\s+class="on"',
                f"{path} should highlight its own sub-nav link",
            )

    def test_placeholder_navbars_have_home_plus_section(self):
        for path, label in (("/recipes/", "Recipes"),
                            ("/production/", "Production"),
                            ("/rota/", "Rota"),
                            ("/notes/", "Notes")):
            r = self.client.get(path)
            nav, labels = self._nav(r.content.decode())
            self.assertEqual(nav.count("<a "), 2,
                             f"{path} navbar should be Home + section (2 links)")
            self.assertIn("Home", labels)
            self.assertIn(label, labels)
            self.assertRegex(nav, r'class="on"[^>]*>' + label)

    def test_profile_navbar_has_home_and_profile(self):
        r = self.client.get("/profile/")
        nav, labels = self._nav(r.content.decode())
        self.assertEqual(nav.count("<a "), 2)
        self.assertIn("Home", labels)
        self.assertIn("Profile", labels)

    def test_admin_link_in_header_only_for_superusers(self):
        # The Admin link lives in the header's right cluster (not the
        # contextual navbar), so superusers see it from every section.
        r = self.client.get("/home/")
        self.assertNotIn('href="/admin/"', r.content.decode())

        U = get_user_model()
        boss = U.objects.create_superuser("boss", password="pw")
        c = Client()
        c.login(username="boss", password="pw")
        # Visible on home, profile and a stock page alike
        for path in ("/home/", "/profile/", "/"):
            self.assertIn('href="/admin/"', c.get(path).content.decode(),
                          f"{path} should expose /admin/ to a superuser")

    def test_login_redirects_to_home(self):
        c = Client()
        r = c.post("/login/", {"username": "alice", "password": "pw"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/home/")

    def test_existing_urls_still_work(self):
        # Sanity: the existing stock pages keep their URLs and views.
        for path in ("/", "/stocktakes/", "/deliveries/", "/adjustments/",
                     "/reorder/", "/products/", "/suppliers/"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, f"{path} returned {r.status_code}")

    def test_stock_card_links_into_section(self):
        # Home's Stock card should land the user inside the Stock section.
        r = self.client.get("/home/")
        body = r.content.decode()
        self.assertIn('href="/stock/"', body)


class PackSizeFilterTests(SimpleTestCase):
    def test_grams_promoted_to_kg_at_threshold(self):
        self.assertEqual(pack_size(25000, "g"), "25 kg")
        self.assertEqual(pack_size(1500, "g"), "1.5 kg")
        self.assertEqual(pack_size(1000, "g"), "1 kg")

    def test_grams_under_threshold_stay_in_g(self):
        self.assertEqual(pack_size(500, "g"), "500 g")
        self.assertEqual(pack_size(999, "g"), "999 g")

    def test_millilitres_promoted_to_litres_at_threshold(self):
        self.assertEqual(pack_size(1500, "ml"), "1.5 L")
        self.assertEqual(pack_size(2000, "ml"), "2 L")
        self.assertEqual(pack_size(500, "ml"), "500 ml")

    def test_each_unit_passes_through(self):
        self.assertEqual(pack_size(12, "ea"), "12 ea")
        self.assertEqual(pack_size(1, "ea"), "1 ea")

    def test_accepts_decimal_input(self):
        self.assertEqual(pack_size(Decimal("25000.00"), "g"), "25 kg")
        self.assertEqual(pack_size(Decimal("1500.00"), "g"), "1.5 kg")
        self.assertEqual(pack_size(Decimal("500.50"), "g"), "500.5 g")

    def test_blank_inputs(self):
        self.assertEqual(pack_size(None, "g"), "")
        self.assertEqual(pack_size("", "g"), "")
        self.assertEqual(pack_size("not a number", "g"), "")

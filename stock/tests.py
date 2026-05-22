import datetime
import re
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, SimpleTestCase, Client
from .models import Department, Supplier, Product, SupplierPrice, Stocktake, StockLine, Delivery, Batch, Adjustment, IngredientAllergen, Recipe, RecipeLine, RecipeCycleError
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
        # Below-minimum stock now surfaces as an actionable "Ordering" task
        # with the item count, linking to /reorder/
        self.assertIn("Ordering", urgent)
        self.assertIn("1 item", urgent)
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

    def test_home_urgent_tasks_use_action_labels(self):
        # Expiring batch + overdue stocktake should produce "Use expiring
        # stock" and "Stocktake due" tasks respectively. Each task line is a
        # link to where the work is done.
        sup = Supplier.objects.create(name="Mill")
        flour = Product.objects.create(
            name="Flour", department=self.dept, unit="g", minimum=0)
        delivery = Delivery.objects.create(
            department=self.dept, supplier=sup,
            date=datetime.date.today() - datetime.timedelta(days=2))
        Batch.objects.create(
            delivery=delivery, product=flour, batch_code="A1",
            use_by=datetime.date.today() + datetime.timedelta(days=3),
            qty_received=Decimal("4"), qty_remaining=Decimal("4"))
        # An old stocktake makes the count overdue
        Stocktake.objects.create(
            department=self.dept,
            date=datetime.date.today() - datetime.timedelta(days=10))

        r = self.client.get("/home/")
        body = r.content.decode()
        urgent = body[body.index('class="panel strip urgent"'):body.index('id="stock-alerts"')]
        # Action labels, not status observations
        self.assertIn("Use expiring stock", urgent)
        self.assertIn("Stocktake due", urgent)
        # Links to where the user does the work
        self.assertIn('href="/deliveries/"', urgent)
        self.assertIn('href="/stocktakes/"', urgent)
        # Badge counts both
        self.assertRegex(urgent, r'class="badge">\s*2\s*<')

    def test_urgent_task_helper_returns_extendable_list(self):
        # _stock_tasks_for_home returns a list of {label, count, url} dicts
        # so other sources (manual tasks etc.) can append to the same list.
        from stock.views import _stock_tasks_for_home
        flour = Product.objects.create(
            name="Flour", department=self.dept, unit="g",
            minimum=Decimal("10"))
        st = Stocktake.objects.create(department=self.dept,
                                      date=datetime.date.today())
        StockLine.objects.create(stocktake=st, product=flour,
                                 current=Decimal("2"), carried_over=False)
        tasks = _stock_tasks_for_home(self.dept, datetime.date.today())
        # Each entry is a {label, count, url} dict
        self.assertGreaterEqual(len(tasks), 1)
        first = tasks[0]
        self.assertEqual(set(first.keys()), {"label", "count", "url"})
        self.assertEqual(first["label"], "Ordering")
        self.assertEqual(first["count"], 1)
        self.assertEqual(first["url"], "/reorder/")

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
        # Recipes is no longer a placeholder — it has its own list/import flow,
        # tested separately. The other three are still "coming soon".
        for path, title in (("/production/", "Production"),
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
        # Recipes now has Home + Recipes + Import sub-nav (tested elsewhere);
        # the other three placeholders remain Home + section.
        for path, label in (("/production/", "Production"),
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


class IngredientImportTests(TestCase):
    """The Excel master import + the matching reset command.

    The fixture workbook is built in-memory so tests don't depend on data/.
    """

    def _make_workbook(self, path, ingredients, uoms,
                       suppliers=None, supplier_names=None, allergens=None):
        """Build a four/five-tab fixture workbook.

        suppliers: list of {code, supplier_code, is_primary} dicts. Defaults
                   to a generated primary supplier per ingredient so tests
                   that don't care about supplier wiring still get prices.
        supplier_names: {supplier_code: name} for the Reference lookup.
                   Defaults to a generated name per supplier_code seen.
        allergens: optional list of {code, allergen, contains, may_contain}.
                   Omitted → no Allergens tab is written.
        """
        from openpyxl import Workbook
        wb = Workbook()
        ing_ws = wb.active
        ing_ws.title = "Ingredients"
        # Header up to Category (col 36). Only columns we read need real names;
        # the importer indexes by position, not header.
        header = [""] * 36
        header[0] = "Code"
        header[1] = "Description"
        header[33] = "Cost"
        header[34] = "Supply Unit"
        header[35] = "Category"
        ing_ws.append(header)
        for ing in ingredients:
            row = [""] * 36
            row[0] = ing["code"]
            row[1] = ing["name"]
            row[33] = ing["cost"]
            row[34] = ing["supply_unit"]
            row[35] = ing["category"]
            ing_ws.append(row)

        uom_ws = wb.create_sheet("Units Of Measure")
        uom_ws.append(["Code", "Description", "UOM", "Quantity", "RUOM", "Ref Quantity", "Is Default"])
        for u in uoms:
            uom_ws.append([u["code"], None, u["uom"], u.get("quantity", 1),
                           u["ruom"], u["ref_quantity"], "No"])

        if suppliers is None:
            suppliers = [
                {"code": ing["code"], "supplier_code": f"S{900 + i}", "is_primary": True}
                for i, ing in enumerate(ingredients, start=1)
            ]
        if supplier_names is None:
            supplier_names = {}
            for s in suppliers:
                supplier_names.setdefault(s["supplier_code"],
                                          f"Supplier {s['supplier_code']}")

        sup_ws = wb.create_sheet("Suppliers")
        sup_ws.append(["Code", "Description", "Supplier Code", "Supplier",
                       "Supplier Address", "Is Primary Supplier"])
        for s in suppliers:
            sup_ws.append([s["code"], None, s["supplier_code"], None, "",
                           "Yes" if s.get("is_primary") else "No"])

        # Reference tab mirrors the real shape: the first row is a wide list
        # of section labels, third row is sub-headers per section. We only
        # need the "Suppliers" section so put it at column 0.
        ref_ws = wb.create_sheet("Reference")
        ref_ws.append(["Suppliers"])             # row 1
        ref_ws.append([])                        # row 2 (blank)
        ref_ws.append(["Supplier Code", "Description"])  # row 3 sub-headers
        for code, name in supplier_names.items():
            ref_ws.append([code, name])

        if allergens is not None:
            alg_ws = wb.create_sheet("Allergens")
            alg_ws.append(["Code", "Description", "Allergen",
                           "Parts Per Million", "Contains", "May Contain"])
            for a in allergens:
                alg_ws.append([
                    a["code"], None, a["allergen"], "0",
                    "Yes" if a.get("contains") else "No",
                    "Yes" if a.get("may_contain") else "No",
                ])
        wb.save(path)

    def test_import_creates_products_with_code_name_category(self):
        import tempfile, os
        from django.core.management import call_command
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "ing.xlsx")
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I001", "name": "Bread Flour", "cost": 18.4,
                 "supply_unit": "Trade Paper Sack", "category": "Dry Goods"},
                {"code": "NPD-I002", "name": "Whole Milk", "cost": 2.39,
                 "supply_unit": "2 Litres", "category": "Dairy & Eggs"},
                {"code": "NPD-I003", "name": "Strawberries", "cost": 4.50,
                 "supply_unit": "Punnet", "category": "Fruit & Veg"},
                {"code": "NPD-I004", "name": "Mystery", "cost": 1.0,
                 "supply_unit": "Widget", "category": "Unassigned"},
            ],
            uoms=[
                {"code": "NPD-I001", "uom": "Trade Paper Sack", "ruom": "Kilograms", "ref_quantity": 16},
                {"code": "NPD-I002", "uom": "2 Litres", "ruom": "Kilograms", "ref_quantity": 2},
                {"code": "NPD-I003", "uom": "Punnet", "ruom": "Grams", "ref_quantity": 250},
                # NPD-I004 has no UOM row → flagged.
            ])
        call_command("import_ingredients", path)
        self.assertEqual(Product.objects.count(), 4)
        flour = Product.objects.get(code="NPD-I001")
        self.assertEqual(flour.name, "Bread Flour")
        self.assertEqual(flour.category, "dry_goods")
        self.assertEqual(flour.unit, "g")
        milk = Product.objects.get(code="NPD-I002")
        self.assertEqual(milk.category, "dairy_eggs")
        berries = Product.objects.get(code="NPD-I003")
        self.assertEqual(berries.category, "fruit_veg")
        mystery = Product.objects.get(code="NPD-I004")
        self.assertEqual(mystery.category, "unassigned")

    def test_16kg_sack_at_18_40_gives_pack_weight_16000_and_price_18_40(self):
        import tempfile, os
        from django.core.management import call_command
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "ing.xlsx")
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I001", "name": "Bread Flour", "cost": 18.4,
                 "supply_unit": "Trade Paper Sack", "category": "Dry Goods"},
            ],
            uoms=[
                {"code": "NPD-I001", "uom": "Trade Paper Sack", "ruom": "Kilograms", "ref_quantity": 16},
            ])
        call_command("import_ingredients", path)
        flour = Product.objects.get(code="NPD-I001")
        sp = flour.prices.get()
        self.assertEqual(sp.pack_weight, Decimal("16000"))
        self.assertEqual(sp.pack_price, Decimal("18.40"))

    def test_case_insensitive_supply_unit_match(self):
        # Ingredient supply unit "2 litres" (lowercase l) matches a UOM row
        # written as "2 Litres". Same for "Case" vs "case".
        import tempfile, os
        from django.core.management import call_command
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "ing.xlsx")
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I010", "name": "Milk", "cost": 2.0,
                 "supply_unit": "2 litres", "category": "Dairy & Eggs"},
                {"code": "NPD-I011", "name": "Jar", "cost": 3.0,
                 "supply_unit": "Case", "category": "Dry Goods"},
            ],
            uoms=[
                {"code": "NPD-I010", "uom": "2 Litres", "ruom": "Kilograms", "ref_quantity": 2},
                {"code": "NPD-I011", "uom": "case", "ruom": "Kilograms", "ref_quantity": 6},
            ])
        call_command("import_ingredients", path)
        self.assertEqual(Product.objects.get(code="NPD-I010").prices.get().pack_weight,
                         Decimal("2000"))
        self.assertEqual(Product.objects.get(code="NPD-I011").prices.get().pack_weight,
                         Decimal("6000"))

    def test_kilograms_supply_unit_without_uom_row_is_one_kg_pack(self):
        # Supply Unit "Kilograms" itself is a base unit - treat as 1kg pack
        # without needing a UOM row.
        import tempfile, os
        from django.core.management import call_command
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "ing.xlsx")
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I020", "name": "Fresh Yeast", "cost": 2.68,
                 "supply_unit": "Kilograms", "category": "Dry Goods"},
            ],
            uoms=[])
        call_command("import_ingredients", path)
        sp = Product.objects.get(code="NPD-I020").prices.get()
        self.assertEqual(sp.pack_weight, Decimal("1000"))
        self.assertEqual(sp.pack_price, Decimal("2.68"))

    def test_indirect_uom_chain_resolves(self):
        # Box → 40 Pack → 0.25 Kilograms = 10 kg = 10000 g
        import tempfile, os
        from django.core.management import call_command
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "ing.xlsx")
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I030", "name": "Butter", "cost": 50.0,
                 "supply_unit": "Box", "category": "Dairy & Eggs"},
            ],
            uoms=[
                {"code": "NPD-I030", "uom": "Pack", "ruom": "Kilograms", "ref_quantity": 0.25},
                {"code": "NPD-I030", "uom": "Box", "ruom": "Pack", "ref_quantity": 40},
            ])
        call_command("import_ingredients", path)
        sp = Product.objects.get(code="NPD-I030").prices.get()
        self.assertEqual(sp.pack_weight, Decimal("10000.00"))

    def test_ingredient_without_uom_is_created_but_flagged(self):
        # Mystery supply unit with no UOM row: ingredient still exists, but no
        # SupplierPrice gets written.
        import tempfile, os
        from django.core.management import call_command
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "ing.xlsx")
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I040", "name": "Mystery", "cost": 1.0,
                 "supply_unit": "Widget", "category": "Unassigned"},
            ],
            uoms=[])
        call_command("import_ingredients", path)
        p = Product.objects.get(code="NPD-I040")
        self.assertFalse(p.prices.exists())

    def test_import_is_idempotent(self):
        # Running twice doesn't duplicate products or pile up history.
        import tempfile, os
        from django.core.management import call_command
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "ing.xlsx")
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I001", "name": "Bread Flour", "cost": 18.4,
                 "supply_unit": "Trade Paper Sack", "category": "Dry Goods"},
            ],
            uoms=[
                {"code": "NPD-I001", "uom": "Trade Paper Sack", "ruom": "Kilograms", "ref_quantity": 16},
            ])
        call_command("import_ingredients", path)
        call_command("import_ingredients", path)
        self.assertEqual(Product.objects.filter(code="NPD-I001").count(), 1)
        flour = Product.objects.get(code="NPD-I001")
        self.assertEqual(flour.prices.count(), 1)
        self.assertEqual(flour.prices.get().pack_weight, Decimal("16000"))

    def test_import_assigns_to_department_arg(self):
        import tempfile, os
        from django.core.management import call_command
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "ing.xlsx")
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I001", "name": "X", "cost": 1.0,
                 "supply_unit": "Kilograms", "category": "Dry Goods"},
            ],
            uoms=[])
        call_command("import_ingredients", path, "--department", "Pastry")
        p = Product.objects.get(code="NPD-I001")
        self.assertEqual(p.department.name, "Pastry")

    # --- supplier wiring -------------------------------------------------

    def _tmp(self, name="ing.xlsx"):
        import tempfile, os
        return os.path.join(tempfile.mkdtemp(), name)

    def test_primary_supplier_s_code_resolves_to_name_and_gets_the_price(self):
        from django.core.management import call_command
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I100", "name": "Bread Flour", "cost": 18.4,
                 "supply_unit": "Trade Paper Sack", "category": "Dry Goods"},
            ],
            uoms=[
                {"code": "NPD-I100", "uom": "Trade Paper Sack",
                 "ruom": "Kilograms", "ref_quantity": 16},
            ],
            suppliers=[
                {"code": "NPD-I100", "supplier_code": "S31", "is_primary": True},
            ],
            supplier_names={"S31": "Wildfarmed"})
        call_command("import_ingredients", path)
        # Master Catalog must NOT be created — supplier comes from data.
        self.assertFalse(Supplier.objects.filter(name="Master Catalog").exists())
        # Real supplier created with the resolved name
        sup = Supplier.objects.get(name="Wildfarmed")
        flour = Product.objects.get(code="NPD-I100")
        sp = flour.prices.get()
        self.assertEqual(sp.supplier, sup)
        self.assertEqual(sp.pack_weight, Decimal("16000"))
        self.assertEqual(sp.pack_price, Decimal("18.40"))

    def test_primary_row_wins_over_other_supplier_rows(self):
        # An ingredient with several supplier rows: only the primary one is
        # used; secondary rows must not produce extra prices.
        from django.core.management import call_command
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I200", "name": "Milk", "cost": 2.39,
                 "supply_unit": "2 Litres", "category": "Dairy & Eggs"},
            ],
            uoms=[
                {"code": "NPD-I200", "uom": "2 Litres",
                 "ruom": "Kilograms", "ref_quantity": 2},
            ],
            suppliers=[
                {"code": "NPD-I200", "supplier_code": "S5", "is_primary": True},
                {"code": "NPD-I200", "supplier_code": "S3", "is_primary": False},
            ],
            supplier_names={"S5": "Bruton Dairies", "S3": "Wellocks"})
        call_command("import_ingredients", path)
        milk = Product.objects.get(code="NPD-I200")
        sp = milk.prices.get()  # exactly one price
        self.assertEqual(sp.supplier.name, "Bruton Dairies")

    def test_fallback_to_first_row_when_no_primary(self):
        # Edge case: nothing marked primary - take whichever row appears first.
        from django.core.management import call_command
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I300", "name": "Salt", "cost": 8.93,
                 "supply_unit": "Bag", "category": "Dry Goods"},
            ],
            uoms=[
                {"code": "NPD-I300", "uom": "Bag",
                 "ruom": "Kilograms", "ref_quantity": 10},
            ],
            suppliers=[
                {"code": "NPD-I300", "supplier_code": "S3", "is_primary": False},
                {"code": "NPD-I300", "supplier_code": "S14", "is_primary": False},
            ],
            supplier_names={"S3": "Wellocks", "S14": "The Fine Food Company"})
        call_command("import_ingredients", path)
        salt = Product.objects.get(code="NPD-I300")
        self.assertEqual(salt.prices.get().supplier.name, "Wellocks")

    def test_unresolvable_supplier_code_uses_code_as_name_and_flags(self):
        # An S-code that doesn't appear in the Reference lookup: name the
        # supplier after the code itself and surface it in the output.
        from django.core.management import call_command
        from io import StringIO
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I400", "name": "X", "cost": 1.0,
                 "supply_unit": "Bag", "category": "Dry Goods"},
            ],
            uoms=[
                {"code": "NPD-I400", "uom": "Bag",
                 "ruom": "Kilograms", "ref_quantity": 1},
            ],
            suppliers=[
                {"code": "NPD-I400", "supplier_code": "S999", "is_primary": True},
            ],
            supplier_names={})  # S999 not present
        out = StringIO()
        call_command("import_ingredients", path, stdout=out)
        # Supplier was created using the S-code as a fallback name
        sup = Supplier.objects.get(name="S999")
        self.assertEqual(Product.objects.get(code="NPD-I400").prices.get().supplier, sup)
        # And the run reports it
        self.assertIn("Unresolved supplier codes", out.getvalue())
        self.assertIn("S999", out.getvalue())

    def test_ingredient_with_no_supplier_row_is_flagged(self):
        # No row in Suppliers tab → no price (we can't pick a supplier).
        from django.core.management import call_command
        from io import StringIO
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I500", "name": "Orphan", "cost": 1.0,
                 "supply_unit": "Kilograms", "category": "Dry Goods"},
            ],
            uoms=[],
            suppliers=[],          # Suppliers tab has the header but no rows
            supplier_names={})
        out = StringIO()
        call_command("import_ingredients", path, stdout=out)
        p = Product.objects.get(code="NPD-I500")
        self.assertFalse(p.prices.exists())
        self.assertIn("no supplier", out.getvalue())

    def test_supplier_idempotent_on_rerun(self):
        # Re-running shouldn't create a duplicate Supplier OR a second price
        # row for the same (product, supplier).
        from django.core.management import call_command
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I600", "name": "Flour", "cost": 18.4,
                 "supply_unit": "Trade Paper Sack", "category": "Dry Goods"},
            ],
            uoms=[
                {"code": "NPD-I600", "uom": "Trade Paper Sack",
                 "ruom": "Kilograms", "ref_quantity": 16},
            ],
            suppliers=[
                {"code": "NPD-I600", "supplier_code": "S31", "is_primary": True},
            ],
            supplier_names={"S31": "Wildfarmed"})
        call_command("import_ingredients", path)
        call_command("import_ingredients", path)
        self.assertEqual(Supplier.objects.filter(name="Wildfarmed").count(), 1)
        flour = Product.objects.get(code="NPD-I600")
        self.assertEqual(flour.prices.count(), 1)
        self.assertEqual(flour.prices.get().pack_price, Decimal("18.40"))

    # --- allergens --------------------------------------------------------

    def test_allergens_attached_with_contains_and_may_contain(self):
        # WildFarmed flour shape: "Cereals containing gluten" (contains) +
        # "Soya" (may contain). Both must land on the product as separate
        # IngredientAllergen rows with the right flags.
        from django.core.management import call_command
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I100", "name": "Bread Flour", "cost": 18.4,
                 "supply_unit": "Trade Paper Sack", "category": "Dry Goods"},
            ],
            uoms=[
                {"code": "NPD-I100", "uom": "Trade Paper Sack",
                 "ruom": "Kilograms", "ref_quantity": 16},
            ],
            allergens=[
                {"code": "NPD-I100", "allergen": "Cereals containing gluten",
                 "contains": True, "may_contain": False},
                {"code": "NPD-I100", "allergen": "Soya",
                 "contains": False, "may_contain": True},
            ])
        call_command("import_ingredients", path)
        p = Product.objects.get(code="NPD-I100")
        gluten = p.allergens.get(name="Cereals containing gluten")
        self.assertTrue(gluten.contains)
        self.assertFalse(gluten.may_contain)
        soya = p.allergens.get(name="Soya")
        self.assertFalse(soya.contains)
        self.assertTrue(soya.may_contain)
        self.assertEqual(p.allergens.count(), 2)

    def test_allergen_import_is_idempotent(self):
        # Re-running must not duplicate rows or flip the flags.
        from django.core.management import call_command
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I101", "name": "Milk", "cost": 2.0,
                 "supply_unit": "Kilograms", "category": "Dairy & Eggs"},
            ],
            uoms=[],
            allergens=[
                {"code": "NPD-I101", "allergen": "Milk",
                 "contains": True, "may_contain": False},
            ])
        call_command("import_ingredients", path)
        call_command("import_ingredients", path)
        p = Product.objects.get(code="NPD-I101")
        self.assertEqual(p.allergens.count(), 1)
        self.assertEqual(IngredientAllergen.objects.filter(
            product=p, name="Milk").count(), 1)

    def test_ingredient_with_no_allergen_rows_has_none(self):
        from django.core.management import call_command
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I102", "name": "Salt", "cost": 1.0,
                 "supply_unit": "Kilograms", "category": "Dry Goods"},
            ],
            uoms=[],
            allergens=[
                {"code": "NPD-I999", "allergen": "Milk",  # different ingredient
                 "contains": True, "may_contain": False},
            ])
        call_command("import_ingredients", path)
        p = Product.objects.get(code="NPD-I102")
        self.assertEqual(p.allergens.count(), 0)

    def test_allergen_rows_for_unknown_ingredient_are_ignored(self):
        # An allergen row that points at a code not in the Ingredients tab
        # must not crash and must not create a phantom IngredientAllergen.
        from django.core.management import call_command
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I103", "name": "Salt", "cost": 1.0,
                 "supply_unit": "Kilograms", "category": "Dry Goods"},
            ],
            uoms=[],
            allergens=[
                {"code": "NPD-I999", "allergen": "Milk",
                 "contains": True, "may_contain": False},
            ])
        call_command("import_ingredients", path)
        self.assertEqual(IngredientAllergen.objects.count(), 0)

    def test_workbook_without_allergens_tab_still_imports(self):
        # Existing data files / partial fixtures without the Allergens tab
        # must keep working.
        from django.core.management import call_command
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I104", "name": "Salt", "cost": 1.0,
                 "supply_unit": "Kilograms", "category": "Dry Goods"},
            ],
            uoms=[])  # allergens=None → no Allergens tab written
        call_command("import_ingredients", path)
        self.assertTrue(Product.objects.filter(code="NPD-I104").exists())
        self.assertEqual(IngredientAllergen.objects.count(), 0)

    def test_no_master_catalog_supplier_created(self):
        # The old "Master Catalog" placeholder must never appear, even when
        # the workbook has no usable supplier data at all.
        from django.core.management import call_command
        path = self._tmp()
        self._make_workbook(path,
            ingredients=[
                {"code": "NPD-I700", "name": "X", "cost": 1.0,
                 "supply_unit": "Kilograms", "category": "Dry Goods"},
            ],
            uoms=[])
        call_command("import_ingredients", path)
        self.assertFalse(Supplier.objects.filter(name="Master Catalog").exists())


class AllergenDisplayTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        self.client = Client()
        assert self.client.login(username="alice", password="pw")
        self.client.get(f"/switch/{self.dept.pk}/")

    def test_contains_and_may_contain_render_in_separate_groups(self):
        flour = Product.objects.create(
            name="Bread Flour", code="NPD-I100", department=self.dept,
            unit="g", minimum=0)
        IngredientAllergen.objects.create(
            product=flour, name="Cereals containing gluten",
            contains=True, may_contain=False)
        IngredientAllergen.objects.create(
            product=flour, name="Soya", contains=False, may_contain=True)
        r = self.client.get(f"/products/{flour.pk}/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Section header present
        self.assertIn(">Allergens<", body)
        # Both labelled groups present in the right order
        contains_idx = body.find("Contains")
        may_idx = body.find("May contain")
        self.assertGreater(contains_idx, 0)
        self.assertGreater(may_idx, contains_idx)
        # The two allergens are tagged with the right CSS class
        contains_section = body[contains_idx:may_idx]
        self.assertIn('class="tag low"', contains_section)
        self.assertIn("Cereals containing gluten", contains_section)
        may_section = body[may_idx:]
        self.assertIn('class="tag prov"', may_section)
        self.assertIn("Soya", may_section)

    def test_no_allergens_shows_placeholder(self):
        salt = Product.objects.create(
            name="Salt", code="SLT1", department=self.dept,
            unit="g", minimum=0)
        r = self.client.get(f"/products/{salt.pk}/")
        body = r.content.decode()
        self.assertIn(">Allergens<", body)
        self.assertIn("No declared allergens", body)

    def test_contains_takes_precedence_over_may_contain(self):
        # An allergen with both flags shouldn't appear in both lists - it's
        # declared, so the firm tag wins and the soft one is suppressed.
        flour = Product.objects.create(
            name="Mixed", code="MIX1", department=self.dept,
            unit="g", minimum=0)
        IngredientAllergen.objects.create(
            product=flour, name="Milk", contains=True, may_contain=True)
        r = self.client.get(f"/products/{flour.pk}/")
        body = r.content.decode()
        contains_idx = body.find("Contains")
        may_idx = body.find("May contain")
        # No "May contain" group should render at all
        self.assertEqual(may_idx, -1)
        # Milk shows in the contains group
        self.assertIn('class="tag low"', body[contains_idx:])
        self.assertIn("Milk", body[contains_idx:])


class ResetStockDataTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        self.sup = Supplier.objects.create(name="Mill")
        self.flour = Product.objects.create(
            name="Flour", code="FLR1", department=self.dept, unit="g",
            minimum=Decimal("5"))
        SupplierPrice.objects.create(
            product=self.flour, supplier=self.sup,
            pack_weight=Decimal("25000"), pack_price=Decimal("30.00"))
        st = Stocktake.objects.create(department=self.dept,
                                      date=datetime.date(2026, 5, 22))
        StockLine.objects.create(stocktake=st, product=self.flour,
                                 current=Decimal("3"), carried_over=False)
        delivery = Delivery.objects.create(
            department=self.dept, supplier=self.sup,
            date=datetime.date(2026, 5, 22))
        Batch.objects.create(delivery=delivery, product=self.flour,
                             qty_received=Decimal("3"), qty_remaining=Decimal("3"))
        Adjustment.objects.create(
            department=self.dept, product=self.flour,
            quantity=Decimal("1"), reason="waste", user=self.user,
            date=datetime.date(2026, 5, 10))

    def test_without_yes_nothing_is_deleted(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command("reset_stock_data", stdout=out)
        # Everything still here
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(SupplierPrice.objects.count(), 1)
        self.assertEqual(Stocktake.objects.count(), 1)
        self.assertEqual(Delivery.objects.count(), 1)
        self.assertEqual(Batch.objects.count(), 1)
        self.assertEqual(Adjustment.objects.count(), 1)
        self.assertIn("Refusing", out.getvalue())

    def test_with_yes_clears_stock_but_leaves_auth_and_departments(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command("reset_stock_data", "--yes", stdout=out)
        # Stock content gone
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(SupplierPrice.objects.count(), 0)
        self.assertEqual(Stocktake.objects.count(), 0)
        self.assertEqual(StockLine.objects.count(), 0)
        self.assertEqual(Delivery.objects.count(), 0)
        self.assertEqual(Batch.objects.count(), 0)
        self.assertEqual(Adjustment.objects.count(), 0)
        # Auth + departments untouched
        self.assertEqual(get_user_model().objects.filter(username="alice").count(), 1)
        self.assertEqual(Department.objects.filter(name="Bakery").count(), 1)
        # Supplier rows also preserved - they're a separate dimension to stock.
        self.assertEqual(Supplier.objects.filter(name="Mill").count(), 1)
        # Department membership preserved
        self.assertTrue(self.dept.members.filter(username="alice").exists())
        # Summary lists what was cleared
        self.assertIn("Products: 1 deleted", out.getvalue())


# ----------------------------------------------------------------------
# Stage C1 — recipes
# ----------------------------------------------------------------------

SAMPLE_RECIPE_XLSX = "data/recipe_sample.xlsx"


class RecipeModelTests(TestCase):
    """The bare model contracts: XOR constraint + cycle detection helper."""

    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        self.product = Product.objects.create(
            name="Flour", code="NPD-I001", department=self.dept,
            unit="g", minimum=0)

    def test_recipeline_requires_exactly_one_target_neither(self):
        # Neither ingredient nor sub_recipe set → DB-level check refuses.
        from django.db.utils import IntegrityError
        r = Recipe.objects.create(code="NPD-R001", name="Bread", department=self.dept)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RecipeLine.objects.create(recipe=r, weight_g=Decimal("100"))

    def test_recipeline_requires_exactly_one_target_both(self):
        # Both set → DB-level check refuses.
        from django.db.utils import IntegrityError
        r = Recipe.objects.create(code="NPD-R002", name="Bread", department=self.dept)
        sub = Recipe.objects.create(code="NPD-R003", name="Starter", department=self.dept)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RecipeLine.objects.create(
                    recipe=r, ingredient=self.product, sub_recipe=sub,
                    weight_g=Decimal("100"))

    def test_recipeline_with_ingredient_only_saves(self):
        r = Recipe.objects.create(code="NPD-R010", name="X", department=self.dept)
        line = RecipeLine.objects.create(
            recipe=r, ingredient=self.product, weight_g=Decimal("50"))
        self.assertEqual(line.ingredient, self.product)
        self.assertIsNone(line.sub_recipe)

    def test_recipeline_with_sub_recipe_only_saves(self):
        r = Recipe.objects.create(code="NPD-R020", name="X", department=self.dept)
        sub = Recipe.objects.create(code="NPD-R021", name="Sub", department=self.dept)
        line = RecipeLine.objects.create(
            recipe=r, sub_recipe=sub, weight_g=Decimal("50"))
        self.assertEqual(line.sub_recipe, sub)
        self.assertIsNone(line.ingredient)

    def test_cycle_detection_rejects_self_reference(self):
        # A recipe must not directly contain itself.
        r = Recipe.objects.create(code="NPD-R100", name="Self", department=self.dept)
        self.assertTrue(r.contains_cycle(r.pk))

    def test_cycle_detection_rejects_transitive(self):
        # R1 -> R2 -> R3; adding R1 as a sub of R3 would loop.
        r1 = Recipe.objects.create(code="NPD-R201", name="A", department=self.dept)
        r2 = Recipe.objects.create(code="NPD-R202", name="B", department=self.dept)
        r3 = Recipe.objects.create(code="NPD-R203", name="C", department=self.dept)
        RecipeLine.objects.create(recipe=r1, sub_recipe=r2, weight_g=Decimal("10"))
        RecipeLine.objects.create(recipe=r2, sub_recipe=r3, weight_g=Decimal("10"))
        # Adding r1 as a sub-recipe of r3 must be detected
        self.assertTrue(r3.contains_cycle(r1.pk))
        # But adding an unrelated recipe is fine
        r4 = Recipe.objects.create(code="NPD-R204", name="D", department=self.dept)
        self.assertFalse(r3.contains_cycle(r4.pk))


class RecipeImportSampleTests(TestCase):
    """Importing the committed sample workbook produces the expected tree."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        cls.dept = Department.objects.create(name="Bakery")
        # Pre-create the NPD-I products that the sample references so the
        # ingredient-link assertions can use them.
        for code, name in (
            ("NPD-I10758", "WILDFARMED BREAD FLOUR (T65)"),
            ("NPD-I10756", "Water"),
            ("NPD-I11057", "FLOUR RYE DARK 100%"),
            ("NPD-I10893", "Dorset Sea Salt"),
            ("NPD-I10951", "WILDFARMED WHOLEMEAL FLOUR (T150)"),
            ("NPD-I10759", "WILDFARMED RUSTIC FLOUR (T80)"),
        ):
            Product.objects.create(
                code=code, name=name, department=cls.dept,
                unit="g", minimum=0)
        call_command("import_recipe", SAMPLE_RECIPE_XLSX, "--department", "Bakery")

    def test_main_recipe_imported_with_code_name_and_weights(self):
        r = Recipe.objects.get(code="NPD-R800")
        self.assertEqual(r.name, "Apple Waste Sourdough (Loose)")
        self.assertEqual(r.finished_weight_g, Decimal("600.000"))
        # Main has no separate Deposit row, falls back to Total
        self.assertEqual(r.deposit_weight_g, Decimal("600.000"))
        self.assertEqual(r.cook_loss_pct, Decimal("0.00"))

    def test_all_seven_sub_recipes_exist(self):
        codes = set(Recipe.objects.values_list("code", flat=True))
        for code in ("NPD-R800", "NPD-R364", "NPD-R2031",
                     "NPD-R2082", "NPD-R2029", "NPD-R1823", "NPD-R307"):
            self.assertIn(code, codes)
        self.assertEqual(Recipe.objects.count(), 7)

    def test_npd_r_lines_link_to_subrecipes(self):
        # NPD-R800 references NPD-R364 as a sub-recipe (600g).
        main = Recipe.objects.get(code="NPD-R800")
        line = main.lines.get()  # exactly one line
        self.assertIsNone(line.ingredient)
        self.assertEqual(line.sub_recipe.code, "NPD-R364")
        self.assertEqual(line.weight_g, Decimal("600.000"))

    def test_npd_i_lines_link_to_existing_ingredients_by_code(self):
        # NPD-R307 contains three NPD-I lines, all pre-created in setUpTestData.
        r307 = Recipe.objects.get(code="NPD-R307")
        codes_in_lines = {ln.ingredient.code for ln in r307.lines.all()
                          if ln.ingredient_id}
        self.assertEqual(codes_in_lines,
                         {"NPD-I10756", "NPD-I10759", "NPD-I10951"})
        # All three are the same Product rows we pre-created (no duplicates)
        for ln in r307.lines.all():
            self.assertTrue(ln.ingredient.pk)
            self.assertIsNone(ln.sub_recipe)

    def test_nested_subrecipe_weight_for_deep_chain(self):
        # NPD-R2031 has 6 lines; the sub_recipe one is NPD-R2082 at 63.2083g
        r2031 = Recipe.objects.get(code="NPD-R2031")
        self.assertEqual(r2031.lines.count(), 6)
        sub_line = r2031.lines.filter(sub_recipe__isnull=False).get()
        self.assertEqual(sub_line.sub_recipe.code, "NPD-R2082")
        self.assertEqual(sub_line.weight_g, Decimal("63.208"))

    def test_method_text_captured_for_recipes_that_have_it(self):
        r364 = Recipe.objects.get(code="NPD-R364")
        # The single Stage 1 instruction is captured
        self.assertIn("Take 660g of dough", r364.method_text)
        self.assertIn("Stage 1:", r364.method_text)
        # The main recipe has no Method section
        main = Recipe.objects.get(code="NPD-R800")
        self.assertEqual(main.method_text, "")

    def test_total_recipeline_count_is_21(self):
        # Sample: 1 (main) + 1 (R364) + 6 (R2031) + 3 (R2082)
        # + 3 (R2029) + 4 (R1823) + 3 (R307) = 21 lines
        self.assertEqual(RecipeLine.objects.count(), 21)


class RecipeImportIdempotencyTests(TestCase):
    """Re-running the importer updates rather than duplicating."""

    def test_re_import_same_workbook_is_idempotent(self):
        from django.core.management import call_command
        Department.objects.create(name="Bakery")
        call_command("import_recipe", SAMPLE_RECIPE_XLSX)
        first_recipes = Recipe.objects.count()
        first_lines = RecipeLine.objects.count()
        first_main = Recipe.objects.get(code="NPD-R800")
        # Run again
        call_command("import_recipe", SAMPLE_RECIPE_XLSX)
        self.assertEqual(Recipe.objects.count(), first_recipes)
        self.assertEqual(RecipeLine.objects.count(), first_lines)
        # Same row, not a new one (same PK; updated timestamp may change)
        second_main = Recipe.objects.get(code="NPD-R800")
        self.assertEqual(second_main.pk, first_main.pk)


class RecipeUnknownIngredientTests(TestCase):
    """Unknown NPD-I codes get stubbed and flagged in the summary."""

    def test_unknown_ingredient_creates_stub_and_flags(self):
        from django.core.management import call_command
        from io import StringIO
        # No pre-existing NPD-I products — the parser will create stubs.
        out = StringIO()
        call_command("import_recipe", SAMPLE_RECIPE_XLSX, stdout=out)
        # Six distinct NPD-I codes in the sample
        stubs = Product.objects.filter(code__startswith="NPD-I").count()
        self.assertEqual(stubs, 6)
        # The summary reports them
        self.assertIn("unknown ingredient", out.getvalue().lower())


class RecipeSaveCycleProtectionTests(TestCase):
    """save_recipes() must refuse a workbook that describes a cyclic recipe."""

    def test_self_referential_recipe_refused(self):
        from stock.recipe_import import save_recipes
        dept = Department.objects.create(name="Bakery")
        parsed = [{
            "code": "NPD-R900", "name": "Self-ref",
            "units_requested": None,
            "finished_weight_g": Decimal("100"),
            "deposit_weight_g": Decimal("100"),
            "cook_loss_pct": Decimal("0"),
            "method_text": "",
            "lines": [{
                "code": "NPD-R900", "name": "Self-ref",
                "weight_g": Decimal("50"), "is_subrecipe": True,
            }],
        }]
        with self.assertRaises(RecipeCycleError):
            save_recipes(parsed, dept)


class RecipesSectionViewTests(TestCase):
    """List page, upload form, preview-then-confirm flow, detail view."""

    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        self.client = Client()
        assert self.client.login(username="alice", password="pw")
        self.client.get(f"/switch/{self.dept.pk}/")

    def test_list_page_replaces_coming_soon(self):
        r = self.client.get("/recipes/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn("coming soon", body.lower())
        self.assertIn("Recipes", body)
        # Import CTA visible
        self.assertIn('href="/recipes/upload/"', body)

    def test_list_navbar_has_home_recipes_import(self):
        r = self.client.get("/recipes/")
        body = r.content.decode()
        nav = body[body.index("<nav>"):body.index("</nav>")]
        self.assertIn(">Home<", nav)
        self.assertIn(">Recipes<", nav)
        self.assertIn(">Import<", nav)

    def test_list_page_shows_imported_recipes(self):
        Recipe.objects.create(
            code="NPD-R100", name="Sample", department=self.dept,
            finished_weight_g=Decimal("500"))
        r = self.client.get("/recipes/")
        body = r.content.decode()
        self.assertIn("NPD-R100", body)
        self.assertIn("Sample", body)

    def test_upload_form_renders(self):
        r = self.client.get("/recipes/upload/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Import recipe", body)
        self.assertIn('name="file"', body)
        self.assertIn('enctype="multipart/form-data"', body)

    def test_upload_then_preview_then_confirm_creates_recipes(self):
        # Pre-create some of the NPD-I products so unknowns are minimal.
        for code, name in (("NPD-I10758", "Bread Flour"),
                           ("NPD-I10756", "Water")):
            Product.objects.create(
                code=code, name=name, department=self.dept,
                unit="g", minimum=0)

        with open(SAMPLE_RECIPE_XLSX, "rb") as f:
            upload = SimpleUploadedFile(
                "recipe_sample.xlsx", f.read(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        r = self.client.post("/recipes/upload/", {"file": upload})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/recipes/upload/preview/")

        # Preview page renders the parsed tree (nothing saved yet)
        self.assertEqual(Recipe.objects.count(), 0)
        r = self.client.get("/recipes/upload/preview/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("NPD-R800", body)
        self.assertIn("NPD-R364", body)
        # Unknown ingredients block surfaced (4 of 6 NPD-I codes are missing)
        self.assertIn("Unknown ingredient", body)

        # Confirm — commits the import
        r = self.client.post("/recipes/upload/preview/", {})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Recipe.objects.count(), 7)
        # Lands on main recipe's detail page
        main = Recipe.objects.get(code="NPD-R800")
        self.assertEqual(r.headers["Location"], f"/recipes/{main.pk}/")

    def test_preview_without_pending_redirects_to_upload(self):
        r = self.client.get("/recipes/upload/preview/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["Location"], "/recipes/upload/")

    def test_recipe_detail_shows_nested_tree(self):
        # Two-level recipe: main has one sub-recipe with two ingredients.
        flour = Product.objects.create(
            code="NPD-I10758", name="Flour", department=self.dept,
            unit="g", minimum=0)
        water = Product.objects.create(
            code="NPD-I10756", name="Water", department=self.dept,
            unit="g", minimum=0)
        sub = Recipe.objects.create(
            code="NPD-R200", name="Starter", department=self.dept,
            finished_weight_g=Decimal("100"))
        RecipeLine.objects.create(recipe=sub, ingredient=flour,
                                  weight_g=Decimal("60"), ordering=0)
        RecipeLine.objects.create(recipe=sub, ingredient=water,
                                  weight_g=Decimal("40"), ordering=1)
        main = Recipe.objects.create(
            code="NPD-R100", name="Loaf", department=self.dept,
            finished_weight_g=Decimal("400"), cook_loss_pct=Decimal("5"))
        RecipeLine.objects.create(recipe=main, sub_recipe=sub,
                                  weight_g=Decimal("100"), ordering=0)

        r = self.client.get(f"/recipes/{main.pk}/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Main recipe header
        self.assertIn("NPD-R100", body)
        self.assertIn("Loaf", body)
        # Sub-recipe shown nested with the right weight
        self.assertIn("NPD-R200", body)
        self.assertIn("Starter", body)
        # Raw ingredients reached via the sub-recipe tree
        self.assertIn("NPD-I10758", body)
        self.assertIn("NPD-I10756", body)
        # Weights rendered
        self.assertIn("100.0g", body)
        self.assertIn("60.0g", body)
        # Sub-recipe tag rendered
        self.assertIn("sub-recipe", body)

    def test_recipe_detail_blocked_for_other_department(self):
        other = Department.objects.create(name="Butchery")
        r = Recipe.objects.create(code="NPD-R900", name="X", department=other)
        resp = self.client.get(f"/recipes/{r.pk}/")
        self.assertEqual(resp.status_code, 403)

    def test_recipe_pages_require_login(self):
        c = Client()
        for path in ("/recipes/", "/recipes/upload/", "/recipes/upload/preview/"):
            r = c.get(path)
            self.assertEqual(r.status_code, 302)
            self.assertIn("/login/", r.headers["Location"])

    def test_recipe_delete_removes_recipe(self):
        r = Recipe.objects.create(code="NPD-R999", name="Gone", department=self.dept)
        resp = self.client.post(f"/recipes/{r.pk}/delete/")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Recipe.objects.filter(code="NPD-R999").exists())


class RecipeExplodedIngredientsTests(TestCase):
    """The flat per-batch ingredient list: scale through each sub-recipe and
    sum the same Product across branches."""

    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        self.flour = Product.objects.create(
            code="NPD-I001", name="Bread Flour",
            department=self.dept, unit="g", minimum=0)
        self.water = Product.objects.create(
            code="NPD-I002", name="Water",
            department=self.dept, unit="g", minimum=0)
        self.salt = Product.objects.create(
            code="NPD-I003", name="Salt",
            department=self.dept, unit="g", minimum=0)

    def _recipe(self, code, **kw):
        return Recipe.objects.create(code=code, department=self.dept, **kw)

    def _ing(self, recipe, product, weight, ordering=0):
        return RecipeLine.objects.create(
            recipe=recipe, ingredient=product,
            weight_g=Decimal(str(weight)), ordering=ordering)

    def _sub(self, recipe, sub_recipe, weight, ordering=0):
        return RecipeLine.objects.create(
            recipe=recipe, sub_recipe=sub_recipe,
            weight_g=Decimal(str(weight)), ordering=ordering)

    def test_simple_no_subrecipes_returns_direct_lines(self):
        r = self._recipe("NPD-R001", name="Flat",
                         finished_weight_g=Decimal("100"),
                         deposit_weight_g=Decimal("100"))
        self._ing(r, self.flour, 60)
        self._ing(r, self.water, 40)
        rows = r.exploded_ingredients()
        by_code = {row["ingredient"].code: row["weight_g"] for row in rows}
        self.assertEqual(by_code["NPD-I001"], Decimal("60"))
        self.assertEqual(by_code["NPD-I002"], Decimal("40"))

    def test_same_ingredient_in_one_recipe_is_summed(self):
        # A recipe can list the same product on two lines (e.g. water in
        # two mix stages) — the flat view collapses them into one row.
        r = self._recipe("NPD-R002", name="Two waters",
                         finished_weight_g=Decimal("60"),
                         deposit_weight_g=Decimal("60"))
        self._ing(r, self.water, 25, ordering=0)
        self._ing(r, self.water, 35, ordering=1)
        rows = r.exploded_ingredients()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ingredient"], self.water)
        self.assertEqual(rows[0]["weight_g"], Decimal("60"))

    def test_subrecipe_full_batch_consumed_keeps_ingredients_as_is(self):
        # Parent uses the entire finished output of the sub-recipe → no scaling.
        sub = self._recipe("NPD-R010", name="Dough",
                           finished_weight_g=Decimal("100"),
                           deposit_weight_g=Decimal("100"))
        self._ing(sub, self.flour, 60)
        self._ing(sub, self.water, 40)
        parent = self._recipe("NPD-R011", name="Loaf",
                              finished_weight_g=Decimal("100"),
                              deposit_weight_g=Decimal("100"))
        self._sub(parent, sub, 100)
        rows = parent.exploded_ingredients()
        by_code = {r["ingredient"].code: r["weight_g"] for r in rows}
        self.assertEqual(by_code["NPD-I001"], Decimal("60"))
        self.assertEqual(by_code["NPD-I002"], Decimal("40"))

    def test_subrecipe_partial_batch_scales_ingredients(self):
        # Parent uses 50g of a sub whose finished weight is 100g → 0.5×.
        sub = self._recipe("NPD-R020", name="Sub",
                           finished_weight_g=Decimal("100"),
                           deposit_weight_g=Decimal("100"))
        self._ing(sub, self.flour, 60)
        self._ing(sub, self.water, 40)
        parent = self._recipe("NPD-R021", name="Half loaf",
                              finished_weight_g=Decimal("50"),
                              deposit_weight_g=Decimal("50"))
        self._sub(parent, sub, 50)
        rows = parent.exploded_ingredients()
        by_code = {r["ingredient"].code: r["weight_g"] for r in rows}
        self.assertEqual(by_code["NPD-I001"], Decimal("30"))
        self.assertEqual(by_code["NPD-I002"], Decimal("20"))

    def test_subrecipe_scaling_uses_finished_weight_not_deposit(self):
        # Sub has 9.09% cook loss: deposit 660g, finished 600g. Parent uses
        # 600g (one finished batch). Scale must be 600/600 = 1.0, NOT
        # 600/660 = 0.909 — so each ingredient comes through at full
        # deposit-side weight.
        sub = self._recipe("NPD-R030", name="Sourdough single",
                           finished_weight_g=Decimal("600"),
                           deposit_weight_g=Decimal("660"))
        self._ing(sub, self.flour, 300)
        self._ing(sub, self.water, 300)
        self._ing(sub, self.salt, 60)
        parent = self._recipe("NPD-R031", name="Sourdough loose",
                              finished_weight_g=Decimal("600"),
                              deposit_weight_g=Decimal("600"))
        self._sub(parent, sub, 600)
        rows = parent.exploded_ingredients()
        by_code = {r["ingredient"].code: r["weight_g"] for r in rows}
        self.assertEqual(by_code["NPD-I001"], Decimal("300"))
        self.assertEqual(by_code["NPD-I002"], Decimal("300"))
        self.assertEqual(by_code["NPD-I003"], Decimal("60"))

    def test_same_ingredient_across_branches_is_summed(self):
        # Parent has TWO sub-recipes (Dough and Glaze) that both contain
        # flour. The flat view must collapse the two contributions into one
        # "Bread Flour: 80g" row.
        dough = self._recipe("NPD-R040", name="Dough",
                             finished_weight_g=Decimal("100"),
                             deposit_weight_g=Decimal("100"))
        self._ing(dough, self.flour, 60)
        self._ing(dough, self.water, 40)
        glaze = self._recipe("NPD-R041", name="Glaze",
                             finished_weight_g=Decimal("50"),
                             deposit_weight_g=Decimal("50"))
        self._ing(glaze, self.flour, 20)
        self._ing(glaze, self.water, 30)
        parent = self._recipe("NPD-R042", name="Glazed loaf",
                              finished_weight_g=Decimal("150"),
                              deposit_weight_g=Decimal("150"))
        self._sub(parent, dough, 100, ordering=0)
        self._sub(parent, glaze, 50, ordering=1)
        rows = parent.exploded_ingredients()
        by_code = {r["ingredient"].code: r["weight_g"] for r in rows}
        # Flour: 60 (dough) + 20 (glaze) = 80g
        self.assertEqual(by_code["NPD-I001"], Decimal("80"))
        # Water: 40 (dough) + 30 (glaze) = 70g
        self.assertEqual(by_code["NPD-I002"], Decimal("70"))
        # Exactly two distinct ingredients, no duplicates
        self.assertEqual(len(rows), 2)

    def test_deeply_nested_explosion_accumulates_repeat_across_levels(self):
        # Three levels deep: parent → starter → levain.
        # Flour appears at every level (one of the sample's real patterns).
        levain = self._recipe("NPD-R050", name="Levain",
                              finished_weight_g=Decimal("10"),
                              deposit_weight_g=Decimal("10"))
        self._ing(levain, self.flour, 5)
        self._ing(levain, self.water, 5)
        starter = self._recipe("NPD-R051", name="Starter",
                               finished_weight_g=Decimal("30"),
                               deposit_weight_g=Decimal("30"))
        self._ing(starter, self.flour, 10)
        self._ing(starter, self.water, 10)
        self._sub(starter, levain, 10)
        parent = self._recipe("NPD-R052", name="Loaf",
                              finished_weight_g=Decimal("100"),
                              deposit_weight_g=Decimal("100"))
        self._ing(parent, self.flour, 60)
        self._ing(parent, self.water, 10)
        self._sub(parent, starter, 30)
        rows = parent.exploded_ingredients()
        by_code = {r["ingredient"].code: r["weight_g"] for r in rows}
        # Flour: 60 (parent) + 10 (starter) + 5 (levain, via starter) = 75g
        self.assertEqual(by_code["NPD-I001"], Decimal("75"))
        # Water: 10 (parent) + 10 (starter) + 5 (levain) = 25g
        self.assertEqual(by_code["NPD-I002"], Decimal("25"))

    def test_results_sorted_by_ingredient_name(self):
        r = self._recipe("NPD-R060", name="Mixed",
                         finished_weight_g=Decimal("100"),
                         deposit_weight_g=Decimal("100"))
        self._ing(r, self.salt, 5)
        self._ing(r, self.flour, 60)
        self._ing(r, self.water, 35)
        rows = r.exploded_ingredients()
        names = [r["ingredient"].name for r in rows]
        self.assertEqual(names, ["Bread Flour", "Salt", "Water"])

    def test_cycle_in_data_does_not_infinite_loop(self):
        # If admin edits introduce a cycle (the import refuses one), the
        # explosion must terminate rather than recurse forever.
        a = self._recipe("NPD-R070", name="A",
                         finished_weight_g=Decimal("10"),
                         deposit_weight_g=Decimal("10"))
        b = self._recipe("NPD-R071", name="B",
                         finished_weight_g=Decimal("10"),
                         deposit_weight_g=Decimal("10"))
        self._sub(a, b, 10)
        self._sub(b, a, 10)
        # No assertion on contents — just that it returns rather than hangs.
        a.exploded_ingredients()


class RecipeDetailLayoutTests(TestCase):
    """The reworked layout: ingredients before method; sub-recipes collapsed
    by default; Structure / All-ingredients toggle."""

    def setUp(self):
        self.dept = Department.objects.create(name="Bakery")
        U = get_user_model()
        self.user = U.objects.create_user("alice", password="pw")
        self.dept.members.add(self.user)
        self.client = Client()
        assert self.client.login(username="alice", password="pw")
        self.client.get(f"/switch/{self.dept.pk}/")
        # Two-level recipe with method text.
        self.flour = Product.objects.create(
            code="NPD-I100", name="Flour", department=self.dept,
            unit="g", minimum=0)
        self.water = Product.objects.create(
            code="NPD-I101", name="Water", department=self.dept,
            unit="g", minimum=0)
        self.sub = Recipe.objects.create(
            code="NPD-R200", name="Starter", department=self.dept,
            finished_weight_g=Decimal("100"),
            deposit_weight_g=Decimal("100"),
            method_text="Mix and rest 12h.")
        RecipeLine.objects.create(
            recipe=self.sub, ingredient=self.flour,
            weight_g=Decimal("60"), ordering=0)
        RecipeLine.objects.create(
            recipe=self.sub, ingredient=self.water,
            weight_g=Decimal("40"), ordering=1)
        self.main = Recipe.objects.create(
            code="NPD-R100", name="Loaf", department=self.dept,
            finished_weight_g=Decimal("100"),
            deposit_weight_g=Decimal("100"),
            method_text="Bake at 230°C for 30 minutes.")
        RecipeLine.objects.create(
            recipe=self.main, sub_recipe=self.sub,
            weight_g=Decimal("100"), ordering=0)

    def test_ingredients_render_before_method_in_main_block(self):
        r = self.client.get(f"/recipes/{self.main.pk}/")
        body = r.content.decode()
        # Anchor on element markup so this doesn't false-positive on CSS
        # comments or unrelated text. The first `>Ingredients<` is the
        # main recipe's section label; the first `>show method<` is its
        # method toggle (sub-recipes are collapsed inside the main and
        # render their own labels later in the document).
        ing_idx = body.index(">Ingredients<")
        method_idx = body.index(">show method<")
        self.assertLess(ing_idx, method_idx,
                        "Ingredients should render before the method toggle")

    def test_method_is_collapsed_behind_a_toggle(self):
        r = self.client.get(f"/recipes/{self.main.pk}/")
        body = r.content.decode()
        # The method body is wrapped in a <details class="rec-method">
        # without `open`, so it's collapsed by default.
        self.assertRegex(body, r'<details class="rec-method">\s*<summary>')
        # The toggle label is present
        self.assertIn("show method", body)
        # The method text itself is still in the HTML (browser hides it)
        self.assertIn("Bake at 230", body)

    def test_subrecipes_collapsed_by_default(self):
        r = self.client.get(f"/recipes/{self.main.pk}/")
        body = r.content.decode()
        # Sub-recipe rows are wrapped in <details class="rec-sub"> with NO
        # `open` attribute — so the user clicks to expand.
        self.assertIn('<details class="rec-sub">', body)
        self.assertNotIn('<details class="rec-sub" open', body)
        # The "expand" affordance is shown
        self.assertIn("expand", body)
        # And nothing on the page auto-opens the sub-recipe
        # (the depth-0 recipe-block isn't wrapped in <details> at all)

    def test_structure_view_is_default(self):
        r = self.client.get(f"/recipes/{self.main.pk}/")
        body = r.content.decode()
        self.assertIn("Nested breakdown", body)
        self.assertNotIn("All raw ingredients", body)
        # View toggle: Structure is active
        self.assertRegex(body, r'class="on"[^>]*>Structure')

    def test_flat_view_renders_exploded_sums(self):
        r = self.client.get(f"/recipes/{self.main.pk}/?view=flat")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # Flat heading and the raw ingredient rows; Structure block hidden
        self.assertIn("All raw ingredients", body)
        self.assertNotIn("Nested breakdown", body)
        self.assertRegex(body, r'class="on"[^>]*>All ingredients')
        # Both raw ingredients show with their per-batch totals
        # (full batch consumed → unchanged weights)
        self.assertIn("NPD-I100", body)
        self.assertIn("Flour", body)
        self.assertIn("60.00", body)
        self.assertIn("NPD-I101", body)
        self.assertIn("Water", body)
        self.assertIn("40.00", body)

    def test_flat_view_does_not_list_sub_recipes(self):
        # The flat view is leaves-only — NPD-R sub-recipes themselves
        # should NOT appear as rows (only the raw NPD-I they explode to).
        r = self.client.get(f"/recipes/{self.main.pk}/?view=flat")
        body = r.content.decode()
        # The sub-recipe code appears in the toggle/back link area but not
        # as an ingredient row in the flat table.
        table_section = body[body.index("All raw ingredients"):]
        # Cut off at the next card / page footer
        end = table_section.find("← all recipes")
        if end > 0:
            table_section = table_section[:end]
        self.assertNotIn("NPD-R200", table_section)

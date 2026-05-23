import datetime
from decimal import Decimal
from django.db import models
from django.db.models import F, ExpressionWrapper, DecimalField, Sum, Q

PER_1000 = ExpressionWrapper(
    F("pack_price") / F("pack_weight") * 1000,
    output_field=DecimalField(max_digits=12, decimal_places=4),
)


from django.conf import settings


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)   # Bakery, Butchery...
    members = models.ManyToManyField(settings.AUTH_USER_MODEL,
                                     blank=True, related_name="departments")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def accessible_to(self, user):
        return user.is_superuser or self.members.filter(pk=user.pk).exists()


class Supplier(models.Model):
    name = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    UNIT_CHOICES = [("g", "grams"), ("ml", "millilitres"), ("ea", "each")]
    CATEGORY_CHOICES = [
        ("dry_goods", "Dry Goods"),
        ("dairy_eggs", "Dairy & Eggs"),
        ("frozen_goods", "Frozen Goods"),
        ("fruit_veg", "Fruit & Veg"),
        ("packaging", "Packaging"),
        ("unassigned", "Unassigned"),
    ]
    department = models.ForeignKey("Department", related_name="products",
                                   on_delete=models.CASCADE, null=True, blank=True)
    code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="unassigned")
    unit = models.CharField(max_length=8, choices=UNIT_CHOICES, default="g")
    minimum = models.DecimalField("minimum (par level)", max_digits=10, decimal_places=2, default=0)
    weekly_usage = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})" if self.code else self.name

    @property
    def cheapest_price(self):
        """Lowest £/1000 among the *latest* price for each supplier.

        Compares one row per supplier so old (overwritten) history rows can't
        masquerade as a cheaper offer.
        """
        best, best_p1000 = None, None
        for sp in self.latest_prices():
            if not sp.pack_weight:
                continue
            p1000 = sp.pack_price / sp.pack_weight * 1000
            if best is None or p1000 < best_p1000:
                best, best_p1000 = sp, p1000
        return best

    def latest_prices(self):
        """The most recent SupplierPrice per supplier (by effective_date, id).

        Iterates self.prices.all() so prefetch_related("prices__supplier") on
        the calling queryset is preserved.
        """
        latest = {}
        for sp in self.prices.all():
            cur = latest.get(sp.supplier_id)
            if cur is None or (sp.effective_date, sp.id) > (cur.effective_date, cur.id):
                latest[sp.supplier_id] = sp
        return list(latest.values())

    def price_history(self):
        """All price rows grouped by supplier, newest first, with per-row
        delta vs the prior price for that supplier. Notable = abs(delta) > 10%.
        """
        groups = {}
        for sp in self.prices.all():
            groups.setdefault(sp.supplier_id, []).append(sp)
        out = []
        for prices in groups.values():
            prices.sort(key=lambda s: (s.effective_date, s.id), reverse=True)
            entries = []
            for i, sp in enumerate(prices):
                prev = prices[i + 1] if i + 1 < len(prices) else None
                delta = None
                notable = False
                if prev and prev.pack_price:
                    delta = ((sp.pack_price - prev.pack_price) / prev.pack_price
                             * Decimal(100)).quantize(Decimal("0.1"))
                    notable = abs(delta) > Decimal("10")
                entries.append({
                    "price": sp, "previous": prev,
                    "delta_pct": delta, "notable": notable,
                })
            out.append({"supplier": prices[0].supplier, "entries": entries})
        out.sort(key=lambda g: g["supplier"].name.lower())
        return out

    @property
    def latest_line(self):
        return (StockLine.objects.filter(product=self, current__isnull=False)
                .select_related("stocktake").order_by("-stocktake__date", "-id").first())

    def history(self, limit=8):
        return list(StockLine.objects.filter(product=self, current__isnull=False)
                    .select_related("stocktake").order_by("-stocktake__date")[:limit])

    @property
    def on_hand_from_batches(self):
        return self.batches.aggregate(total=Sum("qty_remaining"))["total"] or Decimal("0")

    @property
    def adjustments_net(self):
        """Signed sum of adjustments (positive = stock added, negative = removed)."""
        agg = self.adjustments.aggregate(
            out=Sum("quantity", filter=Q(reason__in=Adjustment.REDUCING_REASONS)),
            inn=Sum("quantity", filter=Q(reason="found")),
        )
        return (agg["inn"] or Decimal("0")) - (agg["out"] or Decimal("0"))

    @property
    def on_hand(self):
        """Batch-derived on-hand minus net loss from logged adjustments."""
        return self.on_hand_from_batches + self.adjustments_net

    def usage_history(self, limit=8):
        """Per-count usage records, most recent first.

        usage = previous count's current + packs delivered strictly after the
        previous stocktake date and on/before this stocktake's date - this
        count's current. Only actually-counted lines (carried_over=False) are
        used; the first-ever count has no predecessor and is omitted.
        Negative usage is clamped to 0 and flagged.
        """
        if not self.department_id:
            return []
        lines = list(StockLine.objects
            .filter(product=self, stocktake__department_id=self.department_id,
                    carried_over=False, current__isnull=False)
            .select_related("stocktake")
            .order_by("-stocktake__date", "-id")[:limit + 1])
        rows = []
        for i in range(len(lines) - 1):
            line, prev = lines[i], lines[i + 1]
            cur_date, prev_date = line.stocktake.date, prev.stocktake.date
            delivered = Batch.objects.filter(
                product=self,
                delivery__department_id=self.department_id,
                delivery__date__gt=prev_date,
                delivery__date__lte=cur_date,
            ).aggregate(t=Sum("qty_received"))["t"] or Decimal("0")
            adj = Adjustment.objects.filter(
                product=self, department_id=self.department_id,
                date__gt=prev_date, date__lte=cur_date,
            ).aggregate(
                out=Sum("quantity", filter=Q(reason__in=Adjustment.REDUCING_REASONS)),
                inn=Sum("quantity", filter=Q(reason="found")),
            )
            adj_net = (adj["inn"] or Decimal("0")) - (adj["out"] or Decimal("0"))
            # C = P + D + adj_net - U   =>   U = P + D + adj_net - C
            # Logged waste is moved out of "usage" so burn-rate reflects real
            # consumption, not loss.
            raw = prev.current + delivered + adj_net - line.current
            clamped = raw < 0
            rows.append({
                "stocktake": line.stocktake,
                "previous": prev.stocktake,
                "previous_current": prev.current,
                "current": line.current,
                "delivered": delivered,
                "adjustments": adj_net,
                "usage": Decimal("0") if clamped else raw,
                "clamped": clamped,
                "days": (cur_date - prev_date).days,
            })
        return rows

    def average_weekly_usage(self, n=4):
        rows = self.usage_history(limit=n)
        if not rows:
            return None
        total = sum((r["usage"] for r in rows), Decimal("0"))
        return (total / len(rows)).quantize(Decimal("0.01"))

    def days_of_cover(self, on_hand, n=4):
        avg = self.average_weekly_usage(n=n)
        if avg is None or avg <= 0 or on_hand is None:
            return None
        return int((Decimal(on_hand) / avg * Decimal(7)).quantize(Decimal("1")))


class IngredientAllergen(models.Model):
    """One allergen declaration per ingredient.

    Sourced from the supplier-spec Allergens tab. An ingredient may have many
    rows (one per allergen). "contains" = the ingredient declares it; "may
    contain" = cross-contamination risk. Both flags can be False (a row that
    just records the allergen was checked and ruled out is uncommon in our
    data but harmless to store).
    """
    product = models.ForeignKey(Product, related_name="allergens", on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    contains = models.BooleanField(default=False)
    may_contain = models.BooleanField(default=False)

    class Meta:
        unique_together = ("product", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.product.name} — {self.name}"


class SupplierPrice(models.Model):
    """A supplier's price for a product, dated.

    Multiple rows per (product, supplier) are allowed; the most recent by
    effective_date (ties broken by id) is the "current" price. Past rows are
    retained as price history.
    """
    product = models.ForeignKey(Product, related_name="prices", on_delete=models.CASCADE)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE)
    pack_weight = models.DecimalField(max_digits=12, decimal_places=2)
    pack_price = models.DecimalField(max_digits=12, decimal_places=2)
    effective_date = models.DateField(default=datetime.date.today)

    class Meta:
        ordering = ["product", "-effective_date", "-id"]

    @property
    def per_1000(self):
        if not self.pack_weight:
            return None
        return (self.pack_price / self.pack_weight * 1000).quantize(Decimal("0.0001"))

    def __str__(self):
        return f"{self.product.name} @ {self.supplier.name}"


class Stocktake(models.Model):
    department = models.ForeignKey("Department", related_name="stocktakes",
                                   on_delete=models.CASCADE, null=True, blank=True)
    date = models.DateField()
    completed_by = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        dept = self.department.name if self.department else "Stocktake"
        return f"{dept} - {self.date:%d %b %Y}"

    @property
    def total_value(self):
        total = Decimal("0")
        for line in self.lines.select_related("product").all():
            v = line.value
            if v:
                total += v
        return total

    @property
    def counted(self):
        return self.lines.filter(current__isnull=False, carried_over=False).count()


class StockLine(models.Model):
    stocktake = models.ForeignKey(Stocktake, related_name="lines", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    current = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    carried_over = models.BooleanField(default=False)

    class Meta:
        unique_together = ("stocktake", "product")
        ordering = ["product__name"]

    @property
    def needed(self):
        if self.current is None:
            return None
        n = self.product.minimum - self.current
        return n if n > 0 else Decimal("0")

    @property
    def value(self):
        cheapest = self.product.cheapest_price
        if self.current is None or cheapest is None:
            return None
        return (self.current * cheapest.pack_price).quantize(Decimal("0.01"))


class Delivery(models.Model):
    department = models.ForeignKey(Department, related_name="deliveries", on_delete=models.CASCADE)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    date = models.DateField(default=datetime.date.today)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.supplier.name} - {self.date:%d %b %Y}"


class Batch(models.Model):
    delivery = models.ForeignKey(Delivery, related_name="batches",
                                 null=True, blank=True, on_delete=models.SET_NULL)
    product = models.ForeignKey(Product, related_name="batches", on_delete=models.PROTECT)
    batch_code = models.CharField(max_length=50, blank=True)
    use_by = models.DateField(null=True, blank=True)
    qty_received = models.DecimalField(max_digits=12, decimal_places=2)
    qty_remaining = models.DecimalField(max_digits=12, decimal_places=2)
    created = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ["use_by", "-created"]

    def __str__(self):
        return f"{self.product.name} {self.batch_code}".strip()

    @property
    def has_supplier_price(self):
        if not self.delivery_id:
            return True
        return SupplierPrice.objects.filter(
            product_id=self.product_id,
            supplier_id=self.delivery.supplier_id,
        ).exists()


class Adjustment(models.Model):
    """Wastage / discrepancy log against an ingredient.

    quantity is always stored as a positive magnitude in packs. The reason
    determines the effect on stock: waste, spillage and correction (i.e.
    counted less than expected) reduce stock; found / other increases it.
    Net signed effect is exposed via signed_qty.
    """
    REASON_CHOICES = [
        ("waste", "Waste"),
        ("spillage", "Spillage"),
        ("correction", "Correction (stock was less than expected)"),
        ("found", "Found / other (stock was more than expected)"),
    ]
    REDUCING_REASONS = ("waste", "spillage", "correction")

    product = models.ForeignKey(Product, related_name="adjustments", on_delete=models.CASCADE)
    department = models.ForeignKey(Department, related_name="adjustments", on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    date = models.DateField(default=datetime.date.today)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.SET_NULL, null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.get_reason_display()} - {self.product.name} ({self.quantity})"

    @property
    def signed_qty(self):
        return self.quantity if self.reason == "found" else -self.quantity


class Customer(models.Model):
    """A bakery customer — either an internal Estate outlet (the GARDEN CAFE,
    FARMSHOP, BUTCHERY…) or a wholesale account (TEALS, PINKMANS, SOCIETY…).

    Identity is the name (case-preserved, but cross-referenced case-insensitively
    on import). customer_type is auto-classified by the importer based on
    appearance in the order sheet's WHOLESALE tab; ``is_type_manual`` is set
    when the operator picks the type by hand, so the next re-import won't
    overwrite that choice (same pattern as ``Recipe.is_sold_manual``).
    """
    INTERNAL = "internal"
    WHOLESALE = "wholesale"
    TYPE_CHOICES = [
        (INTERNAL, "Internal"),
        (WHOLESALE, "Wholesale"),
    ]

    name = models.CharField(max_length=120, unique=True)
    location = models.CharField(max_length=120, blank=True)
    ordered_by = models.CharField(max_length=120, blank=True)
    customer_type = models.CharField(
        max_length=12, choices=TYPE_CHOICES, default=INTERNAL)
    # ``is_type_manual`` is the "operator touched this customer" flag — it
    # protects ALL editable fields (customer_type, ordered_by, location)
    # from being overwritten by the next import_customers run. The name is
    # historical; the scope grew as the customers UI did.
    is_type_manual = models.BooleanField(default=False)
    # ``is_manual_entry`` flags rows the operator created by hand (not from
    # the order sheet). The importer skips these entirely on every run, so
    # hand-added customers never get clobbered or deleted by a re-import.
    is_manual_entry = models.BooleanField(default=False)
    department = models.ForeignKey(
        "Department", related_name="customers",
        on_delete=models.CASCADE, null=True, blank=True)
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SaleProduct(models.Model):
    """A sellable SKU on the bakery order sheet — DISTINCT from `Product`.

    The legacy ``Product`` model is the ingredient master (NPD-I codes,
    packs, supplier prices). ``SaleProduct`` is what the bakery actually
    sells: line items in the order sheet ("Apple Waste Sourdough
    (Loose)", "Croissant (Pack/4)", "Mince Pies Internal (Pack/6)"). A
    sale product is linked to a single ``Recipe`` (the bill of
    materials), but a single recipe can back many sale products —
    Internal vs Retail, Loose vs Pack/N, different sizes.

    Identity is the verbatim imported name (case-insensitive on lookup,
    case-preserved on display). The name is NEVER overwritten by the
    recipe name — the order sheet is authoritative.

    ``link_source`` records how the recipe link was established:
      * ``sage`` — product.sage_number matched a Recipe.code exactly.
                   Auto-confirmed (Sage codes are reliable).
      * ``name`` — product.name matched a recipe.name exactly
                   (case-insensitive). Auto-confirmed.
      * ``manual`` — the operator picked the recipe in the UI. NEVER
                     overwritten by import.
      * ``none`` — unlinked. The link-review page surfaces fuzzy
                   suggestions for the operator to confirm.

    ``link_confirmed`` is the green-tick state in the review UI; it's
    True for both Sage and exact-name matches plus any manual pick.
    ``is_manual_entry`` is the same pattern as Customer: a hand-created
    SaleProduct that the importer should never touch.
    """
    SAGE = "sage"
    NAME = "name"
    MANUAL = "manual"
    NONE = "none"
    LINK_SOURCE_CHOICES = [
        (SAGE, "Sage No. match"),
        (NAME, "Exact name match"),
        (MANUAL, "Manually linked"),
        (NONE, "Not linked"),
    ]

    # Link unit choices for the quantified, polymorphic link.
    COUNT = "count"
    WEIGHT_KG = "weight_kg"
    WEIGHT_G = "weight_g"
    LINK_UNIT_CHOICES = [
        (COUNT, "Units (count)"),
        (WEIGHT_KG, "Kilograms"),
        (WEIGHT_G, "Grams"),
    ]

    name = models.CharField(max_length=200, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    sage_number = models.CharField(max_length=40, blank=True)
    pack_size = models.CharField(max_length=40, blank=True)
    # Quantified, polymorphic link. EITHER link_recipe (a Recipe — the
    # bill of materials), OR link_product (another SaleProduct — e.g.
    # a Pack/6 points at the Loose product). Both nullable; at most one
    # set at a time (DB CheckConstraint). Quantity + unit describe how
    # much of the target this SaleProduct represents: 6 × count for
    # "Pack/6 of Loose", or 3.75 × weight_kg for "Focaccia 3.75kg".
    # ``resolved_recipe_consumption`` walks the chain (product → product
    # → … → recipe) multiplying quantities so production maths can use
    # the eventual recipe and total multiplier.
    link_recipe = models.ForeignKey(
        "Recipe", related_name="sale_products",
        on_delete=models.SET_NULL, null=True, blank=True)
    link_product = models.ForeignKey(
        "self", related_name="linked_packs",
        on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Another SaleProduct this one is a multiple of "
                  "(e.g. Pack/6 → Loose).")
    link_quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=1,
        help_text="How many units / kg / g of the target.")
    link_unit = models.CharField(
        max_length=12, choices=LINK_UNIT_CHOICES, default=COUNT)
    link_source = models.CharField(
        max_length=10, choices=LINK_SOURCE_CHOICES, default=NONE)
    link_confirmed = models.BooleanField(default=False)
    department = models.ForeignKey(
        "Department", related_name="sale_products",
        on_delete=models.CASCADE, null=True, blank=True)
    active = models.BooleanField(default=True)
    is_manual_entry = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            # Mirrors the RecipeLine ingredient/sub_recipe XOR. Both
            # null = unlinked (fine); exactly one set = linked to a
            # recipe OR another product; both set = ambiguous and
            # rejected at the DB level.
            models.CheckConstraint(
                check=(Q(link_recipe__isnull=True) |
                       Q(link_product__isnull=True)),
                name="saleproduct_link_recipe_xor_product",
            ),
        ]

    def __str__(self):
        return self.name

    # Backwards-compat shim: a chunk of existing UI + tests reach for
    # ``sale_product.recipe`` directly. The property mirrors
    # ``link_recipe`` so old code keeps working while new code targets
    # ``link_recipe`` explicitly. The setter assigns to ``link_recipe``
    # so ``sp.recipe = some_recipe`` still updates the FK.
    @property
    def recipe(self):
        return self.link_recipe

    @recipe.setter
    def recipe(self, value):
        self.link_recipe = value

    @property
    def recipe_id(self):
        return self.link_recipe_id

    def resolved_recipe_consumption(self, *, max_hops=32):
        """Walk product → product → … → recipe, multiplying quantities.

        Returns ``(recipe, total_quantity, effective_unit)`` when the
        chain ends at a Recipe, or ``(None, Decimal('0'), None)`` when
        it terminates with an unlinked product. Cycle-protected: a
        loop raises :class:`SaleProductCycleError`. ``max_hops`` caps
        chain length defensively (a healthy chain is 1–3 hops).

        ``total_quantity`` is the product of every ``link_quantity``
        along the chain. ``effective_unit`` is the first non-count
        unit encountered (closest to the surface wins) so a 6-count
        Pack of a 1-kg Loose resolves to 6 kg of the recipe.
        """
        from decimal import Decimal
        seen = {self.pk}
        current = self
        total = Decimal("1")
        effective_unit = None
        for _ in range(max_hops):
            qty = current.link_quantity if current.link_quantity is not None else Decimal("1")
            total *= qty
            unit = current.link_unit or self.COUNT
            if effective_unit is None and unit != self.COUNT:
                effective_unit = unit
            if current.link_recipe_id:
                if effective_unit is None:
                    effective_unit = self.COUNT
                return current.link_recipe, total, effective_unit
            if current.link_product_id is None:
                return None, Decimal("0"), None
            if current.link_product_id in seen:
                raise SaleProductCycleError(
                    f"SaleProduct chain cycles via {current.link_product_id}")
            seen.add(current.link_product_id)
            current = current.link_product
        raise SaleProductCycleError(
            f"SaleProduct chain longer than {max_hops} hops — refusing to resolve")


class RecipeCycleError(Exception):
    """A recipe would (transitively) contain itself."""


class SaleProductCycleError(Exception):
    """A SaleProduct's link chain would (transitively) reference itself.

    Raised by ``SaleProduct.resolved_recipe_consumption`` when walking
    ``link_product`` references hits a previously-visited row or
    overruns the defensive hop cap.
    """


class Recipe(models.Model):
    """A recipe / sub-recipe / bill-of-materials.

    Codes match the Excel export (e.g. NPD-R800). A recipe's lines may point
    at raw ingredients (Product) or at other Recipes (sub-recipes), which is
    how multi-stage bakery formulas (starter -> ferment -> dough -> finished
    loaf) are modelled.

    Two independent properties classify a recipe:

    - ``is_used_as_component`` (live-derived from ``parents()``) — true iff
      any other Recipe references it via RecipeLine.sub_recipe. Never
      stored; can't go stale.
    - ``sold_as_product`` (stored bool) — true iff we sell this recipe as
      a standalone product. On import, defaults from references (not used
      → sold; used → not sold) but ``is_sold_manual`` locks in any operator
      choice so re-imports won't clobber it.

    A recipe can be BOTH at once — a dough sold per kg that's also used
    inside pastries is sold_as_product=True AND is_used_as_component=True.
    """
    department = models.ForeignKey("Department", related_name="recipes",
                                   on_delete=models.CASCADE, null=True, blank=True)
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    finished_weight_g = models.DecimalField(max_digits=12, decimal_places=3,
                                            null=True, blank=True)
    deposit_weight_g = models.DecimalField(max_digits=12, decimal_places=3,
                                           null=True, blank=True)
    cook_loss_pct = models.DecimalField(max_digits=6, decimal_places=2,
                                        null=True, blank=True)
    method_text = models.TextField(blank=True)
    # Set on import (true if not used by anything, false if used as
    # sub_recipe). Manual overrides via the list page set is_sold_manual=True
    # so subsequent recompute_all_sold_defaults() leaves them alone.
    sold_as_product = models.BooleanField(default=True)
    is_sold_manual = models.BooleanField(default=False)
    # ``is_basic_manual`` is the "operator hand-edited this recipe's basic
    # fields" flag — name, finished/deposit/cook_loss, the sold checkbox.
    # When set, the bulk re-import leaves those values alone (the same way
    # ``is_sold_manual`` protects the sold flag); RecipeLines are still
    # rebuilt from the workbook because that's how a re-import keeps the
    # bill of materials in sync. Mirrors ``Customer.is_type_manual``.
    is_basic_manual = models.BooleanField(default=False)
    # Archive is the soft-delete / reversible "hide from views" state.
    # Archived recipes keep their lines and packaging links — restoring is
    # a one-field flip. The deploy-time re-import refreshes their basics
    # but never un-archives them (see ``save_recipes``); hard-delete
    # (the rare escape hatch on the detail page) still removes the row
    # and writes a ``SuppressedRecipe`` so it can't be resurrected.
    archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.name} ({self.code})"

    # ---- structural helpers ----

    def parents(self):
        """Recipes that reference this one as a sub_recipe (any number).

        Ordered by code for stable presentation; deduped (a parent that
        uses the same sub-recipe on two lines shows once).
        """
        return (Recipe.objects
                .filter(lines__sub_recipe_id=self.pk)
                .distinct()
                .order_by("code"))

    @property
    def is_used_as_component(self):
        """True iff any other recipe references this one as a sub_recipe.

        Live-derived; never stored. Uses the reverse `used_in_lines`
        relation so a single prefetch on the caller (``prefetch_related
        ('used_in_lines')``) makes this O(1) without an extra query.
        """
        return self.used_in_lines.exists()

    # ---- sold_as_product recompute (default-from-references) ----

    def recompute_sold_default(self, save=True):
        """Re-derive `sold_as_product` from current RecipeLine references.

        Not referenced → sold (a top-level product); referenced → not sold
        (it's purely an internal component). No-op if the operator has set
        ``is_sold_manual=True``. Returns the resolved value.
        """
        if self.is_sold_manual:
            return self.sold_as_product
        new_value = not self.parents().exists()
        if new_value != self.sold_as_product:
            self.sold_as_product = new_value
            if save:
                self.save(update_fields=["sold_as_product"])
        return self.sold_as_product

    @classmethod
    def recompute_all_sold_defaults(cls):
        """Refresh `sold_as_product` for every non-manual recipe in one pass.

        Two queries: collect every sub_recipe id in use, then two UPDATEs
        (referenced → not sold; everything else → sold). Manual overrides
        are excluded so operator choices survive re-imports.
        """
        referenced = set(
            RecipeLine.objects
            .filter(sub_recipe__isnull=False)
            .values_list("sub_recipe_id", flat=True))
        cls.objects.filter(is_sold_manual=False, pk__in=referenced).update(
            sold_as_product=False)
        cls.objects.filter(is_sold_manual=False).exclude(
            pk__in=referenced).update(sold_as_product=True)

    def exploded_ingredients(self):
        """Flat list of raw ingredients to make one stated batch of this recipe.

        Walks every sub-recipe; at each step scales components by
        ``parent_line_weight / sub.finished_weight_g`` so deeper batches
        contribute the amount the parent actually consumes (a parent line
        is a quantity of *finished* sub-recipe output, after the sub's
        cook loss). The same Product appearing across multiple branches is
        summed into a single row.

        Returns a list of ``{ingredient: Product, weight_g: Decimal}``
        sorted by ingredient name. Reused by the flat detail view and
        intended for the production / consumption flows.
        """
        totals = {}
        self._explode_into(totals, Decimal("1"), set())
        return sorted(totals.values(),
                      key=lambda e: e["ingredient"].name.lower())

    def _explode_into(self, totals, multiplier, seen):
        """Recursive accumulator; safe against cycles via `seen`."""
        if self.pk in seen:
            return
        seen = seen | {self.pk}
        for line in self.lines.select_related("ingredient", "sub_recipe").all():
            if line.ingredient_id:
                key = line.ingredient_id
                wt = line.weight_g * multiplier
                if key in totals:
                    totals[key]["weight_g"] += wt
                else:
                    totals[key] = {"ingredient": line.ingredient, "weight_g": wt}
            elif line.sub_recipe_id:
                sub = line.sub_recipe
                # Parent's line uses N grams of the sub's *finished* output;
                # fall back to deposit (input) weight, then to the line sum,
                # only if finished isn't populated.
                ref = sub.finished_weight_g or sub.deposit_weight_g
                if not ref or ref == 0:
                    ref = sum((ln.weight_g for ln in sub.lines.all()),
                              Decimal("0")) or Decimal("1")
                sub_mult = multiplier * (line.weight_g / ref)
                sub._explode_into(totals, sub_mult, seen)

    def all_packaging(self):
        """Distinct packaging Products used by this recipe or any sub-recipe.

        Walks the sub-recipe tree (with cycle protection) and returns a
        list of Product rows deduped by pk, code-sorted. Used by the
        detail page so a sold product shows the packaging from its
        nested components, not just whatever the top-level recipe
        section happened to link directly.
        """
        seen_recipes = set()
        packaging_by_pk = {}
        stack = [self]
        while stack:
            r = stack.pop()
            if r.pk in seen_recipes:
                continue
            seen_recipes.add(r.pk)
            for link in r.packaging_links.select_related("packaging"):
                packaging_by_pk.setdefault(link.packaging.pk, link.packaging)
            for line in (r.lines.filter(sub_recipe__isnull=False)
                         .select_related("sub_recipe")):
                stack.append(line.sub_recipe)
        return sorted(packaging_by_pk.values(),
                      key=lambda p: (p.code or "").lower())

    def contains_cycle(self, candidate_child_id):
        """Would adding `candidate_child_id` as a sub-recipe create a cycle?

        Walks the candidate's transitive sub-recipes; returns True iff this
        recipe is reachable from there (or *is* the candidate). Use before
        saving a new RecipeLine to refuse self-references and deeper loops.
        """
        if candidate_child_id is None:
            return False
        if candidate_child_id == self.pk:
            return True
        seen = set()
        stack = [candidate_child_id]
        while stack:
            rid = stack.pop()
            if rid in seen:
                continue
            seen.add(rid)
            if rid == self.pk:
                return True
            for child_id in (RecipeLine.objects
                             .filter(recipe_id=rid, sub_recipe__isnull=False)
                             .values_list("sub_recipe_id", flat=True)):
                stack.append(child_id)
        return False


class RecipeLine(models.Model):
    """One ingredient row of a recipe.

    Exactly one of `ingredient` (a raw Product) or `sub_recipe` (another
    Recipe) is set, enforced by a DB check constraint. `weight_g` is the
    quantity of that component used in the parent recipe.
    """
    recipe = models.ForeignKey(Recipe, related_name="lines", on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Product, related_name="recipe_lines",
                                   on_delete=models.PROTECT, null=True, blank=True)
    sub_recipe = models.ForeignKey(Recipe, related_name="used_in_lines",
                                   on_delete=models.PROTECT, null=True, blank=True)
    weight_g = models.DecimalField(max_digits=12, decimal_places=3)
    ordering = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordering", "id"]
        constraints = [
            models.CheckConstraint(
                check=(
                    (Q(ingredient__isnull=False) & Q(sub_recipe__isnull=True)) |
                    (Q(ingredient__isnull=True) & Q(sub_recipe__isnull=False))
                ),
                name="recipeline_xor_ingredient_subrecipe",
            ),
        ]

    def __str__(self):
        target = self.ingredient or self.sub_recipe
        return f"{self.recipe.code}: {target} ({self.weight_g}g)"

    @property
    def component(self):
        return self.ingredient or self.sub_recipe


class SuppressedRecipe(models.Model):
    """Records a recipe code that the operator deleted by hand.

    The bulk re-import (``import_recipes_bulk``) runs every deploy. Without
    a record of deletions, deleting NPD-R800 in the UI would silently
    bring it back next time the workbook is re-imported, because the
    sheet for that recipe is still in the file.

    Holding the code (not the FK — the Recipe row is gone) means the
    suppression survives the delete and the next import. Both
    ``save_recipes`` and the auto-stubbing path skip codes present here,
    so neither the main recipe nor a leftover sub-recipe reference will
    re-create the row. Un-suppress by deleting the row in the admin —
    the next deploy will then re-import the recipe as normal.
    """
    code = models.CharField(max_length=20, unique=True)
    reason = models.CharField(max_length=200, blank=True)
    suppressed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class RecipePackaging(models.Model):
    """A packaging item used by a recipe.

    Modelled separately from RecipeLine because packaging has different
    semantics: the raw quantity from the export is in unreliable units
    (per-gram fractions like ``4.41897311481717E-05Each``, per-pack
    strings like ``50g``, etc.). We store the original string verbatim
    so future production maths can interpret it, and surface the link
    on the recipe detail page so the bakery can see which packaging a
    product is built with.
    """
    recipe = models.ForeignKey(
        Recipe, related_name="packaging_links", on_delete=models.CASCADE)
    packaging = models.ForeignKey(
        Product, related_name="used_in_recipe_packaging",
        on_delete=models.PROTECT,
        help_text="A Product in the Packaging category (NPD-P*).")
    # Raw, exporter-provided quantity string — kept as-is so we can revisit
    # the units question without re-importing.
    raw_quantity = models.CharField(max_length=64, blank=True)
    ordering = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordering", "id"]
        unique_together = ("recipe", "packaging")

    def __str__(self):
        return f"{self.recipe.code} ↔ {self.packaging.code}"

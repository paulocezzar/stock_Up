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


class RecipeCycleError(Exception):
    """A recipe would (transitively) contain itself."""


class Recipe(models.Model):
    """A recipe / sub-recipe / bill-of-materials.

    Codes match the Excel export (e.g. NPD-R800). A recipe's lines may point
    at raw ingredients (Product) or at other Recipes (sub-recipes), which is
    how multi-stage bakery formulas (starter -> ferment -> dough -> finished
    loaf) are modelled.
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
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.name} ({self.code})"

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

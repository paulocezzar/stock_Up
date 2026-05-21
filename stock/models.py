from decimal import Decimal
from django.db import models
from django.db.models import F, ExpressionWrapper, DecimalField

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
    department = models.ForeignKey("Department", related_name="products",
                                   on_delete=models.CASCADE, null=True, blank=True)
    code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=8, choices=UNIT_CHOICES, default="g")
    minimum = models.DecimalField("minimum (par level)", max_digits=10, decimal_places=2, default=0)
    weekly_usage = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})" if self.code else self.name

    @property
    def cheapest_price(self):
        return self.prices.annotate(p1000=PER_1000).order_by("p1000").first()

    @property
    def latest_line(self):
        return (StockLine.objects.filter(product=self, current__isnull=False)
                .select_related("stocktake").order_by("-stocktake__date", "-id").first())

    def history(self, limit=8):
        return list(StockLine.objects.filter(product=self, current__isnull=False)
                    .select_related("stocktake").order_by("-stocktake__date")[:limit])


class SupplierPrice(models.Model):
    product = models.ForeignKey(Product, related_name="prices", on_delete=models.CASCADE)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE)
    pack_weight = models.DecimalField(max_digits=12, decimal_places=2)
    pack_price = models.DecimalField(max_digits=12, decimal_places=2)
    effective_date = models.DateField(auto_now=True)

    class Meta:
        ordering = ["product", "pack_price"]
        unique_together = ("product", "supplier")

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

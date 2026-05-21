from django.contrib import admin
from .models import Department, Supplier, Product, SupplierPrice, Stocktake, StockLine


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name",)
    filter_horizontal = ("members",)


class SupplierPriceInline(admin.TabularInline):
    model = SupplierPrice
    extra = 1
    readonly_fields = ("per_1000",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "department", "unit", "minimum")
    list_filter = ("department",)
    search_fields = ("code", "name")
    inlines = [SupplierPriceInline]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


class StockLineInline(admin.TabularInline):
    model = StockLine
    extra = 0
    autocomplete_fields = ("product",)


@admin.register(Stocktake)
class StocktakeAdmin(admin.ModelAdmin):
    list_display = ("__str__", "department", "date", "completed_by")
    list_filter = ("department",)
    inlines = [StockLineInline]


@admin.register(SupplierPrice)
class SupplierPriceAdmin(admin.ModelAdmin):
    list_display = ("product", "supplier", "pack_weight", "pack_price", "per_1000")
    search_fields = ("product__name", "supplier__name")
    list_filter = ("supplier",)

from django.contrib import admin
from .models import Supplier, Product, SupplierPrice, Stocktake, StockLine


class SupplierPriceInline(admin.TabularInline):
    model = SupplierPrice
    extra = 1
    readonly_fields = ("per_1000",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "unit", "minimum", "weekly_usage")
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
    list_display = ("date", "completed_by", "counted", "note")
    inlines = [StockLineInline]


@admin.register(SupplierPrice)
class SupplierPriceAdmin(admin.ModelAdmin):
    list_display = ("product", "supplier", "pack_weight", "pack_price", "per_1000")
    search_fields = ("product__name", "supplier__name")
    list_filter = ("supplier",)

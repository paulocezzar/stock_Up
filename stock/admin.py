from django.contrib import admin
from .models import (
    Department, Supplier, Product, SupplierPrice, Stocktake, StockLine,
    SuppressedRecipe, Customer,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "customer_type", "is_internal",
                    "department", "active")
    list_filter = ("customer_type", "is_internal", "department", "active")
    list_editable = ("is_internal",)
    search_fields = ("name", "location", "ordered_by")


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


@admin.register(SuppressedRecipe)
class SuppressedRecipeAdmin(admin.ModelAdmin):
    """Recipe codes the UI has deleted. Delete a row here to un-suppress
    (the next bulk re-import will then re-create the recipe)."""
    list_display = ("code", "reason", "suppressed_at")
    search_fields = ("code", "reason")

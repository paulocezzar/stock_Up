"""Ingredient-only costing helpers for commercial margin reporting.

This deliberately stops short of full product costing. Ingredient costs are
well-structured today: SaleProduct links resolve to a Recipe, recipes explode
to raw Product weights, and Products have latest-cheapest SupplierPrice rows.
Packaging quantities are still raw exporter strings, so packaging is surfaced
as an exclusion instead of being folded into margin silently.
"""
from datetime import timedelta
from decimal import Decimal

from .models import OrderLine, SaleProductCycleError


ZERO = Decimal("0")


def _q2(value):
    return (value or ZERO).quantize(Decimal("0.01"))


def _q1(value):
    return (value or ZERO).quantize(Decimal("0.1"))


def ingredient_unit_cost(product, cache=None):
    """Return cost per recipe quantity unit for a raw ingredient Product.

    Recipes store ingredient quantities in the same base magnitude used by the
    supplier pack weight for gram/ml products. Count-based products cannot be
    honestly costed from a ``weight_g`` recipe quantity, so they return a
    blocker.
    """
    if cache is not None and product.pk in cache:
        return cache[product.pk]

    if product.unit not in ("g", "ml"):
        result = (None, {
            "code": "unsupported_unit",
            "product_id": product.pk,
            "product": product.name,
            "unit": product.unit,
        })
        if cache is not None:
            cache[product.pk] = result
        return result

    price = product.cheapest_price
    if price is None or not price.pack_weight:
        result = (None, {
            "code": "missing_supplier_price",
            "product_id": product.pk,
            "product": product.name,
            "unit": product.unit,
        })
        if cache is not None:
            cache[product.pk] = result
        return result

    result = (price.pack_price / price.pack_weight, None)
    if cache is not None:
        cache[product.pk] = result
    return result


def recipe_batch_ingredient_cost(recipe, cache=None, ingredient_cache=None):
    """Cost one full finished batch of ``recipe`` from raw ingredients."""
    if cache is not None and recipe.pk in cache:
        return cache[recipe.pk]

    total = ZERO
    blockers = []
    for row in recipe.exploded_ingredients():
        ingredient = row["ingredient"]
        unit_cost, blocker = ingredient_unit_cost(ingredient, ingredient_cache)
        if blocker:
            blockers.append(blocker)
            continue
        total += row["weight_g"] * unit_cost

    packaging_count = len(recipe.all_packaging())
    if packaging_count:
        blockers.append({
            "code": "packaging_excluded",
            "recipe_id": recipe.pk,
            "recipe": recipe.name,
            "count": packaging_count,
        })

    result = {
        "recipe": recipe,
        "cost": _q2(total),
        "blockers": blockers,
    }
    if cache is not None:
        cache[recipe.pk] = result
    return result


def sale_product_ingredient_cost(
        sale_product, cache=None, recipe_cache=None, ingredient_cache=None):
    """Ingredient cost for one sold unit/pack represented by SaleProduct."""
    if cache is not None and sale_product.pk in cache:
        return cache[sale_product.pk]

    try:
        recipe, total_quantity, unit = sale_product.resolved_recipe_consumption()
    except SaleProductCycleError as exc:
        result = {
            "cost": ZERO,
            "recipe": None,
            "blockers": [{
                "code": "sale_product_cycle",
                "sale_product_id": sale_product.pk,
                "sale_product": sale_product.name,
                "detail": str(exc),
            }],
        }
        if cache is not None:
            cache[sale_product.pk] = result
        return result

    if recipe is None:
        result = {
            "cost": ZERO,
            "recipe": None,
            "blockers": [{
                "code": "unresolved_sale_product",
                "sale_product_id": sale_product.pk,
                "sale_product": sale_product.name,
            }],
        }
        if cache is not None:
            cache[sale_product.pk] = result
        return result

    batch = recipe_batch_ingredient_cost(
        recipe, cache=recipe_cache, ingredient_cache=ingredient_cache)
    finished_weight = recipe.finished_weight_g or recipe.deposit_weight_g
    if unit == sale_product.COUNT:
        multiplier = total_quantity
    elif unit == sale_product.WEIGHT_KG:
        if not finished_weight:
            result = {
                "cost": ZERO,
                "recipe": recipe,
                "blockers": [{
                    "code": "missing_finished_weight",
                    "recipe_id": recipe.pk,
                    "recipe": recipe.name,
                }],
            }
            if cache is not None:
                cache[sale_product.pk] = result
            return result
        multiplier = (total_quantity * Decimal("1000")) / finished_weight
    elif unit == sale_product.WEIGHT_G:
        if not finished_weight:
            result = {
                "cost": ZERO,
                "recipe": recipe,
                "blockers": [{
                    "code": "missing_finished_weight",
                    "recipe_id": recipe.pk,
                    "recipe": recipe.name,
                }],
            }
            if cache is not None:
                cache[sale_product.pk] = result
            return result
        multiplier = total_quantity / finished_weight
    else:
        result = {
            "cost": ZERO,
            "recipe": recipe,
            "blockers": [{
                "code": "unsupported_sale_unit",
                "sale_product_id": sale_product.pk,
                "sale_product": sale_product.name,
                "unit": unit,
            }],
        }
        if cache is not None:
            cache[sale_product.pk] = result
        return result

    result = {
        "cost": _q2(batch["cost"] * multiplier),
        "recipe": recipe,
        "blockers": batch["blockers"],
    }
    if cache is not None:
        cache[sale_product.pk] = result
    return result


def order_line_ingredient_cost(
        line, sale_product_cache=None, recipe_cache=None,
        ingredient_cache=None):
    """Ingredient cost estimate for one OrderLine."""
    revenue = line.line_value or ZERO
    if line.sale_product_id is None:
        return {
            "revenue": _q2(revenue),
            "cost": ZERO,
            "blockers": [{
                "code": "missing_sale_product",
                "line_id": line.pk,
                "product": line.display_name,
            }],
        }

    one = sale_product_ingredient_cost(
        line.sale_product,
        cache=sale_product_cache,
        recipe_cache=recipe_cache,
        ingredient_cache=ingredient_cache,
    )
    qty = line.qty_ordered or ZERO
    if one["blockers"]:
        return {
            "revenue": _q2(revenue),
            "cost": ZERO,
            "blockers": one["blockers"],
        }
    return {
        "revenue": _q2(revenue),
        "cost": _q2(one["cost"] * qty),
        "blockers": one["blockers"],
    }


def _unique_blocker_key(blocker):
    return (
        blocker.get("code"),
        blocker.get("product_id"),
        blocker.get("recipe_id"),
        blocker.get("sale_product_id"),
        blocker.get("line_id"),
    )


def range_margin_summary(dept, start_wc, end_wc):
    """Ingredient-only margin summary for an external-order week range."""
    end = end_wc + timedelta(days=6)
    lines = (OrderLine.objects
             .filter(order__department=dept,
                     order__order_date__range=(start_wc, end),
                     order__customer__is_internal=False)
             .select_related(
                 "sale_product__link_recipe",
                 "sale_product__link_product",
                 "order__customer",
             ))

    revenue = ZERO
    cost = ZERO
    costed_revenue = ZERO
    line_count = 0
    costed_lines = 0
    blockers = {}
    blocker_counts = {}
    sale_product_cache = {}
    recipe_cache = {}
    ingredient_cache = {}

    for line in lines:
        line_count += 1
        result = order_line_ingredient_cost(
            line,
            sale_product_cache=sale_product_cache,
            recipe_cache=recipe_cache,
            ingredient_cache=ingredient_cache,
        )
        revenue += result["revenue"]
        if result["blockers"]:
            for blocker in result["blockers"]:
                key = _unique_blocker_key(blocker)
                blockers.setdefault(key, blocker)
                blocker_counts[blocker["code"]] = (
                    blocker_counts.get(blocker["code"], 0) + 1)
            continue
        cost += result["cost"]
        costed_revenue += result["revenue"]
        costed_lines += 1

    gross_profit = costed_revenue - cost
    margin_pct = (
        _q1(gross_profit / costed_revenue * Decimal("100"))
        if costed_revenue else None
    )
    coverage_pct = (
        _q1(Decimal(costed_lines) / Decimal(line_count) * Decimal("100"))
        if line_count else Decimal("0.0")
    )

    return {
        "basis": "ingredient_only",
        "revenue": _q2(revenue),
        "costed_revenue": _q2(costed_revenue),
        "estimated_ingredient_cost": _q2(cost),
        "gross_profit": _q2(gross_profit),
        "gross_margin_pct": margin_pct,
        "line_count": line_count,
        "costed_line_count": costed_lines,
        "coverage_pct": coverage_pct,
        "blocker_counts": blocker_counts,
        "blockers": list(blockers.values())[:20],
    }

"""Ingredient-only costing helpers for commercial margin reporting.

This deliberately stops short of full product costing. Ingredient costs are
well-structured today: SaleProduct links resolve to a Recipe, recipes explode
to raw Product weights, and Products have latest-cheapest SupplierPrice rows.
Packaging quantities are still raw exporter strings, so packaging is surfaced
as an exclusion instead of being folded into margin silently.
"""
from datetime import timedelta
from decimal import Decimal

from .models import (
    OrderLine, Recipe, RecipeLine, RecipePackaging, SaleProduct,
    SaleProductCycleError,
)


ZERO = Decimal("0")


def _q2(value):
    return (value or ZERO).quantize(Decimal("0.01"))


def _q1(value):
    return (value or ZERO).quantize(Decimal("0.1"))


def _build_range_context(dept):
    """Load the catalogue data margin costing needs once per API request."""
    recipes = {
        r.pk: r for r in Recipe.objects.filter(department=dept).only(
            "id", "name", "finished_weight_g", "deposit_weight_g")
    }
    lines_by_recipe = {}
    recipe_lines = (
        RecipeLine.objects
        .filter(recipe__department=dept)
        .select_related("ingredient", "sub_recipe")
        .prefetch_related("ingredient__prices")
    )
    for line in recipe_lines:
        lines_by_recipe.setdefault(line.recipe_id, []).append(line)
        if line.sub_recipe_id and line.sub_recipe_id not in recipes:
            recipes[line.sub_recipe_id] = line.sub_recipe

    packaging_by_recipe = {}
    for recipe_id, packaging_id in (
            RecipePackaging.objects
            .filter(recipe__department=dept)
            .values_list("recipe_id", "packaging_id")):
        packaging_by_recipe.setdefault(recipe_id, set()).add(packaging_id)

    sale_products = {
        sp.pk: sp for sp in SaleProduct.objects.filter(department=dept)
        .select_related("link_recipe")
    }

    return {
        "recipes": recipes,
        "lines_by_recipe": lines_by_recipe,
        "packaging_by_recipe": packaging_by_recipe,
        "sale_products": sale_products,
        "recipe_cache": {},
        "sale_product_cache": {},
        "ingredient_cache": {},
    }


def _explode_recipe_context(context, recipe_id, multiplier, seen):
    if recipe_id in seen:
        return {}, set()
    seen = seen | {recipe_id}
    totals = {}
    packaging_ids = set(context["packaging_by_recipe"].get(recipe_id, set()))

    for line in context["lines_by_recipe"].get(recipe_id, []):
        if line.ingredient_id:
            product = line.ingredient
            weight = line.weight_g * multiplier
            current = totals.get(line.ingredient_id)
            if current:
                current["weight_g"] += weight
            else:
                totals[line.ingredient_id] = {
                    "ingredient": product,
                    "weight_g": weight,
                }
        elif line.sub_recipe_id:
            sub = context["recipes"].get(line.sub_recipe_id) or line.sub_recipe
            ref = sub.finished_weight_g or sub.deposit_weight_g
            if not ref or ref == 0:
                ref = sum(
                    (ln.weight_g for ln in context["lines_by_recipe"].get(
                        line.sub_recipe_id, [])),
                    ZERO,
                ) or Decimal("1")
            sub_totals, sub_packaging = _explode_recipe_context(
                context, line.sub_recipe_id, multiplier * (line.weight_g / ref),
                seen)
            packaging_ids.update(sub_packaging)
            for ingredient_id, row in sub_totals.items():
                current = totals.get(ingredient_id)
                if current:
                    current["weight_g"] += row["weight_g"]
                else:
                    totals[ingredient_id] = row

    return totals, packaging_ids


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


def _recipe_batch_ingredient_cost_context(recipe, context):
    if recipe.pk in context["recipe_cache"]:
        return context["recipe_cache"][recipe.pk]

    totals, packaging_ids = _explode_recipe_context(
        context, recipe.pk, Decimal("1"), set())
    total = ZERO
    blockers = []
    for row in totals.values():
        ingredient = row["ingredient"]
        unit_cost, blocker = ingredient_unit_cost(
            ingredient, context["ingredient_cache"])
        if blocker:
            blockers.append(blocker)
            continue
        total += row["weight_g"] * unit_cost

    if packaging_ids:
        blockers.append({
            "code": "packaging_excluded",
            "recipe_id": recipe.pk,
            "recipe": recipe.name,
            "count": len(packaging_ids),
        })

    result = {
        "recipe": recipe,
        "cost": _q2(total),
        "blockers": blockers,
    }
    context["recipe_cache"][recipe.pk] = result
    return result


def _resolve_sale_product_context(sale_product, context, max_hops=32):
    seen = {sale_product.pk}
    current = context["sale_products"].get(sale_product.pk, sale_product)
    total = Decimal("1")
    effective_unit = None
    for _ in range(max_hops):
        qty = current.link_quantity if current.link_quantity is not None else Decimal("1")
        total *= qty
        unit = current.link_unit or SaleProduct.COUNT
        if effective_unit is None and unit != SaleProduct.COUNT:
            effective_unit = unit
        if current.link_recipe_id:
            if effective_unit is None:
                effective_unit = SaleProduct.COUNT
            recipe = context["recipes"].get(current.link_recipe_id)
            if recipe is None:
                recipe = current.link_recipe
            return recipe, total, effective_unit
        if current.link_product_id is None:
            return None, Decimal("0"), None
        if current.link_product_id in seen:
            raise SaleProductCycleError(
                f"SaleProduct chain cycles via {current.link_product_id}")
        seen.add(current.link_product_id)
        current = context["sale_products"].get(current.link_product_id)
        if current is None:
            return None, Decimal("0"), None
    raise SaleProductCycleError(
        f"SaleProduct chain longer than {max_hops} hops - refusing to resolve")


def _sale_product_ingredient_cost_context(sale_product, context):
    if sale_product.pk in context["sale_product_cache"]:
        return context["sale_product_cache"][sale_product.pk]

    try:
        recipe, total_quantity, unit = _resolve_sale_product_context(
            sale_product, context)
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
        context["sale_product_cache"][sale_product.pk] = result
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
        context["sale_product_cache"][sale_product.pk] = result
        return result

    batch = _recipe_batch_ingredient_cost_context(recipe, context)
    finished_weight = recipe.finished_weight_g or recipe.deposit_weight_g
    if unit == SaleProduct.COUNT:
        multiplier = total_quantity
    elif unit == SaleProduct.WEIGHT_KG:
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
            context["sale_product_cache"][sale_product.pk] = result
            return result
        multiplier = (total_quantity * Decimal("1000")) / finished_weight
    elif unit == SaleProduct.WEIGHT_G:
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
            context["sale_product_cache"][sale_product.pk] = result
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
        context["sale_product_cache"][sale_product.pk] = result
        return result

    result = {
        "cost": _q2(batch["cost"] * multiplier),
        "recipe": recipe,
        "blockers": batch["blockers"],
    }
    context["sale_product_cache"][sale_product.pk] = result
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
        ingredient_cache=None, context=None):
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

    if context is not None:
        one = _sale_product_ingredient_cost_context(line.sale_product, context)
    else:
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
    context = _build_range_context(dept)

    for line in lines:
        line_count += 1
        result = order_line_ingredient_cost(
            line,
            context=context,
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

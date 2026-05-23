import datetime
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Sum
from django.http import HttpResponseForbidden
from .models import Supplier, Product, SupplierPrice, Stocktake, StockLine, Department, Delivery, Batch, Adjustment, Recipe, RecipeLine, RecipeCycleError, Customer, SuppressedRecipe, SaleProduct
from .ai_extract import extract_lines, auto_match, ExtractError
from .recipe_import import (
    parse_recipe_workbook, parse_recipe_workbook_bulk,
    save_recipes, summarize_parse, summarize_parse_bulk,
    serialize_parsed, deserialize_parsed, RecipeParseError,
)


def _carry_over_value(dept, product_id, exclude_stocktake_id=None):
    """Most recent non-null current for this product from a prior stocktake in the dept."""
    qs = StockLine.objects.filter(
        stocktake__department=dept, product_id=product_id, current__isnull=False,
    )
    if exclude_stocktake_id is not None:
        qs = qs.exclude(stocktake_id=exclude_stocktake_id)
    line = qs.order_by("-stocktake__date", "-id").first()
    return line.current if line else None


def _dec(raw):
    raw = (raw or "").strip()
    if raw == "":
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _normalize_pack(input_unit, qty):
    """Map a user-facing pack unit to (stored_unit, stored_qty).

    Pack sizes are always stored in the base unit (g, ml or ea) so existing
    maths and the £/1000 comparison stay consistent. kg / L are convenience
    inputs that we multiply by 1000 and store as g / ml.
    """
    if input_unit == "kg":
        return "g", (qty * 1000 if qty is not None else None)
    if input_unit == "L":
        return "ml", (qty * 1000 if qty is not None else None)
    return input_unit, qty


def user_departments(user):
    if user.is_superuser:
        return Department.objects.all()
    return user.departments.all()


def current_department(request):
    """The department the user is currently working in (from session)."""
    depts = user_departments(request.user)
    dept_id = request.session.get("dept_id")
    if dept_id:
        d = depts.filter(pk=dept_id).first()
        if d:
            return d
    d = depts.first()
    if d:
        request.session["dept_id"] = d.pk
    return d


def _weather_label(code):
    if code is None:
        return "—"
    if code == 0:
        return "Clear sky"
    if code in (1, 2):
        return "Partly cloudy"
    if code == 3:
        return "Overcast"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle"
    if code in (61, 63, 65, 66, 67):
        return "Rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if code in (80, 81, 82):
        return "Showers"
    if code in (95, 96, 99):
        return "Thunderstorm"
    return "—"


def _weather_icon(code):
    if code is None:
        return "·"
    if code == 0:
        return "☼"
    if code in (1, 2):
        return "◐"
    if code == 3:
        return "●"
    if code in (45, 48):
        return "≋"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "‖"
    if code in (71, 73, 75, 77, 85, 86):
        return "✻"
    if code in (95, 96, 99):
        return "↯"
    return "·"


def _packs(d):
    """Render a Decimal pack count without trailing zeros (2.00 -> "2")."""
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


def _stock_tasks_for_home(dept, today):
    """Build the actionable tasks shown on the Home Urgent Tasks card from
    stock data. Returns a list of {label, count, url} dicts.

    Structured so other sources (manual user-added tasks, recipe / production
    prompts, etc.) can extend the same list later. To plug in a new source,
    write another helper that returns the same shape and append its result
    in home().
    """
    tasks = []
    if dept is None:
        return tasks

    below = 0
    low_cover = 0
    for p in dept.products.prefetch_related("prices__supplier"):
        line = p.latest_line
        cur = line.current if line else None
        if cur is None:
            continue
        if cur < p.minimum:
            below += 1
        else:
            cover = p.days_of_cover(cur)
            if cover is not None and cover < 14:
                low_cover += 1

    if below:
        tasks.append({"label": "Ordering", "count": below, "url": "/reorder/"})

    expiring = Batch.objects.filter(
        delivery__department=dept,
        use_by__isnull=False,
        use_by__gte=today,
        use_by__lte=today + datetime.timedelta(days=7),
        qty_remaining__gt=0,
    ).count()
    if expiring:
        tasks.append({"label": "Use expiring stock", "count": expiring,
                      "url": "/deliveries/"})

    last_st = dept.stocktakes.first()
    needs_count = False
    if last_st is None and dept.products.exists():
        needs_count = True
    elif last_st is not None and (today - last_st.date).days > 7:
        needs_count = True
    if needs_count:
        tasks.append({"label": "Stocktake due", "count": None,
                      "url": "/stocktakes/"})

    if low_cover:
        tasks.append({"label": "Running low", "count": low_cover, "url": "/reorder/"})

    return tasks


def fetch_weather(lat=51.1485, lon=-2.7137, timeout=3.0):
    """Open-Meteo current weather for Glastonbury. No API key required.

    Returns a dict with temperature, condition, icon and the API's
    timestamp, or None on any failure (timeout, parse error, missing
    fields). Tests patch this function on stock.views to avoid hitting
    the network.
    """
    import json
    import urllib.request
    url = (f"https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat}&longitude={lon}&current_weather=true")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        cw = data.get("current_weather") or {}
        code = cw.get("weathercode")
        temp = cw.get("temperature")
        if temp is None:
            return None
        return {
            "temperature": temp,
            "code": code,
            "condition": _weather_label(code),
            "icon": _weather_icon(code),
            "time": cw.get("time"),
        }
    except Exception:
        return None


@login_required
def home(request):
    """Dashboard-style landing page — the post-login destination.

    Top row: welcome + weather + urgent tasks cards. Below: per-ingredient
    stock alerts table. Weather is fetched live via Open-Meteo (no API key)
    and falls back gracefully when the request fails.
    """
    dept = current_department(request)
    today = datetime.date.today()
    hour = datetime.datetime.now().hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    stock_alerts = []
    if dept is not None:
        for p in dept.products.prefetch_related("prices__supplier"):
            line = p.latest_line
            cur = line.current if line else None
            if cur is None:
                continue
            if cur < p.minimum:
                stock_alerts.append({
                    "ingredient": p,
                    "alert": "Below minimum",
                    "detail": f"{_packs(cur)} / {_packs(p.minimum)} packs",
                    "href": "/reorder/",
                    "kind": "below_min",
                })
            else:
                cover = p.days_of_cover(cur)
                if cover is not None and cover < 14:
                    stock_alerts.append({
                        "ingredient": p,
                        "alert": "Low days of cover",
                        "detail": f"~{cover} days",
                        "href": f"/products/{p.pk}/",
                        "kind": "low_cover",
                    })

        expiring_batches = (Batch.objects
            .filter(delivery__department=dept,
                    use_by__isnull=False,
                    use_by__gte=today,
                    use_by__lte=today + datetime.timedelta(days=7),
                    qty_remaining__gt=0)
            .select_related("product", "delivery"))
        for b in expiring_batches:
            stock_alerts.append({
                "ingredient": b.product,
                "alert": "Expires soon",
                "detail": f"use-by {b.use_by:%d %b}",
                "href": f"/deliveries/{b.delivery.pk}/",
                "kind": "expiring",
            })

    # Urgent tasks list. Single list of {label, count, url} dicts; new
    # sources (e.g. manual user-added tasks) can be appended here later.
    urgent_tasks = _stock_tasks_for_home(dept, today)

    try:
        weather = fetch_weather()
    except Exception:
        weather = None
    return render(request, "stock/home.html", {
        "greeting": greeting,
        "today": today,
        "urgent_tasks": urgent_tasks,
        "urgent_count": len(urgent_tasks),
        "stock_alerts": stock_alerts,
        "has_dept": dept is not None,
        "weather": weather,
    })


@login_required
def stock_home(request):
    """Stock section landing — links to the existing stock sub-pages."""
    return render(request, "stock/section_stock.html", {})


_COMING_SOON = {
    "production": ("Production", "Daily production plans, batch schedules and outputs."),
    "rota": ("Rota", "Staff schedules, shift assignments and time-off requests."),
    "notes": ("Notes", "Shared notes for the team — handover, reminders, ideas."),
}


def _placeholder(request, key):
    title, blurb = _COMING_SOON[key]
    return render(request, "stock/coming_soon.html",
                  {"title": title, "blurb": blurb, "section": key})


# ---- recipes (per department) ----
def _recipe_tree(recipe, depth=0, seen=None):
    """Build a nested {recipe, depth, lines:[{line, subtree?, cycle?}]} dict.

    `seen` tracks recipe IDs on the current path so a cycle in the data
    (which the import refuses, but might exist via admin edits) is
    represented as a leaf with cycle=True instead of recursing infinitely.
    """
    if seen is None:
        seen = set()
    node = {"recipe": recipe, "depth": depth, "lines": [], "cycle": False}
    seen = seen | {recipe.pk}
    for line in (recipe.lines.select_related("ingredient", "sub_recipe")
                 .order_by("ordering", "id")):
        entry = {"line": line, "subtree": None, "cycle": False}
        if line.sub_recipe_id:
            if line.sub_recipe_id in seen:
                entry["cycle"] = True
            else:
                entry["subtree"] = _recipe_tree(line.sub_recipe, depth + 1, seen)
        node["lines"].append(entry)
    return node


def _safe_json(obj):
    """Render a Python obj as JSON safe to embed in an HTML attribute.

    `</script>` and other sensitive sequences are escaped via the standard
    Django json_script trick; we just produce the raw JSON here and the
    template emits it via the ``json_script`` filter or |escape, both of
    which preserve correctness.
    """
    import json
    return json.dumps(obj, separators=(",", ":"))


def _by_product_forest(recipes):
    """Build the top-level → sub-recipe forest for the by-product view.

    Roots are recipes the bakery sells (``sold_as_product=True``). A recipe
    that's BOTH sold and used as a component appears as a root AND nested
    under each parent that uses it, so the tree shows both "things we sell"
    and "what each is built from."

    Each node is ``{recipe, depth, children, cycle, active_parent_ids,
    roots_using}``. ``active_parent_ids`` is the list of recipe pks in the
    active set that reference this node as a sub_recipe — used by the
    tree's client-side auto-tick logic to decide whether a component is
    "safe" to cascade-tick when its product is selected (safe iff every
    active parent is in the current selection). ``roots_using`` is the
    list of root product pks whose sub-trees transitively reach this
    recipe — used for the user-friendly "also used by: X, Y" labels on
    shared components.

    The recursion path's ``seen`` set prevents an admin-edited cycle from
    rendering forever; a back-edge becomes a leaf with cycle=True.
    """
    by_id = {r.pk: r for r in recipes}
    # parent_id → ordered, deduped list of sub_recipe ids
    children_of = {pk: [] for pk in by_id}
    # sub_id → set of active parent ids (those that reference it)
    parents_of = {pk: set() for pk in by_id}
    for r in recipes:
        seen_for_this = set()
        for line in sorted(r.lines.all(), key=lambda l: (l.ordering, l.id)):
            if not line.sub_recipe_id or line.sub_recipe_id not in by_id:
                continue
            if line.sub_recipe_id in seen_for_this:
                continue
            seen_for_this.add(line.sub_recipe_id)
            children_of[r.pk].append(line.sub_recipe_id)
            parents_of[line.sub_recipe_id].add(r.pk)

    roots = [r for r in recipes if r.sold_as_product]
    roots.sort(key=lambda r: r.code)

    # Per-recipe set of root product ids whose sub-tree reaches it.
    # DFS from each root, accumulating root pk into roots_using[child].
    roots_using = {pk: set() for pk in by_id}
    for root in roots:
        stack = [root.pk]
        visited = set()
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            roots_using[cur].add(root.pk)
            for child_id in children_of.get(cur, []):
                if child_id not in visited:
                    stack.append(child_id)

    def build(rid, depth, path):
        recipe = by_id[rid]
        node = {"recipe": recipe, "depth": depth,
                "children": [], "cycle": False,
                "active_parent_ids": sorted(parents_of[rid]),
                "roots_using": sorted(roots_using[rid])}
        if rid in path:
            node["cycle"] = True
            return node
        new_path = path | {rid}
        for child_id in children_of.get(rid, []):
            node["children"].append(build(child_id, depth + 1, new_path))
        return node

    return [build(r.pk, 0, set()) for r in roots]


@login_required
def recipes_home(request):
    """Three sibling views over the same recipe set:

    * ``by_product`` (default) — structural tree of active recipes.
    * ``flat`` — flat list of active recipes with bulk-archive actions.
    * ``archived`` — list of archived recipes with restore actions.

    The archive flag is honoured at the query level so a re-import
    that touches an archived recipe's basics doesn't accidentally
    expose it in the main views.
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    raw = request.GET.get("view")
    if raw == "archived":
        view_mode = "archived"
    elif raw == "flat":
        view_mode = "flat"
    else:
        view_mode = "by_product"

    base = (Recipe.objects.filter(department=dept)
            .annotate(n_lines=Count("lines"))
            .prefetch_related("lines__sub_recipe", "used_in_lines__recipe")
            .order_by("code"))
    if view_mode == "archived":
        recipes = list(base.filter(archived=True))
    else:
        recipes = list(base.filter(archived=False))

    # Count archived recipes regardless of current view so the tab can
    # surface a count badge.
    n_archived = Recipe.objects.filter(department=dept, archived=True).count()

    context = {
        "n_recipes": len(recipes),
        "n_archived": n_archived,
        "view_mode": view_mode,
    }

    if view_mode == "by_product":
        context["forest"] = _by_product_forest(recipes)
        # Map of pk → {code, name} so the tree's JS can render "also used
        # by: X, Y" labels and shared-component warnings without scraping
        # the DOM. Lightweight (one entry per active recipe).
        context["tree_recipe_meta_json"] = _safe_json(
            {r.pk: {"code": r.code, "name": r.name} for r in recipes})
    elif view_mode == "archived":
        # The archived view uses the same flat-row shape as the
        # "All recipes" tab so the existing checkbox / select-all UI
        # can be reused unchanged; the only difference is the action
        # button (Restore vs Archive) and the empty-state copy.
        rows = []
        for r in recipes:
            # Parents shown here are ALL parents (active or not) — the
            # operator may want to see that an archived recipe still
            # had references when it was hidden.
            seen = set()
            parents = []
            for line in r.used_in_lines.all():
                p = line.recipe
                if p.pk in seen:
                    continue
                seen.add(p.pk)
                parents.append(p)
            parents.sort(key=lambda p: p.code)
            rows.append({"r": r, "parents": parents})
        context["rows"] = rows
    else:  # flat
        rows = []
        for r in recipes:
            # Only active parents are surfaced on the flat view — an
            # archived parent isn't structurally meaningful to a
            # currently-shown recipe.
            seen = set()
            parents = []
            for line in r.used_in_lines.all():
                p = line.recipe
                if p.pk in seen or p.archived:
                    continue
                seen.add(p.pk)
                parents.append(p)
            parents.sort(key=lambda p: p.code)
            rows.append({"r": r, "parents": parents})
        context["rows"] = rows

    return render(request, "stock/recipes.html", context)


@require_POST
@login_required
def recipe_set_sold(request, pk):
    """Toggle whether a recipe is sold as a standalone product.

    Sets ``is_sold_manual=True`` so the next bulk
    ``recompute_all_sold_defaults()`` (e.g. post-import) won't overwrite
    the operator's choice. Accepts "true" / "false" in POST["sold"].
    """
    recipe = get_object_or_404(Recipe, pk=pk)
    if recipe.department and not recipe.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    raw = (request.POST.get("sold") or "").strip().lower()
    if raw not in ("true", "false"):
        messages.error(request, "Pick a valid sold state.")
        return redirect("recipes")
    recipe.sold_as_product = (raw == "true")
    recipe.is_sold_manual = True
    recipe.save(update_fields=["sold_as_product", "is_sold_manual"])
    label = "sold as a product" if recipe.sold_as_product else "not sold standalone"
    messages.success(request, f"Marked {recipe.code} as {label}.")
    return redirect("recipes")


@login_required
def recipe_upload(request):
    """Step 1 of import: pick a workbook; parse all sheets and stash for preview.

    The bulk parser handles both single-recipe and multi-recipe workbooks:
    a one-sheet upload comes back as one parsed recipe-tree, a 93-sheet
    upload comes back as everything across the workbook. Sheets that
    don't parse become failures (skipped, surfaced in the preview) so a
    single bad sheet can't abort the rest.
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload:
            messages.error(request, "Pick a recipe .xlsx file to upload.")
            return redirect("recipe_upload")
        if upload.size > 20 * 1024 * 1024:
            messages.error(request, "That file is over 20 MB.")
            return redirect("recipe_upload")
        try:
            parsed, failures, sheets_processed = parse_recipe_workbook_bulk(upload)
        except Exception as e:
            messages.error(request, f"Could not open the workbook: {e}")
            return redirect("recipe_upload")
        if not parsed:
            # Show the failures so the operator knows why nothing came back.
            joined = "; ".join(f"{t}: {r}" for t, r in failures[:3])
            messages.error(
                request,
                "No recipes parsed from any sheet."
                + (f" First failure(s): {joined}" if failures else ""))
            return redirect("recipe_upload")
        request.session["pending_recipe_import"] = serialize_parsed(parsed)
        request.session["pending_recipe_failures"] = failures
        request.session["pending_recipe_sheets"] = sheets_processed
        return redirect("recipe_upload_preview")
    return render(request, "stock/recipe_upload.html", {})


@login_required
def recipe_upload_preview(request):
    """Step 2: show the parsed summary (per-recipe + per-sheet); POST to commit."""
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    raw = request.session.get("pending_recipe_import")
    if not raw:
        messages.info(request, "Upload a recipe workbook first.")
        return redirect("recipe_upload")
    parsed = deserialize_parsed(raw)
    failures = request.session.get("pending_recipe_failures") or []
    sheets_processed = request.session.get("pending_recipe_sheets") or 1

    if request.method == "POST":
        try:
            stats = save_recipes(parsed, dept)
        except RecipeCycleError as e:
            messages.error(request, f"Refused to save: {e}")
            return redirect("recipe_upload_preview")
        request.session.pop("pending_recipe_import", None)
        request.session.pop("pending_recipe_failures", None)
        request.session.pop("pending_recipe_sheets", None)
        n_unique = len(stats["created"]) + len(stats["updated"])
        # Multi-sheet workbooks (each sheet a separate top-level recipe) land
        # on the recipes list — there's no single "main" to feature. A single
        # sheet, even one that nests several sub-recipes, still lands on its
        # main's detail page (preserves the per-recipe upload UX).
        if sheets_processed > 1:
            msg = (f"Imported {n_unique} recipe(s) across "
                   f"{sheets_processed} sheet(s) — "
                   f"{len(stats['created'])} created, "
                   f"{len(stats['updated'])} updated.")
            if failures:
                msg += f" {len(failures)} sheet(s) failed."
            if stats["stub_products"]:
                msg += f" {len(stats['stub_products'])} unknown ingredient(s) stubbed."
            messages.success(request, msg)
            return redirect("recipes")
        # Single-sheet upload: land on the main recipe's detail page.
        main = parsed[0]
        msg = (f"Imported {main['code']} ({main['name']}): "
               f"{len(stats['created'])} created, {len(stats['updated'])} updated.")
        if stats["stub_products"]:
            msg += f" {len(stats['stub_products'])} unknown ingredient(s) stubbed."
        messages.success(request, msg)
        main_recipe = Recipe.objects.get(code=main["code"])
        return redirect("recipe_detail", pk=main_recipe.pk)

    summary = summarize_parse_bulk(parsed, failures, sheets_processed)
    return render(request, "stock/recipe_upload_preview.html", {
        "parsed": parsed,
        "summary": summary,
    })


@login_required
def recipe_detail(request, pk):
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    recipe = get_object_or_404(Recipe, pk=pk)
    if recipe.department and not recipe.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    # Two views: the nested structure (default) and a flat per-batch
    # ingredient list (the same explode-and-sum used by production later).
    view_mode = "flat" if request.GET.get("view") == "flat" else "structure"
    context = {
        "recipe": recipe,
        "view_mode": view_mode,
    }
    if view_mode == "flat":
        context["flat_ingredients"] = recipe.exploded_ingredients()
    else:
        context["tree"] = _recipe_tree(recipe)
    context["parents"] = list(recipe.parents())
    # Packaging linked by this recipe OR any of its sub-recipes — for a
    # sold product the union is what the bakery actually needs.
    context["packaging_items"] = recipe.all_packaging()
    return render(request, "stock/recipe_detail.html", context)


@login_required
def recipe_delete(request, pk):
    """Permanent (hard) delete escape hatch.

    Archive is the prominent default everywhere; hard-delete is the
    deliberate, friction-ful exception accessible only from the recipe
    detail page. The form on the confirmation template hides its
    submit button behind a "I understand this is permanent" checkbox
    so a stray click can't trigger it, and the view requires both the
    checkbox AND the typed-back recipe code before committing.

    On commit:
      * the recipe's own RecipeLines disappear via CASCADE;
      * RecipeLines in OTHER recipes that referenced this one as a
        sub_recipe are removed first (RecipeLine.sub_recipe is PROTECT);
      * a ``SuppressedRecipe`` row records the code so the bulk
        re-import on the next deploy doesn't silently resurrect it.

    Department-scoped, login-gated. Un-suppression is a one-row
    delete in the Django admin.
    """
    recipe = get_object_or_404(Recipe, pk=pk)
    if recipe.department and not recipe.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    parents = list(recipe.parents())
    error = None
    if request.method == "POST":
        acknowledge = request.POST.get("acknowledge") == "on"
        typed = (request.POST.get("confirm_code") or "").strip().upper()
        if not acknowledge:
            error = "Tick the acknowledgement box to confirm permanent deletion."
        elif typed != recipe.code.upper():
            error = (f"Type the recipe code exactly ({recipe.code}) "
                     "to confirm permanent deletion.")
        else:
            code = recipe.code
            name = recipe.name
            # Drop dangling sub_recipe references from parent recipes first —
            # RecipeLine.sub_recipe is on_delete=PROTECT.
            RecipeLine.objects.filter(sub_recipe=recipe).delete()
            recipe.delete()
            SuppressedRecipe.objects.update_or_create(
                code=code,
                defaults={"reason": f"Hard-deleted via UI: {name}"[:200]},
            )
            Recipe.recompute_all_sold_defaults()
            msg = f"Permanently deleted recipe {code}."
            if parents:
                msg += (f" {len(parents)} parent recipe(s) lost a sub-recipe "
                        f"reference: {', '.join(p.code for p in parents)}.")
            msg += " The next re-import will skip this code."
            messages.success(request, msg)
            return redirect("recipes")
    return render(request, "stock/recipe_delete_confirm.html", {
        "recipe": recipe,
        "parents": parents,
        "error": error,
    })


@require_POST
@login_required
def recipe_archive(request, pk):
    """Hide a recipe by setting ``archived=True`` (reversible).

    The row stays in the database; its lines and packaging links are
    kept; only the main views filter it out. Restoring is a one-field
    flip via ``recipe_restore``. The deploy-time re-import refreshes
    an archived recipe's basics but never un-archives it.
    """
    recipe = get_object_or_404(Recipe, pk=pk)
    if recipe.department and not recipe.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    if not recipe.archived:
        recipe.archived = True
        recipe.archived_at = timezone.now()
        recipe.save(update_fields=["archived", "archived_at"])
    msg = f"Archived recipe {recipe.code}."
    active_parents = [p for p in recipe.parents() if not p.archived]
    if active_parents:
        msg += (f" Still referenced by {len(active_parents)} active recipe(s): "
                f"{', '.join(p.code for p in active_parents)}.")
    msg += " Restore from the Archived tab."
    messages.success(request, msg)
    next_url = request.POST.get("next") or "recipes"
    return redirect(next_url if next_url.startswith("/") else "recipes")


@require_POST
@login_required
def recipe_restore(request, pk):
    """Un-archive a recipe (active again, visible in main views)."""
    recipe = get_object_or_404(Recipe, pk=pk)
    if recipe.department and not recipe.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    if recipe.archived:
        recipe.archived = False
        recipe.archived_at = None
        recipe.save(update_fields=["archived", "archived_at"])
    messages.success(request, f"Restored recipe {recipe.code}.")
    next_url = request.POST.get("next") or "recipes"
    return redirect(next_url if next_url.startswith("/") else "recipes")


def _bulk_recipe_selection(request, dept):
    """Shared parse + dept-filter for the bulk archive/restore/delete forms."""
    raw_ids = request.POST.getlist("recipe_ids")
    try:
        ids = {int(x) for x in raw_ids if x}
    except ValueError:
        ids = set()
    return list(Recipe.objects.filter(pk__in=ids, department=dept)
                .order_by("code"))


@require_POST
@login_required
def recipe_bulk_archive(request):
    """Bulk-archive recipes selected on the flat list page.

    Two-step POST mirrors the bulk-delete flow but without any of the
    hard-delete consequences: no row is removed, no FKs to chase, no
    SuppressedRecipe rows written. The confirmation page lists the
    selected recipes and, when any selected recipe is still
    referenced by an ACTIVE recipe outside the selection, surfaces a
    soft informational note (not a red warning — archiving is
    reversible and doesn't break anything).
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    selected = [r for r in _bulk_recipe_selection(request, dept)
                if not r.archived]
    if not selected:
        messages.error(request, "Pick at least one active recipe to archive.")
        return redirect("/recipes/?view=flat")
    selected_pks = {r.pk for r in selected}

    if request.POST.get("confirm") == "1":
        now = timezone.now()
        Recipe.objects.filter(pk__in=selected_pks).update(
            archived=True, archived_at=now)
        messages.success(
            request,
            f"Archived {len(selected)} recipe(s): "
            f"{', '.join(r.code for r in selected)}. "
            "Restore from the Archived tab.")
        return redirect("/recipes/?view=flat")

    # Informational note: which selected recipes are STILL referenced
    # by ACTIVE recipes outside the selection? Archiving doesn't break
    # them (the FK is preserved) but the operator may want to know.
    note_rows = []
    referencing = (Recipe.objects
                   .filter(lines__sub_recipe_id__in=selected_pks,
                           archived=False)
                   .exclude(pk__in=selected_pks)
                   .distinct())
    by_archived = {}
    for parent in referencing:
        for line in parent.lines.all():
            if line.sub_recipe_id in selected_pks:
                by_archived.setdefault(line.sub_recipe.code, set()).add(
                    parent.code)
    for code in sorted(by_archived):
        note_rows.append({"code": code,
                          "referenced_by": sorted(by_archived[code])})

    return render(request, "stock/recipe_bulk_archive_confirm.html", {
        "selected": selected,
        "note_rows": note_rows,
    })


@require_POST
@login_required
def recipe_bulk_restore(request):
    """Bulk-restore recipes from the archived list (single-step POST).

    Restore is harmless — the recipe just becomes visible again — so
    there's no separate confirmation page. A JS ``confirm()`` on the
    submit button is plenty.
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    selected = [r for r in _bulk_recipe_selection(request, dept)
                if r.archived]
    if not selected:
        messages.error(request, "Pick at least one archived recipe to restore.")
        return redirect("/recipes/?view=archived")
    selected_pks = {r.pk for r in selected}
    Recipe.objects.filter(pk__in=selected_pks).update(
        archived=False, archived_at=None)
    messages.success(
        request,
        f"Restored {len(selected)} recipe(s): "
        f"{', '.join(r.code for r in selected)}.")
    return redirect("/recipes/?view=flat")


@require_POST
@login_required
def recipe_bulk_delete(request):
    """Bulk-delete recipes selected on the flat list page.

    Two-step POST: the first submission carries ``recipe_ids`` from the
    checkboxes and renders a confirmation page that names exactly which
    recipes will be deleted, the count, and any external parents (parent
    recipes that reference a selected sub-recipe but aren't themselves
    selected). The second submission carries ``confirm=1`` and commits
    the deletion in a single transaction:

      * dangling ``RecipeLine.sub_recipe`` references in non-selected
        parents are removed first (the FK is on_delete=PROTECT, so the
        bare delete() would raise);
      * each recipe is deleted;
      * a ``SuppressedRecipe`` row is written per code so the next
        deploy's ``import_recipes_bulk`` won't bring them back.

    Department-scoped: only recipes in the operator's current department
    are deletable. Selected IDs from other departments are silently
    dropped from the candidate set, never surfaced.
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    raw_ids = request.POST.getlist("recipe_ids")
    try:
        ids = {int(x) for x in raw_ids if x}
    except ValueError:
        ids = set()
    selected = list(Recipe.objects.filter(pk__in=ids, department=dept)
                    .order_by("code"))
    if not selected:
        messages.error(request, "Pick at least one recipe to delete.")
        return redirect("/recipes/?view=flat")
    selected_pks = {r.pk for r in selected}

    error = None
    if request.POST.get("confirm") == "1":
        acknowledge = request.POST.get("acknowledge") == "on"
        typed = (request.POST.get("confirm_phrase") or "").strip().upper()
        if not acknowledge:
            error = "Tick the acknowledgement to confirm permanent bulk deletion."
        elif typed != "DELETE":
            error = ('Type "DELETE" (without the quotes) to confirm '
                     "permanent bulk deletion.")
        else:
            with transaction.atomic():
                # Drop EVERY RecipeLine that references a selected recipe
                # as its sub_recipe — including lines inside other
                # selected recipes. Django's deletion collector raises
                # ProtectedError the moment it sees any protected FK,
                # even if the referrer is in the same delete batch and
                # would be cascaded itself. Clearing them up front
                # sidesteps that.
                RecipeLine.objects.filter(sub_recipe_id__in=selected_pks).delete()
                codes = [r.code for r in selected]
                names = {r.code: r.name for r in selected}
                Recipe.objects.filter(pk__in=selected_pks).delete()
                for code in codes:
                    SuppressedRecipe.objects.update_or_create(
                        code=code,
                        defaults={"reason": f"Bulk delete: {names[code]}"[:200]},
                    )
            # Former parents may have lost their last child reference; sold
            # flags re-derive (manual overrides still respected).
            Recipe.recompute_all_sold_defaults()
            messages.success(
                request,
                f"Permanently deleted {len(selected)} recipe(s): "
                f"{', '.join(codes)}. "
                "The next re-import will skip these codes.")
            return redirect("/recipes/?view=flat")

    # Either first submission (no confirm) or confirm with a failed
    # acknowledgement gate — render the confirmation page. "External"
    # parents are parents that use a selected sub-recipe but aren't
    # themselves in the selection (so the operator sees the knock-on
    # damage before confirming). Parents inside the selection are being
    # deleted too, so they don't need their own warning row.
    external = (Recipe.objects
                .filter(lines__sub_recipe_id__in=selected_pks)
                .exclude(pk__in=selected_pks)
                .distinct()
                .order_by("code"))
    external_rows = []
    for parent in external:
        child_codes = sorted(
            line.sub_recipe.code for line in parent.lines.all()
            if line.sub_recipe_id in selected_pks)
        external_rows.append({"parent": parent, "child_codes": child_codes})
    return render(request, "stock/recipe_bulk_delete_confirm.html", {
        "selected": selected,
        "external_rows": external_rows,
        "error": error,
    })


@login_required
def recipe_edit(request, pk):
    """Edit a recipe's basic fields by hand.

    Editable: name, finished_weight_g, deposit_weight_g, cook_loss_pct,
    sold_as_product. Recipe LINES (ingredients / sub-recipes) are not
    touched in this stage — that's a later milestone.

    Saving sets ``is_basic_manual=True`` and ``is_sold_manual=True`` so
    the next ``import_recipes_bulk`` leaves every field the operator
    edited alone; lines still rebuild from the workbook because the
    bill-of-materials must stay in sync with the export.
    """
    recipe = get_object_or_404(Recipe, pk=pk)
    if recipe.department and not recipe.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")

    def _ctx(form, errors=None):
        return {"recipe": recipe, "form": form, "errors": errors or {}}

    if request.method == "POST":
        form = {
            "name": (request.POST.get("name") or "").strip(),
            "finished_weight_g": (request.POST.get("finished_weight_g") or "").strip(),
            "deposit_weight_g": (request.POST.get("deposit_weight_g") or "").strip(),
            "cook_loss_pct": (request.POST.get("cook_loss_pct") or "").strip(),
            "sold_as_product": request.POST.get("sold_as_product") == "on",
        }
        errors = {}
        if not form["name"]:
            errors["name"] = "Name is required."
        finished = _dec(form["finished_weight_g"])
        deposit = _dec(form["deposit_weight_g"])
        cook_loss = _dec(form["cook_loss_pct"])
        if form["finished_weight_g"] and finished is None:
            errors["finished_weight_g"] = "Enter a number."
        if form["deposit_weight_g"] and deposit is None:
            errors["deposit_weight_g"] = "Enter a number."
        if form["cook_loss_pct"] and cook_loss is None:
            errors["cook_loss_pct"] = "Enter a number."
        if errors:
            return render(request, "stock/recipe_edit.html", _ctx(form, errors))
        recipe.name = form["name"]
        recipe.finished_weight_g = finished
        recipe.deposit_weight_g = deposit
        recipe.cook_loss_pct = cook_loss
        recipe.sold_as_product = form["sold_as_product"]
        # Both manual flags flip on: the next import must not overwrite
        # the basics OR re-derive the sold flag from references.
        recipe.is_basic_manual = True
        recipe.is_sold_manual = True
        recipe.save()
        messages.success(request,
                         f"Saved edits to {recipe.code}. "
                         "Re-imports will preserve these changes.")
        return redirect("recipe_detail", pk=recipe.pk)

    form = {
        "name": recipe.name,
        "finished_weight_g": (str(recipe.finished_weight_g)
                              if recipe.finished_weight_g is not None else ""),
        "deposit_weight_g": (str(recipe.deposit_weight_g)
                             if recipe.deposit_weight_g is not None else ""),
        "cook_loss_pct": (str(recipe.cook_loss_pct)
                          if recipe.cook_loss_pct is not None else ""),
        "sold_as_product": recipe.sold_as_product,
    }
    return render(request, "stock/recipe_edit.html", _ctx(form))


@login_required
def production_home(request):
    return _placeholder(request, "production")


@login_required
def rota_home(request):
    return _placeholder(request, "rota")


@login_required
def notes_home(request):
    return _placeholder(request, "notes")


@login_required
def profile(request):
    depts = user_departments(request.user)
    return render(request, "stock/profile.html", {"departments_list": depts})


@login_required
def switch_department(request, pk):
    if user_departments(request.user).filter(pk=pk).exists():
        request.session["dept_id"] = pk
    return redirect(request.GET.get("next") or "dashboard")


@login_required
def dashboard(request):
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    products = list(dept.products.prefetch_related("prices__supplier"))
    rows, below = [], 0
    for p in products:
        line = p.latest_line
        cur = line.current if line else None
        low = cur is not None and cur < p.minimum
        if low:
            below += 1
        days_cover = p.days_of_cover(cur) if cur is not None else None
        low_by_usage = (not low and days_cover is not None and days_cover < 14)
        rows.append({"p": p, "cheap": p.cheapest_price, "current": cur,
                     "low": low, "needed": (p.minimum - cur) if low else None,
                     "days_cover": days_cover, "low_by_usage": low_by_usage})
    rows.sort(key=lambda r: (not r["low"], not r["low_by_usage"], r["p"].name.lower()))
    latest = dept.stocktakes.first()
    return render(request, "stock/dashboard.html", {
        "rows": rows, "below": below, "latest": latest,
        "n_products": len(products),
        "value": latest.total_value if latest else Decimal("0"),
    })


# ---- suppliers (global, shared by all departments) ----
@login_required
def suppliers(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if name:
            Supplier.objects.get_or_create(name=name)
            messages.success(request, f"Added supplier '{name}'.")
        return redirect("suppliers")
    return render(request, "stock/suppliers.html", {
        "suppliers": Supplier.objects.annotate(n=Count("supplierprice")),
    })


@require_POST
@login_required
def supplier_delete(request, pk):
    s = get_object_or_404(Supplier, pk=pk)
    name = s.name
    s.delete()
    messages.success(request, f"Deleted supplier '{name}'.")
    return redirect("suppliers")


# ---- ingredients (per department) ----
@login_required
def products(request):
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    if request.method == "POST":
        code = (request.POST.get("code") or "").strip() or None
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Name is required.")
            return redirect("products")
        stored_unit, stored_qty = _normalize_pack(
            request.POST.get("unit") or "g", _dec(request.POST.get("quantity")))
        defaults = {"name": name, "unit": stored_unit,
                    "minimum": _dec(request.POST.get("minimum")) or 0,
                    "department": dept}
        if code:
            product, _ = Product.objects.update_or_create(
                code=code, department=dept, defaults=defaults)
        else:
            product = Product.objects.create(**defaults)
        sup = (request.POST.get("supplier") or "").strip()
        cost = _dec(request.POST.get("cost"))
        if sup and stored_qty and cost is not None:
            supplier, _ = Supplier.objects.get_or_create(name=sup)
            SupplierPrice.objects.create(
                product=product, supplier=supplier,
                pack_weight=stored_qty, pack_price=cost,
                effective_date=datetime.date.today())
            messages.success(request, f"Saved '{name}' with {sup} price.")
        else:
            messages.success(request, f"Saved '{name}'.")
        return redirect("products")
    # Ingredients list excludes packaging — packaging has its own page so
    # the bakery view isn't drowned in NPD-P box/case rows.
    return render(request, "stock/products.html", {
        "products": (dept.products.exclude(category="packaging")
                     .prefetch_related("prices__supplier")),
        "suppliers": Supplier.objects.all(),
    })


@login_required
def packaging(request):
    """Packaging list — the Packaging-category slice of the same Products."""
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    items = (dept.products.filter(category="packaging")
             .prefetch_related("prices__supplier"))
    return render(request, "stock/packaging.html", {
        "products": items,
        "n_items": items.count(),
    })


def _get_product(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if product.department and not product.department.accessible_to(request.user):
        return None
    return product


@login_required
def product_detail(request, pk):
    product = _get_product(request, pk)
    if product is None:
        return HttpResponseForbidden("Not your department.")
    if request.method == "POST":
        sup = (request.POST.get("supplier") or "").strip()
        _, wt = _normalize_pack(
            request.POST.get("pack_unit") or product.unit,
            _dec(request.POST.get("pack_weight")))
        pr = _dec(request.POST.get("pack_price"))
        if sup and wt and pr is not None:
            supplier, _ = Supplier.objects.get_or_create(name=sup)
            SupplierPrice.objects.create(
                product=product, supplier=supplier,
                pack_weight=wt, pack_price=pr,
                effective_date=datetime.date.today())
            messages.success(request, f"Price from {sup} saved.")
        else:
            messages.error(request, "Supplier, pack weight and price are all required.")
        return redirect("product_detail", pk=pk)
    on_hand = product.on_hand
    # latest price per supplier (current) + full history with deltas, both
    # built from a single prefetch so we don't issue a query per supplier.
    product = (Product.objects.prefetch_related("prices__supplier")
               .get(pk=product.pk))
    latest_prices = sorted(product.latest_prices(),
                           key=lambda p: p.supplier.name.lower())
    cheapest = product.cheapest_price
    allergen_rows = list(product.allergens.all())
    return render(request, "stock/product_detail.html", {
        "product": product,
        "latest_prices": latest_prices,
        "cheapest": cheapest,
        "price_history": product.price_history(),
        "suppliers": Supplier.objects.all(),
        "history": product.history(),
        "batches": product.batches.select_related("delivery__supplier").order_by("use_by", "-created"),
        "usage_rows": product.usage_history(),
        "avg_weekly_usage": product.average_weekly_usage(),
        "days_of_cover": product.days_of_cover(on_hand),
        "on_hand": on_hand,
        "batches_total": product.on_hand_from_batches,
        "adjustments_net": product.adjustments_net,
        "allergens_contains": [a for a in allergen_rows if a.contains],
        "allergens_may_contain": [a for a in allergen_rows if a.may_contain and not a.contains],
    })


@require_POST
@login_required
def product_delete(request, pk):
    product = _get_product(request, pk)
    if product is None:
        return HttpResponseForbidden("Not your department.")
    name = product.name
    product.delete()
    messages.success(request, f"Deleted '{name}'.")
    return redirect("products")


@require_POST
@login_required
def price_delete(request, price_id):
    price = get_object_or_404(SupplierPrice, pk=price_id)
    pk = price.product_id
    price.delete()
    return redirect("product_detail", pk=pk)


# ---- stocktakes (per department) ----
@login_required
def stocktakes(request):
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    if request.method == "POST":
        st = Stocktake.objects.create(
            department=dept, date=datetime.date.today(),
            completed_by=(request.POST.get("completed_by") or "").strip())
        new_lines = []
        for p in dept.products.all():
            prev = _carry_over_value(dept, p.pk, exclude_stocktake_id=st.pk)
            new_lines.append(StockLine(
                stocktake=st, product=p,
                current=prev, carried_over=prev is not None))
        StockLine.objects.bulk_create(new_lines)
        return redirect("count", pk=st.pk)
    return render(request, "stock/stocktakes.html", {
        "stocktakes": dept.stocktakes.all(),
        "has_products": dept.products.exists(),
    })


@login_required
def count(request, pk):
    st = get_object_or_404(Stocktake, pk=pk)
    if st.department and not st.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    existing = set(st.lines.values_list("product_id", flat=True))
    extra_qs = (st.department.products if st.department else Product.objects).exclude(id__in=existing)
    extra_lines = []
    for p in extra_qs:
        prev = _carry_over_value(st.department, p.pk, exclude_stocktake_id=st.pk) if st.department else None
        extra_lines.append(StockLine(
            stocktake=st, product=p,
            current=prev, carried_over=prev is not None))
    StockLine.objects.bulk_create(extra_lines)
    lines = list(st.lines.select_related("product").order_by("product__name"))
    return render(request, "stock/count.html", {
        "st": st, "lines": lines, "total_value": st.total_value,
    })


@login_required
def stocktake_csv(request, pk):
    import csv
    from django.http import HttpResponse
    st = get_object_or_404(Stocktake, pk=pk)
    if st.department and not st.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    lines = list(st.lines.select_related("product").order_by("product__name"))
    resp = HttpResponse(content_type="text/csv")
    dept_slug = (st.department.name.lower() if st.department else "stocktake").replace(" ", "-")
    fname = f"stocktake-{dept_slug}-{st.date:%Y-%m-%d}.csv"
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    w = csv.writer(resp)
    w.writerow(["Ingredient", "Code", "Minimum", "Count", "Needed", "Value"])
    for line in lines:
        p = line.product
        w.writerow([
            p.name, p.code or "",
            p.minimum,
            line.current if line.current is not None else "",
            line.needed if line.needed is not None else "",
            line.value if line.value is not None else "",
        ])
    w.writerow(["TOTAL", "", "", "", "", st.total_value])
    return resp


@require_POST
@login_required
def save_count(request, line_id):
    line = get_object_or_404(StockLine, pk=line_id)
    line.current = _dec(request.POST.get("current"))
    line.carried_over = False
    line.save()
    return render(request, "stock/_line_status.html", {"line": line})


# ---- reorder / shopping list ----
def _reorder_rows(dept):
    """Ingredients in this dept currently below minimum, with order qty + cheapest supplier."""
    rows = []
    for p in dept.products.prefetch_related("prices__supplier"):
        line = p.latest_line
        cur = line.current if line else None
        if cur is None or cur >= p.minimum:
            continue
        cheap = p.cheapest_price
        order_qty = p.minimum - cur
        cost = (order_qty * cheap.pack_price).quantize(Decimal("0.01")) if cheap else None
        rows.append({
            "product": p, "current": cur, "minimum": p.minimum,
            "order_qty": order_qty,
            "supplier": cheap.supplier.name if cheap else "(no price set)",
            "pack_price": cheap.pack_price if cheap else None,
            "pack_weight": cheap.pack_weight if cheap else None,
            "est_cost": cost,
        })
    rows.sort(key=lambda r: (r["supplier"].lower(), r["product"].name.lower()))
    return rows


@login_required
def reorder(request):
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    rows = _reorder_rows(dept)
    # group by supplier for display
    groups = {}
    total = Decimal("0")
    for r in rows:
        groups.setdefault(r["supplier"], []).append(r)
        if r["est_cost"]:
            total += r["est_cost"]
    return render(request, "stock/reorder.html", {
        "groups": groups, "rows": rows, "total": total, "dept": dept,
    })


@login_required
def reorder_csv(request):
    import csv
    from django.http import HttpResponse
    from .templatetags.pack_format import pack_size as fmt_pack
    dept = current_department(request)
    if dept is None:
        return redirect("dashboard")
    rows = _reorder_rows(dept)
    # POST may carry per-line overrides as qty_<product_id>; fall back to
    # the suggested order qty when missing or unparseable.
    if request.method == "POST":
        for r in rows:
            override = _dec(request.POST.get(f"qty_{r['product'].pk}"))
            if override is not None and override >= 0:
                r["order_qty"] = override
                r["est_cost"] = ((override * r["pack_price"]).quantize(Decimal("0.01"))
                                 if r["pack_price"] is not None else None)
    resp = HttpResponse(content_type="text/csv")
    fname = f"reorder-{dept.name.lower()}-{datetime.date.today():%Y-%m-%d}.csv"
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    w = csv.writer(resp)
    w.writerow(["Supplier", "Ingredient", "Order qty", "Pack size",
                "Pack price", "Est. cost"])
    for r in rows:
        pack = fmt_pack(r["pack_weight"], r["product"].unit) if r["pack_weight"] else ""
        w.writerow([
            r["supplier"], r["product"].name,
            r["order_qty"],
            pack,
            r["pack_price"] if r["pack_price"] is not None else "",
            r["est_cost"] if r["est_cost"] is not None else "",
        ])
    return resp


# ---- deliveries / goods-in (per department) ----
@login_required
def deliveries(request):
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    deliv = (dept.deliveries.select_related("supplier")
             .annotate(n_lines=Count("batches"), packs_in=Sum("batches__qty_received"))
             .order_by("-date", "-id"))
    return render(request, "stock/deliveries.html", {"deliveries": deliv})


@login_required
def adjustments(request):
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    if request.method == "POST":
        product_id = request.POST.get("product")
        qty = _dec(request.POST.get("quantity"))
        reason = request.POST.get("reason")
        note = (request.POST.get("note") or "").strip()
        date_str = (request.POST.get("date") or "").strip()
        product = dept.products.filter(pk=product_id).first() if product_id else None
        valid_reasons = {k for k, _ in Adjustment.REASON_CHOICES}
        if not product or qty is None or qty <= 0 or reason not in valid_reasons:
            messages.error(request, "Pick an ingredient, a positive quantity, and a reason.")
            return redirect("adjustments")
        try:
            d = datetime.date.fromisoformat(date_str) if date_str else datetime.date.today()
        except ValueError:
            d = datetime.date.today()
        Adjustment.objects.create(
            product=product, department=dept, quantity=qty, reason=reason,
            date=d, user=request.user, note=note,
        )
        label = dict(Adjustment.REASON_CHOICES)[reason]
        messages.success(request, f"Logged {label.lower()} of {qty} for {product.name}.")
        return redirect("adjustments")
    log = list(dept.adjustments.select_related("product", "user")
               .order_by("-date", "-id")[:100])
    return render(request, "stock/adjustments.html", {
        "log": log,
        "products": dept.products.order_by("name"),
        "reasons": Adjustment.REASON_CHOICES,
        "reducing": Adjustment.REDUCING_REASONS,
        "today": datetime.date.today().isoformat(),
    })


@login_required
def delivery_detail(request, pk):
    delivery = get_object_or_404(Delivery.objects.select_related("supplier", "department"), pk=pk)
    if not delivery.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    batches = list(delivery.batches.select_related("product")
                   .order_by("product__name"))
    total_packs = sum((b.qty_received for b in batches), Decimal("0"))
    return render(request, "stock/delivery_detail.html", {
        "delivery": delivery,
        "batches": batches,
        "n_lines": len(batches),
        "total_packs": total_packs,
    })


@login_required
def delivery_new(request):
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    if request.method == "POST":
        supplier_id = request.POST.get("supplier")
        supplier = Supplier.objects.filter(pk=supplier_id).first() if supplier_id else None
        if not supplier:
            messages.error(request, "Pick a supplier.")
            return redirect("delivery_new")
        date_str = (request.POST.get("date") or "").strip()
        try:
            d = datetime.date.fromisoformat(date_str) if date_str else datetime.date.today()
        except ValueError:
            d = datetime.date.today()
        product_ids = request.POST.getlist("product")
        batch_codes = request.POST.getlist("batch_code")
        use_by_strs = request.POST.getlist("use_by")
        qty_strs = request.POST.getlist("qty")
        rows = []
        for pid, code, ub, q in zip(product_ids, batch_codes, use_by_strs, qty_strs):
            qty = _dec(q)
            if not pid or qty is None or qty <= 0:
                continue
            product = dept.products.filter(pk=pid).first()
            if not product:
                continue
            try:
                ub_date = datetime.date.fromisoformat(ub) if ub.strip() else None
            except ValueError:
                ub_date = None
            rows.append((product, code.strip(), ub_date, qty))
        if not rows:
            messages.error(request, "Add at least one line with a quantity.")
            return redirect("delivery_new")
        delivery = Delivery.objects.create(
            department=dept, supplier=supplier, date=d,
            note=(request.POST.get("note") or "").strip())
        Batch.objects.bulk_create([
            Batch(delivery=delivery, product=p, batch_code=code,
                  use_by=ub, qty_received=q, qty_remaining=q)
            for (p, code, ub, q) in rows
        ])
        priced_ids = set(SupplierPrice.objects
            .filter(supplier=supplier, product_id__in=[p.id for p, *_ in rows])
            .values_list("product_id", flat=True))
        no_price = sum(1 for (p, *_) in rows if p.id not in priced_ids)
        msg = f"Logged delivery from {supplier.name} ({len(rows)} line{'s' if len(rows) != 1 else ''})."
        if no_price:
            msg += (f" Note: {no_price} batch{'es' if no_price != 1 else ''} "
                    f"need{'' if no_price != 1 else 's'} a supplier price set.")
        messages.success(request, msg)
        return redirect("deliveries")
    products = list(dept.products.prefetch_related("prices").order_by("name"))
    for p in products:
        p.supplier_ids = sorted({sp.supplier_id for sp in p.prices.all()})
    return render(request, "stock/delivery_new.html", {
        "products": products,
        "suppliers": Supplier.objects.order_by("name"),
        "today": datetime.date.today().isoformat(),
        "lines": [{} for _ in range(6)],
    })


@login_required
def delivery_scan(request):
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    if request.method != "POST":
        return render(request, "stock/delivery_scan.html", {
            "suppliers": Supplier.objects.order_by("name"),
        })
    supplier_id = request.POST.get("supplier")
    supplier = Supplier.objects.filter(pk=supplier_id).first() if supplier_id else None
    if not supplier:
        messages.error(request, "Pick a supplier first.")
        return redirect("delivery_scan")
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Pick a delivery-note image or PDF to scan.")
        return redirect("delivery_scan")
    if upload.size > 20 * 1024 * 1024:
        messages.error(request, "That file is over 20 MB. Try a smaller photo or PDF.")
        return redirect("delivery_scan")
    extracted = []
    try:
        extracted = extract_lines(upload.read(), upload.content_type or "")
    except ExtractError as e:
        messages.warning(request, f"Couldn't scan the delivery note: {e}. Add the lines below by hand.")
    except Exception:
        messages.warning(request, "Couldn't scan the delivery note. Add the lines below by hand.")
    if not extracted:
        messages.warning(request,
            "No line items came back from the scan. Enter the delivery manually below.")
    prefilled = []
    for item in extracted:
        product, confident = auto_match(item["description"], supplier, dept)
        prefilled.append({
            "product_id": product.pk if (product and confident) else None,
            "qty": item["qty"],
            "hint": item["description"],
        })
    while len(prefilled) < 3:
        prefilled.append({})
    products = list(dept.products.prefetch_related("prices").order_by("name"))
    for p in products:
        p.supplier_ids = sorted({sp.supplier_id for sp in p.prices.all()})
    return render(request, "stock/delivery_new.html", {
        "products": products,
        "suppliers": Supplier.objects.order_by("name"),
        "today": datetime.date.today().isoformat(),
        "lines": prefilled,
        "prefilled_supplier_id": supplier.pk,
        "default_show_all": True,
    })


# ---- customers (per department) ----
def _customer_qs(dept, customer_type):
    return (Customer.objects.filter(department=dept,
                                    customer_type=customer_type)
            .order_by("name"))


@login_required
def customers_internal(request):
    """Internal-customer list (Estate outlets like GARDEN CAFE, FARMSHOP, …).

    Also the default landing for the Customers top-nav link.
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    return render(request, "stock/customers_internal.html", {
        "customers": _customer_qs(dept, Customer.INTERNAL),
    })


@login_required
def customers_wholesale(request):
    """Wholesale-customer list (TEALS, PINKMANS, SOCIETY …)."""
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    return render(request, "stock/customers_wholesale.html", {
        "customers": _customer_qs(dept, Customer.WHOLESALE),
    })


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if customer.department and not customer.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    return render(request, "stock/customer_detail.html", {
        "customer": customer,
        "type_choices": Customer.TYPE_CHOICES,
    })


@require_POST
@login_required
def customer_set_type(request, pk):
    """Operator override for a customer's type — persists past re-imports.

    Sets ``is_type_manual=True`` so the next ``import_customers`` keeps
    the choice (mirrors ``Recipe.is_sold_manual``).
    """
    customer = get_object_or_404(Customer, pk=pk)
    if customer.department and not customer.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    new_type = request.POST.get("customer_type")
    valid = {k for k, _ in Customer.TYPE_CHOICES}
    if new_type not in valid:
        messages.error(request, "Pick a valid customer type.")
        return redirect("customer_detail", pk=pk)
    customer.customer_type = new_type
    customer.is_type_manual = True
    customer.save(update_fields=["customer_type", "is_type_manual"])
    messages.success(request,
                     f"Marked {customer.name} as "
                     f"{customer.get_customer_type_display().lower()}.")
    return redirect("customer_detail", pk=pk)


def _customer_list_redirect_url(customer_type):
    """Where to send the operator after a create / edit / delete."""
    if customer_type == Customer.WHOLESALE:
        return "customers_wholesale"
    return "customers"


@login_required
def customer_new(request):
    """Create a customer by hand.

    Pre-selects the type from the ?type= query parameter so the "Add
    customer" button on each list page lands the operator on the right
    default. The new row is flagged ``is_manual_entry=True`` (so the
    importer will skip it forever) and ``is_type_manual=True`` (so its
    fields can never be overwritten anyway — belt and braces).
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")

    default_type = request.GET.get("type")
    if default_type not in {k for k, _ in Customer.TYPE_CHOICES}:
        default_type = Customer.INTERNAL

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        location = (request.POST.get("location") or "").strip()
        ordered_by = (request.POST.get("ordered_by") or "").strip()
        customer_type = request.POST.get("customer_type")
        valid_types = {k for k, _ in Customer.TYPE_CHOICES}
        if not name:
            messages.error(request, "Name is required.")
            return render(request, "stock/customer_form.html",
                          _customer_form_context(
                              {"name": name, "location": location,
                               "ordered_by": ordered_by,
                               "customer_type": customer_type or default_type},
                              mode="new", default_type=default_type))
        if customer_type not in valid_types:
            messages.error(request, "Pick a valid customer type.")
            return render(request, "stock/customer_form.html",
                          _customer_form_context(
                              {"name": name, "location": location,
                               "ordered_by": ordered_by,
                               "customer_type": default_type},
                              mode="new", default_type=default_type))
        # Case-insensitive duplicate check — "TEALS" / "teals" are the same.
        if Customer.objects.filter(name__iexact=name).exists():
            messages.error(request,
                           f"A customer named '{name}' already exists. "
                           "Pick a different name.")
            return render(request, "stock/customer_form.html",
                          _customer_form_context(
                              {"name": name, "location": location,
                               "ordered_by": ordered_by,
                               "customer_type": customer_type},
                              mode="new", default_type=default_type))
        customer = Customer.objects.create(
            name=name, location=location, ordered_by=ordered_by,
            customer_type=customer_type,
            is_type_manual=True, is_manual_entry=True,
            department=dept,
        )
        messages.success(request, f"Created customer '{customer.name}'.")
        return redirect("customer_detail", pk=customer.pk)

    return render(request, "stock/customer_form.html",
                  _customer_form_context(
                      {"name": "", "location": "", "ordered_by": "",
                       "customer_type": default_type},
                      mode="new", default_type=default_type))


def _customer_form_context(form, mode, default_type, customer=None):
    return {
        "form": form,
        "mode": mode,                         # "new" | "edit"
        "default_type": default_type,
        "customer": customer,
        "type_choices": Customer.TYPE_CHOICES,
    }


@login_required
def customer_edit(request, pk):
    """Edit an existing customer.

    Always sets ``is_type_manual=True`` on save so the next import
    leaves every editable field alone — even if the operator only
    changed one of them. Department-scoped.
    """
    customer = get_object_or_404(Customer, pk=pk)
    if customer.department and not customer.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        location = (request.POST.get("location") or "").strip()
        ordered_by = (request.POST.get("ordered_by") or "").strip()
        customer_type = request.POST.get("customer_type")
        valid_types = {k for k, _ in Customer.TYPE_CHOICES}
        form = {"name": name, "location": location,
                "ordered_by": ordered_by, "customer_type": customer_type}
        if not name:
            messages.error(request, "Name is required.")
            return render(request, "stock/customer_form.html",
                          _customer_form_context(form, mode="edit",
                                                 default_type=customer.customer_type,
                                                 customer=customer))
        if customer_type not in valid_types:
            messages.error(request, "Pick a valid customer type.")
            return render(request, "stock/customer_form.html",
                          _customer_form_context(form, mode="edit",
                                                 default_type=customer.customer_type,
                                                 customer=customer))
        # Renaming: refuse a name that collides with a DIFFERENT customer.
        if Customer.objects.filter(name__iexact=name).exclude(pk=customer.pk).exists():
            messages.error(request,
                           f"A customer named '{name}' already exists. "
                           "Pick a different name.")
            return render(request, "stock/customer_form.html",
                          _customer_form_context(form, mode="edit",
                                                 default_type=customer.customer_type,
                                                 customer=customer))
        customer.name = name
        customer.location = location
        customer.ordered_by = ordered_by
        customer.customer_type = customer_type
        customer.is_type_manual = True  # operator owns this row's content now
        customer.save()
        messages.success(request, f"Saved changes to '{customer.name}'.")
        return redirect("customer_detail", pk=customer.pk)

    form = {"name": customer.name, "location": customer.location,
            "ordered_by": customer.ordered_by,
            "customer_type": customer.customer_type}
    return render(request, "stock/customer_form.html",
                  _customer_form_context(form, mode="edit",
                                         default_type=customer.customer_type,
                                         customer=customer))


@require_POST
@login_required
def customer_delete(request, pk):
    """Delete a customer (POST after JS confirm)."""
    customer = get_object_or_404(Customer, pk=pk)
    if customer.department and not customer.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    name = customer.name
    list_url = _customer_list_redirect_url(customer.customer_type)
    customer.delete()
    messages.success(request, f"Deleted customer '{name}'.")
    return redirect(list_url)


# ---- sale products (sellable SKUs, distinct from ingredient Products) ----
def _sale_product_qs(dept):
    return (SaleProduct.objects.filter(department=dept)
            .select_related("recipe")
            .order_by("name"))


def _recipe_suggestions(name, all_recipes, *, n=5, threshold=0.5):
    """Top-N fuzzy recipe matches for a sale product name.

    Uses difflib.SequenceMatcher ratios against each recipe's name
    (case-insensitive, trimmed). Returns a list of
    ``{recipe, ratio, percent}`` dicts, highest ratio first, capped at
    ``n``. ``threshold`` is the minimum ratio to surface — too low
    floods the review page with noise; default 0.5 is "vaguely
    related".
    """
    from difflib import SequenceMatcher
    target = (name or "").strip().lower()
    if not target:
        return []
    scored = []
    for r in all_recipes:
        rn = (r.name or "").strip().lower()
        if not rn:
            continue
        ratio = SequenceMatcher(None, target, rn).ratio()
        if ratio < threshold:
            continue
        scored.append({"recipe": r, "ratio": ratio,
                       "percent": int(round(ratio * 100))})
    scored.sort(key=lambda x: x["ratio"], reverse=True)
    return scored[:n]


@login_required
def sale_products(request):
    """Sale products list — the default landing for the Products section."""
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    products = list(_sale_product_qs(dept))
    n_linked = sum(1 for p in products if p.recipe_id)
    n_unlinked = sum(1 for p in products if not p.recipe_id)
    n_unconfirmed = sum(1 for p in products
                        if p.recipe_id and not p.link_confirmed)
    return render(request, "stock/sale_products.html", {
        "products": products,
        "n_linked": n_linked,
        "n_unlinked": n_unlinked,
        "n_unconfirmed": n_unconfirmed,
    })


@login_required
def sale_product_detail(request, pk):
    product = get_object_or_404(SaleProduct, pk=pk)
    if product.department and not product.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    suggestions = []
    if not product.recipe_id:
        all_recipes = list(Recipe.objects.filter(archived=False))
        suggestions = _recipe_suggestions(product.name, all_recipes)
    return render(request, "stock/sale_product_detail.html", {
        "product": product,
        "suggestions": suggestions,
    })


def _sale_product_form_context(form, mode, product=None, error=None,
                                recipes=None):
    return {
        "form": form,
        "mode": mode,
        "product": product,
        "error": error,
        "recipes": recipes if recipes is not None else [],
    }


def _parse_price(s):
    s = (s or "").strip()
    if s == "":
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


@login_required
def sale_product_new(request):
    """Create a sale product by hand.

    Hand-created rows are flagged ``is_manual_entry=True`` so the
    deploy-time importer never overwrites them — same protection
    pattern as ``Customer.is_manual_entry``.
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    recipes = list(Recipe.objects.filter(archived=False).order_by("code"))

    if request.method == "POST":
        form = {
            "name": (request.POST.get("name") or "").strip(),
            "price": (request.POST.get("price") or "").strip(),
            "sage_number": (request.POST.get("sage_number") or "").strip(),
            "pack_size": (request.POST.get("pack_size") or "").strip(),
            "recipe_id": request.POST.get("recipe_id") or "",
        }
        error = None
        if not form["name"]:
            error = "Name is required."
        elif SaleProduct.objects.filter(name__iexact=form["name"]).exists():
            error = (f"A sale product named '{form['name']}' already "
                     "exists. Pick a different name.")
        if error:
            return render(request, "stock/sale_product_form.html",
                          _sale_product_form_context(
                              form, mode="new", error=error, recipes=recipes))
        recipe = None
        if form["recipe_id"]:
            recipe = Recipe.objects.filter(pk=form["recipe_id"]).first()
        sp = SaleProduct.objects.create(
            name=form["name"],
            price=_parse_price(form["price"]),
            sage_number=form["sage_number"],
            pack_size=form["pack_size"],
            recipe=recipe,
            link_source=SaleProduct.MANUAL if recipe else SaleProduct.NONE,
            link_confirmed=bool(recipe),
            department=dept,
            is_manual_entry=True,
        )
        messages.success(request, f"Created sale product '{sp.name}'.")
        return redirect("sale_product_detail", pk=sp.pk)

    form = {"name": "", "price": "", "sage_number": "",
            "pack_size": "", "recipe_id": ""}
    return render(request, "stock/sale_product_form.html",
                  _sale_product_form_context(form, mode="new", recipes=recipes))


@login_required
def sale_product_edit(request, pk):
    """Edit a sale product. Setting a recipe flips link_source=manual
    so the next import won't re-derive (or clear) the link."""
    product = get_object_or_404(SaleProduct, pk=pk)
    if product.department and not product.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    recipes = list(Recipe.objects.filter(archived=False).order_by("code"))

    if request.method == "POST":
        form = {
            "name": (request.POST.get("name") or "").strip(),
            "price": (request.POST.get("price") or "").strip(),
            "sage_number": (request.POST.get("sage_number") or "").strip(),
            "pack_size": (request.POST.get("pack_size") or "").strip(),
            "recipe_id": request.POST.get("recipe_id") or "",
        }
        error = None
        if not form["name"]:
            error = "Name is required."
        elif (SaleProduct.objects.filter(name__iexact=form["name"])
              .exclude(pk=product.pk).exists()):
            error = (f"A sale product named '{form['name']}' already "
                     "exists. Pick a different name.")
        if error:
            return render(request, "stock/sale_product_form.html",
                          _sale_product_form_context(
                              form, mode="edit", product=product,
                              error=error, recipes=recipes))
        new_recipe = None
        if form["recipe_id"]:
            new_recipe = Recipe.objects.filter(pk=form["recipe_id"]).first()
        link_changed = (
            (product.recipe_id or None) != (new_recipe.pk if new_recipe else None))
        product.name = form["name"]
        product.price = _parse_price(form["price"])
        product.sage_number = form["sage_number"]
        product.pack_size = form["pack_size"]
        if link_changed:
            product.recipe = new_recipe
            product.link_source = SaleProduct.MANUAL if new_recipe else SaleProduct.NONE
            product.link_confirmed = bool(new_recipe)
        product.save()
        messages.success(request, f"Saved changes to '{product.name}'.")
        return redirect("sale_product_detail", pk=product.pk)

    form = {
        "name": product.name,
        "price": (str(product.price) if product.price is not None else ""),
        "sage_number": product.sage_number,
        "pack_size": product.pack_size,
        "recipe_id": str(product.recipe_id or ""),
    }
    return render(request, "stock/sale_product_form.html",
                  _sale_product_form_context(
                      form, mode="edit", product=product, recipes=recipes))


@require_POST
@login_required
def sale_product_delete(request, pk):
    product = get_object_or_404(SaleProduct, pk=pk)
    if product.department and not product.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    name = product.name
    product.delete()
    messages.success(request, f"Deleted sale product '{name}'.")
    return redirect("sale_products")


@login_required
def sale_product_link_review(request):
    """Review the auto-linker's work: unlinked products + fuzzy suggestions.

    The page lists every SaleProduct that needs the operator's
    attention — currently anything with no recipe. For each, computes
    the top-N fuzzy recipe suggestions so the operator can confirm one
    with a single click; confirming sets ``link_source=manual`` and
    ``link_confirmed=True`` so the next deploy won't undo the pick.

    Also shows confirmed-via-Sage and confirmed-via-name rows in a
    summary block so the operator can sanity-check the auto-linker's
    output at a glance.
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    products = list(_sale_product_qs(dept))
    all_recipes = list(Recipe.objects.filter(archived=False).order_by("code"))
    unlinked = []
    sage_matched = []
    name_matched = []
    manual = []
    for p in products:
        if p.recipe_id is None:
            row = {"product": p,
                   "suggestions": _recipe_suggestions(p.name, all_recipes)}
            unlinked.append(row)
        elif p.link_source == SaleProduct.SAGE:
            sage_matched.append(p)
        elif p.link_source == SaleProduct.NAME:
            name_matched.append(p)
        elif p.link_source == SaleProduct.MANUAL:
            manual.append(p)
    return render(request, "stock/sale_product_link_review.html", {
        "unlinked": unlinked,
        "sage_matched": sage_matched,
        "name_matched": name_matched,
        "manual": manual,
        "all_recipes": all_recipes,
    })


@require_POST
@login_required
def sale_product_link_set(request, pk):
    """Set or clear the recipe link via the review/detail page.

    POST ``recipe_id`` (empty / "0" / "none" → unlink; otherwise a
    Recipe pk to link to). Flips ``link_source=manual`` and
    ``link_confirmed=True`` so the import never overrides the pick.
    A future un-link sets ``link_source=manual`` too (the operator's
    deliberate "no, none of these apply" decision survives re-import).
    """
    product = get_object_or_404(SaleProduct, pk=pk)
    if product.department and not product.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    raw = (request.POST.get("recipe_id") or "").strip()
    if raw in ("", "0", "none"):
        product.recipe = None
        product.link_source = SaleProduct.MANUAL
        product.link_confirmed = True
        msg = f"Cleared the recipe link on '{product.name}'."
    else:
        try:
            new_pk = int(raw)
        except ValueError:
            messages.error(request, "Pick a valid recipe.")
            return redirect("sale_product_link_review")
        recipe = Recipe.objects.filter(pk=new_pk).first()
        if recipe is None:
            messages.error(request, "That recipe no longer exists.")
            return redirect("sale_product_link_review")
        product.recipe = recipe
        product.link_source = SaleProduct.MANUAL
        product.link_confirmed = True
        msg = f"Linked '{product.name}' to {recipe.code} — {recipe.name}."
    product.save(update_fields=[
        "recipe", "link_source", "link_confirmed"])
    messages.success(request, msg)
    next_url = (request.POST.get("next") or "").strip()
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("sale_product_link_review")


@require_POST
@login_required
def sale_product_confirm_sage_matches(request):
    """Bulk-confirm every Sage-source link in one click.

    For every SaleProduct currently auto-linked via Sage No., flip
    ``link_source=manual`` so the import permanently respects the
    operator's "yes, that's right" verdict. (link_confirmed is already
    True for Sage matches; the flip is purely about future-proofing
    against a Sage code being later removed from a Recipe.)
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    qs = (SaleProduct.objects.filter(department=dept,
                                     link_source=SaleProduct.SAGE))
    n = qs.update(link_source=SaleProduct.MANUAL, link_confirmed=True)
    messages.success(
        request,
        f"Confirmed {n} Sage-matched link(s). Future re-imports will "
        "leave them alone.")
    return redirect("sale_product_link_review")

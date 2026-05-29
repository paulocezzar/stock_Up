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
from .models import Supplier, Product, SupplierPrice, Stocktake, StockLine, Department, Delivery, Batch, Adjustment, Recipe, RecipeLine, RecipeCycleError, Customer, SuppressedRecipe, SaleProduct, Order, OrderLine
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
        # Checkbox: present in POST iff ticked; absent means False.
        is_internal = bool(request.POST.get("is_internal"))
        valid_types = {k for k, _ in Customer.TYPE_CHOICES}
        form = {"name": name, "location": location,
                "ordered_by": ordered_by, "customer_type": customer_type,
                "is_internal": is_internal}
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
        customer.is_internal = is_internal
        customer.is_type_manual = True  # operator owns this row's content now
        customer.save()
        messages.success(request, f"Saved changes to '{customer.name}'.")
        return redirect("customer_detail", pk=customer.pk)

    form = {"name": customer.name, "location": customer.location,
            "ordered_by": customer.ordered_by,
            "customer_type": customer.customer_type,
            "is_internal": customer.is_internal}
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
            .select_related("link_recipe", "link_product")
            .order_by("name"))


def _annotate_recipe_roles(recipes):
    """Stamp ``cached_is_component`` on each recipe in one extra query.

    ``Recipe.is_used_as_component`` is a property that hits the DB per
    recipe — fine for one detail page, useless for a list of suggestions.
    Here we collect every sub_recipe_id referenced anywhere in one
    query and tag each recipe in the input list. The attribute name
    avoids a leading underscore so Django templates can read it
    (templates refuse `recipe._foo` attribute access). Returns the
    same list (mutated) for chaining.
    """
    referenced = set(
        RecipeLine.objects.filter(sub_recipe__isnull=False)
        .values_list("sub_recipe_id", flat=True))
    for r in recipes:
        r.cached_is_component = r.pk in referenced
    return recipes


def _recipe_picker_payload(recipes):
    """Plain list of dicts for the client-side recipe autocomplete.

    Each entry is ``{pk, code, name, sold, component}``. The browser
    filters this list as the operator types; nothing per-keystroke
    hits the server. Pass a list already annotated by
    ``_annotate_recipe_roles`` so the role flags are accurate. The
    template renders it with ``{{ payload|json_script:"recipe-picker-data" }}``
    so embedding is XSS-safe automatically (no ``</script>`` escape worries).
    """
    return [
        {"pk": r.pk, "code": r.code, "name": r.name,
         "sold": bool(r.sold_as_product),
         "component": bool(getattr(r, "cached_is_component", False))}
        for r in recipes
    ]


def _recipe_suggestions(name, all_recipes, *, n=5, threshold=0.5):
    """Top-N fuzzy recipe matches for a sale product name.

    Uses difflib.SequenceMatcher ratios against each recipe's name
    (case-insensitive, trimmed). Returns a list of
    ``{recipe, ratio, percent, is_sold, is_component}`` dicts, highest
    ratio first, capped at ``n``. The ``is_sold`` / ``is_component``
    flags drive the link-review UI's "sold" / "component" labels so
    the operator can tell a sellable recipe from an internal helper at
    a glance. ``threshold`` is the minimum ratio to surface — too low
    floods the review page with noise; default 0.5 is "vaguely
    related".

    Callers should pass ``all_recipes`` already annotated by
    ``_annotate_recipe_roles`` so the role flags are accurate; without
    that we fall back to ``sold_as_product`` only and treat
    ``is_component`` as False (the live property would do one extra
    query per recipe, which we deliberately avoid here).
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
        scored.append({
            "recipe": r, "ratio": ratio,
            "percent": int(round(ratio * 100)),
            "is_sold": bool(r.sold_as_product),
            "is_component": bool(getattr(r, "cached_is_component", False)),
        })
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
    has_link = bool(product.link_recipe_id or product.link_product_id)
    if not has_link:
        all_recipes = _annotate_recipe_roles(
            list(Recipe.objects.filter(archived=False)))
        suggestions = _recipe_suggestions(product.name, all_recipes)
    resolved = None
    if has_link:
        try:
            recipe, total_qty, unit = product.resolved_recipe_consumption()
            if recipe is not None:
                resolved = {
                    "recipe": recipe,
                    "total_quantity": total_qty,
                    "unit": unit,
                    "unit_label": dict(SaleProduct.LINK_UNIT_CHOICES).get(unit, unit),
                }
        except Exception:
            # SaleProductCycleError or any odd state → swallow so the
            # detail page still renders; the resolve banner shows the
            # error inline below.
            resolved = {"error": "cycle detected in link chain"}
    return render(request, "stock/sale_product_detail.html", {
        "product": product,
        "suggestions": suggestions,
        "resolved": resolved,
        "link_unit_label": dict(SaleProduct.LINK_UNIT_CHOICES).get(
            product.link_unit, product.link_unit),
    })


def _sale_product_form_context(form, mode, product=None, error=None,
                                recipes=None, dept=None):
    recipes = recipes if recipes is not None else []
    # The form template renders TWO search-as-you-type pickers — one
    # for recipes, one for other SaleProducts (so a Pack/6 can link to
    # the Loose product). Both are powered by the same widget reading
    # from separate JSON blobs.
    if dept is None and product is not None:
        dept = product.department
    products_qs = SaleProduct.objects.all()
    if dept is not None:
        products_qs = products_qs.filter(department=dept)
    # Don't let a product link to itself; downstream cycles get caught
    # at resolution time, but exclude the obvious case from the picker.
    exclude_pk = product.pk if product else None
    return {
        "form": form,
        "mode": mode,
        "product": product,
        "error": error,
        "recipes": recipes,
        "recipe_picker_payload": _recipe_picker_payload(recipes),
        "product_picker_payload": _product_picker_payload(
            products_qs, exclude_pk=exclude_pk),
        "link_unit_choices": SaleProduct.LINK_UNIT_CHOICES,
    }


def _parse_price(s):
    s = (s or "").strip()
    if s == "":
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _product_picker_payload(products, exclude_pk=None):
    """JSON-able list for the SaleProduct autocomplete (sister to recipes).

    Each entry has the same ``{pk, code, name, sold, component, info,
    kind}`` shape the recipe payload uses so the same widget can render
    both — ``sold``/``component`` are always False for sale products,
    ``code`` carries the Sage number (often empty) and ``info`` the
    pack size, both small. ``kind`` lets the template tag the row
    "product" to distinguish it visually.
    """
    return [
        {"pk": p.pk, "code": p.sage_number or "",
         "name": p.name, "sold": False, "component": False,
         "info": p.pack_size or "", "kind": "product"}
        for p in products
        if exclude_pk is None or p.pk != exclude_pk
    ]


def _parse_link_form(post):
    """Extract the polymorphic link choice from a POST.

    Returns ``(link_recipe, link_product, quantity, unit, error)``.
    Caller supplies the resolved Recipe/SaleProduct via
    ``post["recipe_id"]`` / ``post["product_id"]`` and the form-level
    ``post["link_target_type"]`` (``"recipe"`` / ``"product"`` /
    empty = unlinked). Quantity defaults to 1 and unit to ``count``
    when a target is set; an unlinked submission resets both to the
    same defaults.

    Backwards-compat: a POST that omits ``link_target_type`` but
    carries a ``recipe_id`` is treated as the old "recipe + qty 1 +
    count" shape — keeps the link-review's existing simple-confirm
    button working unchanged.
    """
    target_type = (post.get("link_target_type") or "").strip().lower()
    raw_recipe = (post.get("recipe_id") or "").strip()
    raw_product = (post.get("product_id") or "").strip()
    raw_qty = (post.get("link_quantity") or "").strip()
    raw_unit = (post.get("link_unit") or "").strip()

    if not target_type:
        # Old shape: assume "recipe" iff recipe_id present, else
        # unlinked. Quantity/unit not provided → default.
        target_type = "recipe" if raw_recipe else ""

    link_recipe = None
    link_product = None
    if target_type == "recipe" and raw_recipe and raw_recipe not in ("0", "none"):
        link_recipe = Recipe.objects.filter(pk=raw_recipe).first()
        if link_recipe is None:
            return None, None, Decimal("1"), SaleProduct.COUNT, "That recipe doesn't exist."
    elif target_type == "product" and raw_product and raw_product not in ("0", "none"):
        link_product = SaleProduct.objects.filter(pk=raw_product).first()
        if link_product is None:
            return None, None, Decimal("1"), SaleProduct.COUNT, "That product doesn't exist."

    # Quantity / unit only matter when a target is set. Empty → 1.
    if raw_qty:
        try:
            qty = Decimal(raw_qty)
        except InvalidOperation:
            return None, None, Decimal("1"), SaleProduct.COUNT, "Quantity must be a number."
        if qty <= 0:
            return None, None, Decimal("1"), SaleProduct.COUNT, "Quantity must be greater than zero."
    else:
        qty = Decimal("1")

    unit_choices = {k for k, _ in SaleProduct.LINK_UNIT_CHOICES}
    unit = raw_unit if raw_unit in unit_choices else SaleProduct.COUNT

    return link_recipe, link_product, qty, unit, None


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
    recipes = _annotate_recipe_roles(
        list(Recipe.objects.filter(archived=False).order_by("code")))

    if request.method == "POST":
        form = {
            "name": (request.POST.get("name") or "").strip(),
            "price": (request.POST.get("price") or "").strip(),
            "sage_number": (request.POST.get("sage_number") or "").strip(),
            "pack_size": (request.POST.get("pack_size") or "").strip(),
            "link_target_type": (request.POST.get("link_target_type") or "").strip(),
            "recipe_id": request.POST.get("recipe_id") or "",
            "product_id": request.POST.get("product_id") or "",
            "link_quantity": (request.POST.get("link_quantity") or "").strip(),
            "link_unit": (request.POST.get("link_unit") or "").strip(),
        }
        error = None
        if not form["name"]:
            error = "Name is required."
        elif SaleProduct.objects.filter(name__iexact=form["name"]).exists():
            error = (f"A sale product named '{form['name']}' already "
                     "exists. Pick a different name.")
        link_recipe = link_product = None
        quantity = Decimal("1")
        unit = SaleProduct.COUNT
        if error is None:
            link_recipe, link_product, quantity, unit, link_error = (
                _parse_link_form(request.POST))
            if link_error:
                error = link_error
        if error:
            return render(request, "stock/sale_product_form.html",
                          _sale_product_form_context(
                              form, mode="new", error=error, recipes=recipes,
                              dept=dept))
        has_target = link_recipe is not None or link_product is not None
        sp = SaleProduct.objects.create(
            name=form["name"],
            price=_parse_price(form["price"]),
            sage_number=form["sage_number"],
            pack_size=form["pack_size"],
            link_recipe=link_recipe,
            link_product=link_product,
            link_quantity=quantity if has_target else Decimal("1"),
            link_unit=unit if has_target else SaleProduct.COUNT,
            link_source=SaleProduct.MANUAL if has_target else SaleProduct.NONE,
            link_confirmed=has_target,
            department=dept,
            is_manual_entry=True,
        )
        messages.success(request, f"Created sale product '{sp.name}'.")
        return redirect("sale_product_detail", pk=sp.pk)

    form = {"name": "", "price": "", "sage_number": "", "pack_size": "",
            "link_target_type": "recipe", "recipe_id": "", "product_id": "",
            "link_quantity": "1", "link_unit": SaleProduct.COUNT}
    return render(request, "stock/sale_product_form.html",
                  _sale_product_form_context(
                      form, mode="new", recipes=recipes, dept=dept))


@login_required
def sale_product_edit(request, pk):
    """Edit a sale product including its quantified, polymorphic link.

    The link may target a Recipe OR another SaleProduct (Pack/6 → Loose)
    with a quantity + unit; setting any of those flips link_source=manual
    so the next import won't re-derive (or clear) the choice.
    """
    product = get_object_or_404(SaleProduct, pk=pk)
    if product.department and not product.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    recipes = _annotate_recipe_roles(
        list(Recipe.objects.filter(archived=False).order_by("code")))

    if request.method == "POST":
        form = {
            "name": (request.POST.get("name") or "").strip(),
            "price": (request.POST.get("price") or "").strip(),
            "sage_number": (request.POST.get("sage_number") or "").strip(),
            "pack_size": (request.POST.get("pack_size") or "").strip(),
            "link_target_type": (request.POST.get("link_target_type") or "").strip(),
            "recipe_id": request.POST.get("recipe_id") or "",
            "product_id": request.POST.get("product_id") or "",
            "link_quantity": (request.POST.get("link_quantity") or "").strip(),
            "link_unit": (request.POST.get("link_unit") or "").strip(),
        }
        error = None
        if not form["name"]:
            error = "Name is required."
        elif (SaleProduct.objects.filter(name__iexact=form["name"])
              .exclude(pk=product.pk).exists()):
            error = (f"A sale product named '{form['name']}' already "
                     "exists. Pick a different name.")
        link_recipe = link_product = None
        quantity = Decimal("1")
        unit = SaleProduct.COUNT
        if error is None:
            link_recipe, link_product, quantity, unit, link_error = (
                _parse_link_form(request.POST))
            if link_error:
                error = link_error
            elif link_product is not None and link_product.pk == product.pk:
                error = "A product can't link to itself."
        if error:
            return render(request, "stock/sale_product_form.html",
                          _sale_product_form_context(
                              form, mode="edit", product=product,
                              error=error, recipes=recipes))
        has_target = link_recipe is not None or link_product is not None
        link_changed = (
            (product.link_recipe_id or None,
             product.link_product_id or None,
             product.link_quantity,
             product.link_unit) !=
            (link_recipe.pk if link_recipe else None,
             link_product.pk if link_product else None,
             quantity if has_target else Decimal("1"),
             unit if has_target else SaleProduct.COUNT))
        product.name = form["name"]
        product.price = _parse_price(form["price"])
        product.sage_number = form["sage_number"]
        product.pack_size = form["pack_size"]
        if link_changed:
            product.link_recipe = link_recipe
            product.link_product = link_product
            product.link_quantity = quantity if has_target else Decimal("1")
            product.link_unit = unit if has_target else SaleProduct.COUNT
            product.link_source = SaleProduct.MANUAL if has_target else SaleProduct.NONE
            product.link_confirmed = has_target
        product.save()
        messages.success(request, f"Saved changes to '{product.name}'.")
        return redirect("sale_product_detail", pk=product.pk)

    current_target = "recipe"
    if product.link_product_id:
        current_target = "product"
    elif not product.link_recipe_id:
        current_target = "recipe"
    form = {
        "name": product.name,
        "price": (str(product.price) if product.price is not None else ""),
        "sage_number": product.sage_number,
        "pack_size": product.pack_size,
        "link_target_type": current_target,
        "recipe_id": str(product.link_recipe_id or ""),
        "product_id": str(product.link_product_id or ""),
        "link_quantity": (str(product.link_quantity)
                          if product.link_quantity is not None else "1"),
        "link_unit": product.link_unit or SaleProduct.COUNT,
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
    """Review queue: only UNRESOLVED sale products.

    A product is unresolved iff it has no recipe yet OR its current
    link hasn't been confirmed (``link_confirmed=False``). The moment
    the operator confirms a link (Sage / name / manual pick), the
    product drops off this queue and lives on in the normal
    ``/sale-products/`` list — where it can still be edited or
    re-linked if needed.

    For each unresolved row we compute top-N fuzzy recipe suggestions
    (difflib SequenceMatcher) so the operator can confirm one with a
    single click. Every suggestion AND every recipe in the "pick any
    recipe" dropdown is labelled with whether it's a sold product
    (``sold_as_product=True``) or a component (used as a sub_recipe
    elsewhere) so the operator can tell a sellable recipe from an
    internal helper at a glance. The bulk "Confirm all Sage matches"
    action still lives here — it promotes auto-Sage matches to
    ``manual`` (and ``link_confirmed=True``), removing them from the
    queue on the next page load.
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    products = list(_sale_product_qs(dept))
    all_recipes = _annotate_recipe_roles(
        list(Recipe.objects.filter(archived=False).order_by("code")))

    unresolved = []
    n_sage_unconfirmed = 0
    for p in products:
        if p.link_confirmed:
            continue
        unresolved.append({
            "product": p,
            "suggestions": _recipe_suggestions(p.name, all_recipes),
        })
        if p.link_source == SaleProduct.SAGE:
            n_sage_unconfirmed += 1

    return render(request, "stock/sale_product_link_review.html", {
        "unresolved": unresolved,
        "n_unresolved": len(unresolved),
        "n_sage_unconfirmed": n_sage_unconfirmed,
        "all_recipes": all_recipes,
        "recipe_picker_payload": _recipe_picker_payload(all_recipes),
        # Products can link to each other (Pack/N → Loose etc.) so the
        # link-review picker offers a product-typed search too. Exclude
        # archived rows and never let a product target itself; per-row
        # exclusion is enforced client- and server-side.
        "product_picker_payload": _product_picker_payload(
            SaleProduct.objects.filter(department=dept)),
        "link_unit_choices": SaleProduct.LINK_UNIT_CHOICES,
    })


@require_POST
@login_required
def sale_product_link_set(request, pk):
    """Set or clear the quantified, polymorphic link via review/detail.

    Accepts the polymorphic form fields parsed by
    ``_parse_link_form``: ``link_target_type`` ("recipe" / "product"),
    ``recipe_id`` / ``product_id``, ``link_quantity``, ``link_unit``.
    Backwards-compat: a POST with only ``recipe_id`` (the legacy
    one-click suggestion confirm) still works — it lands as
    "recipe + qty 1 + count". Whatever lands, the link is flipped
    ``link_source=manual`` and ``link_confirmed=True`` so re-imports
    never override the operator's pick. Clearing (empty target) also
    flips to manual — the deliberate "none of these apply" survives
    re-import.
    """
    product = get_object_or_404(SaleProduct, pk=pk)
    if product.department and not product.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    link_recipe, link_product, quantity, unit, error = _parse_link_form(request.POST)
    if error:
        messages.error(request, error)
        return redirect("sale_product_link_review")
    if link_product is not None and link_product.pk == product.pk:
        messages.error(request, "A product can't link to itself.")
        return redirect("sale_product_link_review")
    has_target = link_recipe is not None or link_product is not None
    product.link_recipe = link_recipe
    product.link_product = link_product
    product.link_quantity = quantity if has_target else Decimal("1")
    product.link_unit = unit if has_target else SaleProduct.COUNT
    product.link_source = SaleProduct.MANUAL
    product.link_confirmed = True
    product.save(update_fields=[
        "link_recipe", "link_product", "link_quantity", "link_unit",
        "link_source", "link_confirmed"])
    if has_target:
        if link_recipe is not None:
            target_label = f"{link_recipe.code} — {link_recipe.name}"
        else:
            target_label = link_product.name
        unit_label = dict(SaleProduct.LINK_UNIT_CHOICES).get(unit, unit)
        msg = (f"Linked '{product.name}' to {target_label} "
               f"({quantity} {unit_label}).")
    else:
        msg = f"Cleared the link on '{product.name}'."
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


# ---- orders (chunk 1: model + manual CRUD, no import yet) ----
def _orders_qs(dept):
    return (Order.objects.filter(department=dept)
            .select_related("customer")
            .prefetch_related("lines__sale_product")
            .order_by("-order_date", "-id"))


def _parse_order_date(raw):
    """Parse a YYYY-MM-DD string from the form, defaulting to today.

    Bad / empty input falls back to today's date — the form's
    ``<input type="date">`` should always supply a valid value but be
    defensive in case a hand-crafted POST lands.
    """
    raw = (raw or "").strip()
    if not raw:
        return datetime.date.today()
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        return datetime.date.today()


def _collect_order_lines(post, dept):
    """Pull parallel ``product_id[]`` / ``qty_ordered[]`` arrays from POST.

    Returns ``(lines, error)`` where ``lines`` is a list of
    ``{sale_product, qty}`` dicts (skipping empty rows) and ``error``
    is the first user-facing problem found — invalid quantity, unknown
    product, cross-department selection, or a duplicate product
    appearing twice on the same order. The view shows the error and
    re-renders the form with the operator's input intact.
    """
    pids = post.getlist("product_id")
    qtys = post.getlist("qty_ordered")
    pairs = list(zip(pids, qtys))
    out = []
    seen = set()
    for raw_pid, raw_qty in pairs:
        raw_pid = (raw_pid or "").strip()
        raw_qty = (raw_qty or "").strip()
        if not raw_pid and not raw_qty:
            # Wholly empty row — skip silently (template renders spare
            # blank slots so the operator can grow the line list).
            continue
        if not raw_pid:
            return [], "Pick a product for every line with a quantity."
        if not raw_qty:
            return [], "Enter a quantity for every line with a product."
        try:
            sp = SaleProduct.objects.get(pk=raw_pid, department=dept)
        except (SaleProduct.DoesNotExist, ValueError):
            return [], "One of the lines points at a product that isn't in this department."
        if sp.pk in seen:
            return [], (f"'{sp.name}' appears more than once on this order — "
                        "combine the quantities into one line.")
        seen.add(sp.pk)
        try:
            qty = Decimal(raw_qty)
        except InvalidOperation:
            return [], f"Quantity '{raw_qty}' isn't a number."
        if qty <= 0:
            return [], f"Quantity for {sp.name} must be greater than zero."
        out.append({"sale_product": sp, "qty": qty})
    return out, None


def _order_filter_qs(qs, customer_pk, date_str):
    if customer_pk:
        qs = qs.filter(customer_id=customer_pk)
    if date_str:
        try:
            qs = qs.filter(order_date=datetime.date.fromisoformat(date_str))
        except ValueError:
            pass
    return qs


def _monday_of(d):
    """Return the Monday that begins the calendar week containing ``d``.

    Python's ``date.weekday()`` is 0 for Monday … 6 for Sunday, so
    subtracting ``weekday()`` days always lands on Monday — the
    week-commencing date the orders system uses everywhere it groups
    by week. Pure derivation; nothing is stored.
    """
    return d - datetime.timedelta(days=d.weekday())


def _default_week_start(dept):
    """Pick a sensible default week for the orders page.

    Today's week if any orders fall in it (so a fresh visit lands on
    the action-rich one); otherwise the week of the most recent order
    so the operator sees their most recent activity; falling back to
    today's week when the dept has no orders at all.
    """
    today = datetime.date.today()
    this_start = _monday_of(today)
    this_end = this_start + datetime.timedelta(days=6)
    if Order.objects.filter(
            department=dept,
            order_date__range=(this_start, this_end)).exists():
        return this_start
    latest = (Order.objects.filter(department=dept)
              .order_by("-order_date").only("order_date").first())
    if latest is not None:
        return _monday_of(latest.order_date)
    return this_start


@login_required
def financials_home(request):
    """Channel split (Internal vs Wholesale) for a week range.

    Defaults to the full data window — earliest week with orders →
    latest. The two ``?from=YYYY-MM-DD&to=YYYY-MM-DD`` params snap
    to their Monday so any day within a week resolves to that week.
    BAKERY INTERNAL USE + BAKERY WASTAGE (Customer.is_internal) are
    EXCLUDED from every total here; they're the bakery's own
    consumption, not external demand.
    """
    from .financials import (
        available_week_range, per_customer_in_channel,
        per_week_split, range_totals,
    )
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")

    default_from, default_to = available_week_range(dept)

    def _snap(raw, fallback):
        raw = (raw or "").strip()
        if not raw:
            return fallback
        try:
            return _monday_of(datetime.date.fromisoformat(raw))
        except ValueError:
            return fallback

    from_wc = _snap(request.GET.get("from"), default_from)
    to_wc = _snap(request.GET.get("to"), default_to)
    if to_wc < from_wc:
        # Operator typo — silently swap rather than show an empty page.
        from_wc, to_wc = to_wc, from_wc

    totals = range_totals(dept, from_wc, to_wc)
    weekly = per_week_split(dept, from_wc, to_wc)
    wholesale_rows = per_customer_in_channel(
        dept, Customer.WHOLESALE, from_wc, to_wc)
    internal_rows = per_customer_in_channel(
        dept, Customer.INTERNAL, from_wc, to_wc)

    # CSS bar widths — the headline split uses two segments summing to
    # 100%; the weekly trend scales each bar to the largest week so
    # the eye reads the peak as full-height. Computed here, not in
    # the template, so the template stays purely declarative.
    total = totals["total"] or Decimal("1")
    pct_internal = (totals["internal"] / total * 100) if totals["total"] else Decimal("0")
    pct_wholesale = (totals["wholesale"] / total * 100) if totals["total"] else Decimal("0")
    max_week_total = max((w["total"] for w in weekly), default=Decimal("0"))
    for w in weekly:
        scale = (w["total"] / max_week_total * 100
                 if max_week_total else Decimal("0"))
        w["bar_pct"] = float(scale)
        if w["total"]:
            w["bar_internal_pct"] = float(w["internal"] / w["total"] * 100)
            w["bar_wholesale_pct"] = float(w["wholesale"] / w["total"] * 100)
        else:
            w["bar_internal_pct"] = 0.0
            w["bar_wholesale_pct"] = 0.0

    return render(request, "stock/financials.html", {
        "from_wc": from_wc,
        "to_wc": to_wc,
        "default_from": default_from,
        "default_to": default_to,
        "totals": totals,
        "pct_internal": pct_internal.quantize(Decimal("0.1")),
        "pct_wholesale": pct_wholesale.quantize(Decimal("0.1")),
        "weekly": weekly,
        "wholesale_rows": wholesale_rows,
        "internal_rows": internal_rows,
    })


@login_required
def orders_home(request):
    """Orders list grouped by week, then by day (Mon–Sun).

    Orders are stored per-date — the "week commencing" Monday is always
    DERIVED from each order's date, never stored as a separate field.
    The view normalises any ``?week=YYYY-MM-DD`` query (the operator
    can paste any day within the week and we snap to its Monday); when
    no week is given we pick a sensible default via
    ``_default_week_start``.

    Customer + date filters layer ON TOP of the week — combining them
    narrows further inside the selected week, so a URL like
    ``/orders/?week=2026-05-18&customer=3&date=2026-05-20`` is the
    "Garden Cafe orders for Wednesday this week" view.

    The week summary (total orders / total value / per-day totals) is
    enough to see the week's shape at a glance; full production
    aggregation is a later chunk.
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")
    customer_pk = (request.GET.get("customer") or "").strip()
    date_str = (request.GET.get("date") or "").strip()
    raw_week = (request.GET.get("week") or "").strip()
    if raw_week:
        try:
            week_start = _monday_of(datetime.date.fromisoformat(raw_week))
        except ValueError:
            week_start = _default_week_start(dept)
    else:
        week_start = _default_week_start(dept)
    week_end = week_start + datetime.timedelta(days=6)

    qs = _orders_qs(dept).filter(order_date__range=(week_start, week_end))
    qs = _order_filter_qs(qs, customer_pk, date_str)
    orders = list(qs)

    # Per-day buckets (Mon–Sun) — the rendered week always shows the
    # full strip even when a day is empty, so the operator sees the
    # week's shape rather than a sparse list. Day totals split into
    # external (the headline revenue) and internal (BAKERY INTERNAL USE
    # + BAKERY WASTAGE etc. — anything Customer.is_internal). Templates
    # show external on the tiles; internal surfaces as a subtotal line
    # underneath so the bakery's own consumption stays visible without
    # inflating the revenue figure.
    days = []
    for i in range(7):
        day = week_start + datetime.timedelta(days=i)
        day_orders = [o for o in orders if o.order_date == day]
        day_total_external = sum(
            (o.total_value() for o in day_orders
             if not o.customer.is_internal), Decimal("0"))
        day_total_internal = sum(
            (o.total_value() for o in day_orders
             if o.customer.is_internal), Decimal("0"))
        days.append({
            "date": day,
            "label": day.strftime("%A"),
            "is_today": day == datetime.date.today(),
            "orders": day_orders,
            "count": len(day_orders),
            "total": day_total_external,
            "total_internal": day_total_internal,
        })

    week_total_orders = len(orders)
    week_total_value = sum((d["total"] for d in days), Decimal("0"))
    week_total_internal = sum(
        (d["total_internal"] for d in days), Decimal("0"))

    customers = list(Customer.objects.filter(department=dept).order_by("name"))
    today_week = _monday_of(datetime.date.today())

    # If a customer is picked AND no specific day filter is set, build
    # the spreadsheet-style grid (products as rows × Mon..Sun columns).
    # The grid is the main view for a single customer's week; the
    # per-day strip stays available as a secondary read.
    grid = None
    selected_customer = None
    if customer_pk:
        selected_customer = next(
            (c for c in customers if str(c.pk) == customer_pk), None)
        if selected_customer is not None and not date_str:
            grid = _build_order_grid(orders, days)

    # When no customer is picked the list of dept customers doubles as
    # a "drill into a customer's week" picker. Active customers (those
    # with orders THIS week) come first with their order count + total;
    # inactive ones still render below (dimmed in the template) so any
    # customer remains one click away. Order within each group is
    # alphabetical so the eye scans predictably.
    customer_links = []
    if not customer_pk:
        for c in customers:
            cust_orders = [o for o in orders if o.customer_id == c.pk]
            n_orders = len(cust_orders)
            total_value = sum((o.total_value() for o in cust_orders),
                              Decimal("0"))
            customer_links.append({
                "customer": c,
                "n_orders": n_orders,
                "total_value": total_value,
                "active": n_orders > 0,
                "is_internal": c.is_internal,
            })
        customer_links.sort(
            key=lambda cl: (0 if cl["active"] else 1,
                            cl["customer"].name.lower()))

    # When ?date= narrows to a single day, surface that day's orders
    # as a one-day list (the replacement for the old verbose 7-card
    # strip — same edit / delete / detail links, but only for the day
    # the operator actually filtered to).
    filtered_day = None
    if date_str:
        try:
            d = datetime.date.fromisoformat(date_str)
            filtered_day = next(
                (day for day in days if day["date"] == d), None)
        except ValueError:
            filtered_day = None

    return render(request, "stock/orders_bp.html", {
        "orders": orders,
        "customers": customers,
        "filter_customer": customer_pk,
        "filter_date": date_str,
        "week_start": week_start,
        "week_end": week_end,
        "prev_week": week_start - datetime.timedelta(days=7),
        "next_week": week_start + datetime.timedelta(days=7),
        "today_week": today_week,
        "on_today_week": week_start == today_week,
        "days": days,
        "week_total_orders": week_total_orders,
        "week_total_value": week_total_value,
        "week_total_internal": week_total_internal,
        "selected_customer": selected_customer,
        "grid": grid,
        "customer_links": customer_links,
        "filtered_day": filtered_day,
    })


def _build_order_grid(orders, days):
    """Build a spreadsheet-style products × days grid for one customer.

    ``orders`` is the dept-filtered list for the selected week and
    customer; ``days`` is the Mon..Sun strip the view already
    computed. Returns ``{rows, day_totals, day_values, grand_total,
    grand_value}`` where each row is one product (linked OR
    discontinued / historical) with:
      * ``product`` — a dict ``{name, sage_number, price,
        sale_product}``; ``sale_product`` is the catalogue entry (or
        None for a historical line whose product no longer exists),
        and ``price`` is the SNAPSHOTTED ``unit_price`` from the
        order line — not the live catalogue value
      * ``cells`` — list of 7 ``{qty}`` dicts aligned to Mon..Sun
        (qty is a Decimal or ``None`` for blank cells, matching the
        bakery sheet's blanks-for-zero convention)
      * ``total_qty`` — sum of cells
      * ``total_value`` — sum of ``line.line_value`` for the grouped
        lines (uses each line's snapshotted unit price so
        discontinued products contribute their original value)

    Rows are sorted by SKU/Sage when present, then by name — mirrors
    the sheet's order. Lines without a sale_product (historical /
    discontinued) group together by ``(product_name, unit_price)``
    so the same deprecated SKU on different days lands in one row.
    """
    # row_key → {name, sage_number, price, sale_product}
    products = {}
    # row_key → list of 7 Decimal-or-None qtys (Mon..Sun)
    qtys = {}
    # row_key → running line value sum (Decimal)
    values = {}

    for o in orders:
        # day index relative to week_start (Mon = 0, ..., Sun = 6).
        try:
            day_idx = next(i for i, d in enumerate(days)
                           if d["date"] == o.order_date)
        except StopIteration:
            continue
        for line in o.lines.select_related("sale_product").all():
            sp = line.sale_product
            line_price = line.unit_price
            if sp is not None:
                row_key = ("sp", sp.pk)
                if row_key not in products:
                    products[row_key] = {
                        "name": line.product_name or sp.name,
                        "sage_number": sp.sage_number,
                        "price": line_price if line_price is not None else sp.price,
                        "sale_product": sp,
                    }
            else:
                # Discontinued / unlinked: group by (name, price) so
                # the same deprecated SKU lands in one row even if it
                # appears on several days.
                row_key = ("unlinked",
                           (line.product_name or "").lower(),
                           str(line_price) if line_price is not None else "")
                if row_key not in products:
                    products[row_key] = {
                        "name": line.product_name or "",
                        "sage_number": "",
                        "price": line_price,
                        "sale_product": None,
                    }
            if row_key not in qtys:
                qtys[row_key] = [None] * 7
                values[row_key] = Decimal("0")
            qty = line.qty_ordered or Decimal("0")
            cur = qtys[row_key][day_idx]
            qtys[row_key][day_idx] = (cur or Decimal("0")) + qty
            lv = line.line_value
            if lv is not None:
                values[row_key] += lv

    def _sort_key(item):
        row_key, p = item
        sage = (p.get("sage_number") or "").strip()
        if sage and sage.isdigit() and sage != "0":
            return (0, int(sage), "")
        return (1, 0, (p.get("name") or "").lower())

    rows = []
    day_totals = [Decimal("0")] * 7
    day_values = [Decimal("0")] * 7
    grand_total = Decimal("0")
    grand_value = Decimal("0")
    for row_key, p in sorted(products.items(), key=_sort_key):
        cells = []
        total_qty = Decimal("0")
        for i in range(7):
            q = qtys[row_key][i]
            cells.append({"qty": q})
            if q is not None:
                day_totals[i] += q
                total_qty += q
                if p["price"] is not None:
                    day_values[i] += (q * p["price"])
        row_value = values[row_key].quantize(Decimal("0.01"))
        total_value = row_value if values[row_key] != Decimal("0") or p["price"] is not None else None
        # Only show "—" for truly priceless rows; even £0 totals
        # still render as "£0.00".
        if p["price"] is None and values[row_key] == Decimal("0"):
            total_value = None
        grand_total += total_qty
        if total_value is not None:
            grand_value += total_value
        rows.append({
            "product": p,
            "cells": cells,
            "total_qty": total_qty,
            "total_value": total_value,
        })
    return {
        "rows": rows,
        "day_totals": day_totals,
        "day_values": [v.quantize(Decimal("0.01")) for v in day_values],
        "grand_total": grand_total,
        "grand_value": grand_value.quantize(Decimal("0.01")),
    }


@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if order.department and not order.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    lines = list(order.lines.select_related(
        "sale_product__link_recipe", "sale_product__link_product"))
    return render(request, "stock/order_detail.html", {
        "order": order,
        "lines": lines,
        "total_value": order.total_value(),
        "resolved": order.resolved_consumption(),
    })


def _order_form_context(form, mode, dept, *, order=None, error=None):
    """Build the create / edit form context with the customer list +
    SaleProduct picker payload for the per-line autocomplete."""
    customers = list(Customer.objects.filter(department=dept).order_by("name"))
    products_qs = SaleProduct.objects.filter(department=dept).order_by("name")
    return {
        "form": form,
        "mode": mode,
        "order": order,
        "error": error,
        "customers": customers,
        "product_picker_payload": _product_picker_payload(products_qs),
    }


def _render_order_form(request, form, mode, dept, *, order=None, error=None):
    return render(request, "stock/order_form.html",
                  _order_form_context(form, mode, dept,
                                      order=order, error=error))


def _line_rows_for_form(lines):
    """Pre-fill rows for the line editor.

    ``lines`` is a list of either OrderLine instances (edit mode) or
    plain dicts from a re-render after a validation failure. Returns
    a list of dicts with ``product_id`` / ``product_label`` / ``qty``.
    """
    out = []
    for ln in lines:
        if isinstance(ln, OrderLine):
            sp = ln.sale_product
            out.append({
                "product_id": str(sp.pk),
                "product_label": sp.name,
                "qty": str(ln.qty_ordered),
            })
        else:
            sp = ln.get("sale_product")
            out.append({
                "product_id": str(sp.pk) if sp else "",
                "product_label": sp.name if sp else "",
                "qty": str(ln.get("qty") or ""),
            })
    # Pad with a few spare blanks so the operator can keep adding.
    while len(out) < 3:
        out.append({"product_id": "", "product_label": "", "qty": ""})
    return out


@login_required
def order_new(request):
    """Create a new order with one or more lines.

    Customer + date + parallel ``product_id`` / ``qty_ordered`` arrays
    from the line repeater. Department-scoped: customers + products
    are filtered to the current department; an out-of-dept pick is
    rejected via the validator.
    """
    dept = current_department(request)
    if dept is None:
        return render(request, "stock/no_department.html")

    if request.method == "POST":
        form = {
            "customer_id": (request.POST.get("customer_id") or "").strip(),
            "order_date": (request.POST.get("order_date") or "").strip(),
            "note": (request.POST.get("note") or "").strip(),
            "lines": [],
        }
        error = None
        customer = None
        if not form["customer_id"]:
            error = "Pick a customer."
        else:
            customer = (Customer.objects.filter(
                pk=form["customer_id"], department=dept).first())
            if customer is None:
                error = "That customer isn't in this department."
        lines = []
        if error is None:
            lines, line_error = _collect_order_lines(request.POST, dept)
            if line_error:
                error = line_error
            elif not lines:
                error = "Add at least one product line."
        if error:
            form["lines"] = _line_rows_for_form([
                {"sale_product": ln.get("sale_product"),
                 "qty": ln.get("qty")} for ln in lines
            ] if lines else _zip_form_lines(request.POST))
            return _render_order_form(request, form, "new", dept, error=error)

        with transaction.atomic():
            order = Order.objects.create(
                customer=customer,
                order_date=_parse_order_date(form["order_date"]),
                department=dept,
                note=form["note"],
            )
            for ln in lines:
                OrderLine.objects.create(
                    order=order,
                    sale_product=ln["sale_product"],
                    qty_ordered=ln["qty"],
                )
        messages.success(request, f"Created order for {customer.name}.")
        return redirect("order_detail", pk=order.pk)

    form = {
        "customer_id": "",
        "order_date": datetime.date.today().isoformat(),
        "note": "",
        "lines": _line_rows_for_form([]),
    }
    return _render_order_form(request, form, "new", dept)


def _zip_form_lines(post):
    """Turn parallel product_id[] / qty_ordered[] arrays from a failed
    POST back into the dict shape ``_line_rows_for_form`` expects.

    Used to redisplay the user's input verbatim on validation failure.
    Empty product rows still render so the operator can fix them.
    """
    pids = post.getlist("product_id")
    qtys = post.getlist("qty_ordered")
    out = []
    for raw_pid, raw_qty in zip(pids, qtys):
        sp = None
        if raw_pid:
            sp = SaleProduct.objects.filter(pk=raw_pid).first()
        out.append({"sale_product": sp, "qty": raw_qty})
    return out


@login_required
def order_edit(request, pk):
    """Edit an order's customer/date/note and its lines.

    Lines are rebuilt from the form on save: every existing OrderLine
    is wiped and the POST's product_id/qty_ordered pairs are recreated.
    This is the simplest correct behaviour while only ``qty_ordered``
    is tracked. When ``qty_sent`` lands in a later chunk the rebuild
    will need to preserve per-line state — leave a TODO there then.
    """
    order = get_object_or_404(Order, pk=pk)
    if order.department and not order.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    dept = order.department or current_department(request)

    if request.method == "POST":
        form = {
            "customer_id": (request.POST.get("customer_id") or "").strip(),
            "order_date": (request.POST.get("order_date") or "").strip(),
            "note": (request.POST.get("note") or "").strip(),
            "lines": [],
        }
        error = None
        customer = None
        if not form["customer_id"]:
            error = "Pick a customer."
        else:
            customer = (Customer.objects.filter(
                pk=form["customer_id"], department=dept).first())
            if customer is None:
                error = "That customer isn't in this department."
        lines = []
        if error is None:
            lines, line_error = _collect_order_lines(request.POST, dept)
            if line_error:
                error = line_error
            elif not lines:
                error = "Add at least one product line."
        if error:
            form["lines"] = _line_rows_for_form([
                {"sale_product": ln.get("sale_product"),
                 "qty": ln.get("qty")} for ln in lines
            ] if lines else _zip_form_lines(request.POST))
            return _render_order_form(request, form, "edit", dept,
                                      order=order, error=error)

        with transaction.atomic():
            order.customer = customer
            order.order_date = _parse_order_date(form["order_date"])
            order.note = form["note"]
            order.save()
            order.lines.all().delete()
            for ln in lines:
                OrderLine.objects.create(
                    order=order,
                    sale_product=ln["sale_product"],
                    qty_ordered=ln["qty"],
                )
        messages.success(request, f"Saved changes to order #{order.pk}.")
        return redirect("order_detail", pk=order.pk)

    existing = list(order.lines.select_related("sale_product"))
    form = {
        "customer_id": str(order.customer_id),
        "order_date": order.order_date.isoformat(),
        "note": order.note,
        "lines": _line_rows_for_form(existing),
    }
    return _render_order_form(request, form, "edit", dept, order=order)


@require_POST
@login_required
def order_delete(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if order.department and not order.department.accessible_to(request.user):
        return HttpResponseForbidden("Not your department.")
    label = str(order)
    order.delete()
    messages.success(request, f"Deleted order {label}.")
    return redirect("orders")


# ---------------------------------------------------------------------------
# React dashboard SPA shell.
#
# /dashboard/ (and any sub-route under it) serves the pre-built Vite
# bundle's `index.html`. The bundle is committed to git under
# frontend/dist/ because Render's free-tier build env doesn't ship Node;
# the build step runs locally before commit (npm run build) and Django
# just hands the file to the browser. Hashed assets in the HTML resolve
# to /static/dashboard/assets/... via WhiteNoise + STATICFILES_DIRS.
# ---------------------------------------------------------------------------

from django.conf import settings as _settings
from django.http import HttpResponse, HttpResponseNotFound


@login_required
def spa_dashboard(request, *args, **kwargs):
    """Serve the React dashboard SPA. Catches every URL under /dashboard/
    so client-side routes (Phase B) deep-link correctly without 404ing.
    """
    index_path = _settings.BASE_DIR / "frontend" / "dist" / "index.html"
    try:
        html = index_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Build hasn't been run yet. Render a clear actionable message
        # instead of a stack trace so the dev knows what to do.
        return HttpResponseNotFound(
            "<h1>Dashboard SPA not built</h1>"
            "<p>Run <code>cd frontend &amp;&amp; npm install &amp;&amp; "
            "npm run build</code> and commit <code>frontend/dist/</code>.</p>",
            content_type="text/html",
        )
    return HttpResponse(html)

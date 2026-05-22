import datetime
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum
from django.http import HttpResponseForbidden
from .models import Supplier, Product, SupplierPrice, Stocktake, StockLine, Department, Delivery, Batch, Adjustment
from .ai_extract import extract_lines, auto_match, ExtractError


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
    return render(request, "stock/products.html", {
        "products": dept.products.prefetch_related("prices__supplier"),
        "suppliers": Supplier.objects.all(),
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

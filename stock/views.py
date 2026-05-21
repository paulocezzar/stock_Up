import datetime
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Count
from .models import Supplier, Product, SupplierPrice, Stocktake, StockLine


def _dec(raw):
    raw = (raw or "").strip()
    if raw == "":
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def dashboard(request):
    products = list(Product.objects.prefetch_related("prices__supplier"))
    rows, below = [], 0
    for p in products:
        line = p.latest_line
        cur = line.current if line else None
        low = cur is not None and cur < p.minimum
        if low:
            below += 1
        rows.append({"p": p, "cheap": p.cheapest_price, "current": cur,
                     "low": low, "needed": (p.minimum - cur) if low else None})
    rows.sort(key=lambda r: (not r["low"], r["p"].name.lower()))
    latest = Stocktake.objects.first()
    return render(request, "stock/dashboard.html", {
        "rows": rows, "below": below, "latest": latest,
        "n_products": len(products),
        "value": latest.total_value if latest else Decimal("0"),
    })


# ---- suppliers ----
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


# ---- products ----
def products(request):
    if request.method == "POST":
        code = (request.POST.get("code") or "").strip() or None
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Name is required.")
            return redirect("products")
        unit = request.POST.get("unit") or "g"
        defaults = {"name": name, "unit": unit,
                    "minimum": _dec(request.POST.get("minimum")) or 0}
        if code:
            product, _ = Product.objects.update_or_create(code=code, defaults=defaults)
        else:
            product, created = Product.objects.get_or_create(name=name, code__isnull=True,
                                                             defaults=defaults)
            if not created:
                for k, v in defaults.items():
                    setattr(product, k, v)
                product.save()
        # optional inline supplier price
        sup = (request.POST.get("supplier") or "").strip()
        qty = _dec(request.POST.get("quantity"))
        cost = _dec(request.POST.get("cost"))
        if sup and qty and cost is not None:
            supplier, _ = Supplier.objects.get_or_create(name=sup)
            SupplierPrice.objects.update_or_create(
                product=product, supplier=supplier,
                defaults={"pack_weight": qty, "pack_price": cost})
            messages.success(request, f"Saved '{name}' with {sup} price.")
        else:
            messages.success(request, f"Saved '{name}'.")
        return redirect("products")
    return render(request, "stock/products.html", {
        "products": Product.objects.prefetch_related("prices__supplier"),
        "suppliers": Supplier.objects.all(),
    })


def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        sup = (request.POST.get("supplier") or "").strip()
        wt = _dec(request.POST.get("pack_weight"))
        pr = _dec(request.POST.get("pack_price"))
        if sup and wt and pr is not None:
            supplier, _ = Supplier.objects.get_or_create(name=sup)
            SupplierPrice.objects.update_or_create(
                product=product, supplier=supplier,
                defaults={"pack_weight": wt, "pack_price": pr})
            messages.success(request, f"Price from {sup} saved.")
        else:
            messages.error(request, "Supplier, pack weight and price are all required.")
        return redirect("product_detail", pk=pk)
    return render(request, "stock/product_detail.html", {
        "product": product,
        "prices": product.prices.select_related("supplier").all(),
        "suppliers": Supplier.objects.all(),
        "history": product.history(),
    })


@require_POST
def price_delete(request, price_id):
    price = get_object_or_404(SupplierPrice, pk=price_id)
    pk = price.product_id
    price.delete()
    return redirect("product_detail", pk=pk)


# ---- stocktakes ----
def stocktakes(request):
    if request.method == "POST":
        st = Stocktake.objects.create(
            date=datetime.date.today(),
            completed_by=(request.POST.get("completed_by") or "").strip(),
        )
        # pre-create a line per product
        StockLine.objects.bulk_create(
            [StockLine(stocktake=st, product=p) for p in Product.objects.all()])
        return redirect("count", pk=st.pk)
    return render(request, "stock/stocktakes.html", {
        "stocktakes": Stocktake.objects.all(),
        "has_products": Product.objects.exists(),
    })


def count(request, pk):
    st = get_object_or_404(Stocktake, pk=pk)
    existing = set(st.lines.values_list("product_id", flat=True))
    StockLine.objects.bulk_create(
        [StockLine(stocktake=st, product=p)
         for p in Product.objects.exclude(id__in=existing)])
    lines = list(st.lines.select_related("product").order_by("product__name"))
    return render(request, "stock/count.html", {"st": st, "lines": lines})


@require_POST
def save_count(request, line_id):
    line = get_object_or_404(StockLine, pk=line_id)
    line.current = _dec(request.POST.get("current"))
    line.save()
    return render(request, "stock/_line_status.html", {"line": line})

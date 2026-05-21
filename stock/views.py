import datetime
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from .models import Product, Stocktake, StockLine


def dashboard(request):
    products = list(Product.objects.prefetch_related("prices__supplier"))
    rows, below, total_value = [], 0, Decimal("0")
    latest = Stocktake.objects.first()
    for p in products:
        cheap = p.cheapest_price
        line = p.latest_count
        cur = line.current if line else None
        val = line.value if line else None
        if val:
            total_value += val
        low = cur is not None and cur < p.minimum
        if low:
            below += 1
        rows.append({"p": p, "cheap": cheap, "current": cur,
                     "low": low, "needed": (p.minimum - cur) if low else None,
                     "value": val})
    rows.sort(key=lambda r: (not r["low"], r["p"].name.lower()))
    return render(request, "stock/dashboard.html", {
        "rows": rows, "below": below, "total_value": total_value,
        "latest": latest, "n_products": len(products),
    })


def count(request, pk=None):
    st = Stocktake.objects.first()
    if st is None:
        st = Stocktake.objects.create(date=datetime.date.today(), note="New count")
    # ensure a line exists for every product
    existing = set(st.lines.values_list("product_id", flat=True))
    missing = [StockLine(stocktake=st, product=p)
               for p in Product.objects.exclude(id__in=existing)]
    StockLine.objects.bulk_create(missing)
    lines = list(st.lines.select_related("product").order_by("product__name"))
    return render(request, "stock/count.html", {"st": st, "lines": lines})


@require_POST
def save_count(request, line_id):
    line = get_object_or_404(StockLine, pk=line_id)
    raw = request.POST.get("current", "").strip()
    line.current = Decimal(raw) if raw else None
    line.save()
    return render(request, "stock/_line_status.html", {"line": line})

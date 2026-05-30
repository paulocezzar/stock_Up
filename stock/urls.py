from django.urls import path, re_path
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView
from . import views
from .api import (
    business_performance_export_csv, business_performance_summary,
    dashboard_export_csv, dashboard_summary,
)

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="stock/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    # Root retired: / now redirects to /home/ (the merged landing page). The
    # dashboard view + stock/dashboard.html stay in the tree for now, unused.
    path("", RedirectView.as_view(pattern_name="home", permanent=False), name="dashboard"),
    path("home/", views.home, name="home"),
    path("stock/", views.stock_home, name="stock_home"),
    path("recipes/", views.recipes_home, name="recipes"),
    path("recipes/upload/", views.recipe_upload, name="recipe_upload"),
    path("recipes/upload/preview/", views.recipe_upload_preview, name="recipe_upload_preview"),
    path("recipes/bulk-delete/", views.recipe_bulk_delete, name="recipe_bulk_delete"),
    path("recipes/bulk-archive/", views.recipe_bulk_archive, name="recipe_bulk_archive"),
    path("recipes/bulk-restore/", views.recipe_bulk_restore, name="recipe_bulk_restore"),
    path("recipes/<int:pk>/", views.recipe_detail, name="recipe_detail"),
    path("recipes/<int:pk>/edit/", views.recipe_edit, name="recipe_edit"),
    path("recipes/<int:pk>/archive/", views.recipe_archive, name="recipe_archive"),
    path("recipes/<int:pk>/restore/", views.recipe_restore, name="recipe_restore"),
    path("recipes/<int:pk>/delete/", views.recipe_delete, name="recipe_delete"),
    path("recipes/<int:pk>/sold/", views.recipe_set_sold, name="recipe_set_sold"),
    path("profile/", views.profile, name="profile"),
    path("switch/<int:pk>/", views.switch_department, name="switch_department"),
    path("suppliers/", views.suppliers, name="suppliers"),
    path("suppliers/<int:pk>/delete/", views.supplier_delete, name="supplier_delete"),
    path("products/", views.products, name="products"),
    path("packaging/", views.packaging, name="packaging"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("price/<int:price_id>/delete/", views.price_delete, name="price_delete"),
    path("reorder/", views.reorder, name="reorder"),
    path("reorder/csv/", views.reorder_csv, name="reorder_csv"),
    path("stocktakes/", views.stocktakes, name="stocktakes"),
    path("stocktakes/<int:pk>/count/", views.count, name="count"),
    path("stocktakes/<int:pk>/csv/", views.stocktake_csv, name="stocktake_csv"),
    path("count/line/<int:line_id>/", views.save_count, name="save_count"),
    path("deliveries/", views.deliveries, name="deliveries"),
    path("deliveries/new/", views.delivery_new, name="delivery_new"),
    path("deliveries/scan/", views.delivery_scan, name="delivery_scan"),
    path("deliveries/<int:pk>/", views.delivery_detail, name="delivery_detail"),
    # TEMP: Wave B design-system previews (Goods In: list / new / scan /
    # detail). Remove all four on cutover. URL paths stay /deliveries... for
    # now; the /goods-in/ rename happens at cutover.
    path("goods-in-preview/", views.deliveries_preview, name="deliveries_preview"),
    path("goods-in/new-preview/", views.delivery_new_preview, name="delivery_new_preview"),
    path("goods-in/scan-preview/", views.delivery_scan_preview, name="delivery_scan_preview"),
    path("goods-in/<int:pk>/preview/", views.delivery_detail_preview, name="delivery_detail_preview"),
    path("adjustments/", views.adjustments, name="adjustments"),
    path("customers/", views.customers_internal, name="customers"),
    path("customers/wholesale/", views.customers_wholesale, name="customers_wholesale"),
    path("customers/new/", views.customer_new, name="customer_new"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/edit/", views.customer_edit, name="customer_edit"),
    path("customers/<int:pk>/delete/", views.customer_delete, name="customer_delete"),
    path("customers/<int:pk>/type/", views.customer_set_type, name="customer_set_type"),
    # Sale products (sellable SKUs) — distinct from /products/ (ingredients).
    path("sale-products/", views.sale_products, name="sale_products"),
    path("sale-products/new/", views.sale_product_new, name="sale_product_new"),
    path("sale-products/link-review/", views.sale_product_link_review,
         name="sale_product_link_review"),
    path("sale-products/confirm-sage/", views.sale_product_confirm_sage_matches,
         name="sale_product_confirm_sage"),
    path("sale-products/<int:pk>/", views.sale_product_detail,
         name="sale_product_detail"),
    path("sale-products/<int:pk>/edit/", views.sale_product_edit,
         name="sale_product_edit"),
    path("sale-products/<int:pk>/delete/", views.sale_product_delete,
         name="sale_product_delete"),
    path("sale-products/<int:pk>/link/", views.sale_product_link_set,
         name="sale_product_link_set"),
    # Financials — channel split (Internal vs Wholesale) over a week
    # range. Read-only; aggregates from existing OrderLine snapshots.
    # /financials/ retired: redirects to the Business Performance SPA, which
    # carries the channel split / trends / customer breakdowns. The
    # financials_home view + template stay in the tree, unused. Query string
    # preserved so from/to range params survive the hop.
    path("financials/", RedirectView.as_view(
        pattern_name="business_performance_dashboard",
        permanent=False, query_string=True), name="financials"),
    # Orders — chunk 1: model + manual CRUD. No import yet.
    path("orders/", views.orders_home, name="orders"),
    path("orders/new/", views.order_new, name="order_new"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/edit/", views.order_edit, name="order_edit"),
    path("orders/<int:pk>/delete/", views.order_delete, name="order_delete"),
    # Business Performance SPA + its DRF backend. The re_path catches any
    # client-side sub-route under /business-performance-dashboard/ so it
    # deep-links to the same index.html. (The /api/dashboard/* endpoints are
    # still consumed by the SPA's App.jsx code paths.)
    path("api/dashboard/summary/", dashboard_summary, name="api_dashboard_summary"),
    path("api/dashboard/export.csv", dashboard_export_csv,
         name="api_dashboard_export_csv"),
    path("api/business-performance/summary/", business_performance_summary,
         name="api_business_performance_summary"),
    path("api/business-performance/export.csv", business_performance_export_csv,
         name="api_business_performance_export_csv"),
    # /dashboard/ retired: it now redirects to the Business Performance SPA
    # route (App.jsx is left unused in the frontend tree). Query string
    # preserved so deep params survive the hop.
    path("dashboard/", RedirectView.as_view(
        pattern_name="business_performance_dashboard",
        permanent=False, query_string=True), name="spa_dashboard"),
    path("business-performance-dashboard/", views.spa_dashboard,
         name="business_performance_dashboard"),
    re_path(r"^business-performance-dashboard/.+$", views.spa_dashboard),
]

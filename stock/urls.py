from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="stock/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("switch/<int:pk>/", views.switch_department, name="switch_department"),
    path("suppliers/", views.suppliers, name="suppliers"),
    path("suppliers/<int:pk>/delete/", views.supplier_delete, name="supplier_delete"),
    path("products/", views.products, name="products"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("price/<int:price_id>/delete/", views.price_delete, name="price_delete"),
    path("reorder/", views.reorder, name="reorder"),
    path("reorder/csv/", views.reorder_csv, name="reorder_csv"),
    path("stocktakes/", views.stocktakes, name="stocktakes"),
    path("stocktakes/<int:pk>/count/", views.count, name="count"),
    path("count/line/<int:line_id>/", views.save_count, name="save_count"),
    path("deliveries/", views.deliveries, name="deliveries"),
    path("deliveries/new/", views.delivery_new, name="delivery_new"),
    path("deliveries/scan/", views.delivery_scan, name="delivery_scan"),
]

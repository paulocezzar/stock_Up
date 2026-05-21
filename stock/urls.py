from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("suppliers/", views.suppliers, name="suppliers"),
    path("products/", views.products, name="products"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("price/<int:price_id>/delete/", views.price_delete, name="price_delete"),
    path("stocktakes/", views.stocktakes, name="stocktakes"),
    path("stocktakes/<int:pk>/count/", views.count, name="count"),
    path("count/line/<int:line_id>/", views.save_count, name="save_count"),
]

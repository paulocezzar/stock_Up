from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("count/", views.count, name="count"),
    path("count/line/<int:line_id>/", views.save_count, name="save_count"),
]

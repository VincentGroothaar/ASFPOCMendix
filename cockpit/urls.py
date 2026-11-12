"""URL routes of the cockpit app."""

from django.urls import path

from cockpit import views

app_name = "cockpit"

urlpatterns = [
    path("", views.home, name="home"),
    path(
        "orders/<str:number>/requisitions/",
        views.requisition_create,
        name="requisition_create",
    ),
    path("requisitions/", views.requisition_list, name="requisition_list"),
    path("requisitions/<int:pk>/", views.requisition_detail, name="requisition_detail"),
]

"""URL routes of the cockpit app."""

from django.urls import path

from cockpit import views

app_name = "cockpit"

urlpatterns = [
    path("", views.home, name="home"),
    path("orders/", views.order_list, name="order_list"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("orders/<str:number>/", views.order_detail, name="order_detail"),
    path("plants/<str:plant>/refresh/", views.refresh_plant, name="refresh_plant"),
    path(
        "orders/<str:number>/requisitions/",
        views.requisition_create,
        name="requisition_create",
    ),
    path(
        "orders/<str:number>/requisitions/preview/",
        views.requisition_preview,
        name="requisition_preview",
    ),
    path(
        "orders/<str:number>/requisitions/panel/empty/",
        views.requisition_panel_empty,
        name="requisition_panel_empty",
    ),
    path(
        "orders/<str:number>/requisitions/<int:pk>/",
        views.requisition_panel,
        name="requisition_panel",
    ),
    path("requisitions/", views.requisition_list, name="requisition_list"),
    path("requisitions/<int:pk>/", views.requisition_detail, name="requisition_detail"),
]

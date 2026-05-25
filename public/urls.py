from django.urls import path
from public import views

app_name = "public"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("presupuesto/solicitar/", views.solicitar_presupuesto, name="solicitar_presupuesto"),
    path("presupuesto/gracias/", views.presupuesto_gracias, name="presupuesto_gracias"),
]

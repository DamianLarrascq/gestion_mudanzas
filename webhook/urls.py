from django.urls import path
from . import views

app_name = "webhook"

urlpatterns = [
    path("mp/notificacion/", views.mp_notificacion, name="mp_notificacion"),
    path("mp/success/",      views.mp_success,      name="mp_success"),
    path("mp/failure/",      views.mp_failure,      name="mp_failure"),
    path("mp/pending/",      views.mp_pending,      name="mp_pending"),
]
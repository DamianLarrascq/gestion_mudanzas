from django.urls import path
from .views import ChatbotWebView

urlpatterns = [
    # ... rutas existentes
    path("api/chatbot/mensaje/", ChatbotWebView.as_view(), name="chatbot_web"),
]
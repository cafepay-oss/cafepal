# chat/routing.py
from django.urls import path

from cafepay.api_v1.consumers import DispatchConsumer

websocket_urlpatterns = [
    path('ws/v1/', DispatchConsumer.DispatchConsumer),

]

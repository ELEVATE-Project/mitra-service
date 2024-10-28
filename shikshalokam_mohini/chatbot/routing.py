from django.urls import re_path
from .consumers.shikshalokam_bedrock_consumer import ShikshalokamBedrockConsumer


websocket_urlpatterns = [
    re_path(r"ws/shikshalokam_new/$", ShikshalokamBedrockConsumer.as_asgi()),
]

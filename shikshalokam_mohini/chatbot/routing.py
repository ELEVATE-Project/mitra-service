from django.urls import re_path
from .consumers.one_shot_bedrock_consumer import OneShotBedrockConsumer
from .consumers.shikshalokam_bedrock_consumer import ShikshalokamBedrockConsumer


websocket_urlpatterns = [
    re_path(r"ws/shikshalokam_new/$", ShikshalokamBedrockConsumer.as_asgi()),
    re_path(r"ws/shikshalokam_one_shot/$", OneShotBedrockConsumer.as_asgi()),
]

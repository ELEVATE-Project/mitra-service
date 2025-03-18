import os
from celery import Celery


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shikshalokam_mohini.settings')

app = Celery('shikshalokam_mohini', backend='redis://localhost', broker='redis://localhost')
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks([
    'chatbot.celery_tasks.shikshalokam_bedrock_tasks',
    'chatbot.celery_tasks.one_shot_bedrock_tasks',
    'chatbot.celery_tasks.common_chat_tasks',
    'chatbot.celery_tasks.reflection_bedrock_tasks',
    'chatbot.celery_tasks.mitra_bedrock_tasks',
    'chatbot.utils.story_utils',
])

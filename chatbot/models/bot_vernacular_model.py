from django.db import models
from simple_history.models import HistoricalRecords
from chatbot.models import CompanyBot


class BotVernacular(models.Model):
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.CASCADE, related_name='bot_vernacular')

    language = models.CharField(max_length=250)
    introductory_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        db_table = 'shikshalokam"."bot_vernacular'
        unique_together = ('company_bot', 'language')
        indexes = [
            models.Index(fields=['language']),
            models.Index(fields=['created_at']),
            models.Index(fields=['company_bot']),
        ]

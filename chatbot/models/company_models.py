from django.db import models
from chatbot.models import CompanyBot, EntityTypeChoices


class CompanyStateMachine(models.Model):
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    step = models.IntegerField()
    type = models.CharField(max_length=10, choices=EntityTypeChoices.choices, default=EntityTypeChoices.MANDATORY)
    bot_question = models.TextField(null=True, blank=True)
    completion_criteria = models.TextField(null=True, blank=True)
    context = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

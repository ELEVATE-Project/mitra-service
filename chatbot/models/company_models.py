from django.db import models
from chatbot.models import CompanyBot, EntityTypeChoices


class CompanyStateMachine(models.Model):
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, help_text="Enter the name of the state.")
    step = models.IntegerField(
        help_text="Integer representing the order in which state function calling happens. Lower values are "
                  "called first."
    )
    type = models.CharField(
        max_length=10, choices=EntityTypeChoices.choices, default=EntityTypeChoices.MANDATORY,
        help_text="Specify whether the state is mandatory or optional."
    )
    bot_question = models.TextField(
        null=True, blank=True, help_text="Provide the first question that the bot will ask when the state is triggered."
    )
    completion_criteria = models.TextField(
        null=True, blank=True,
        help_text="Define the criteria required to move from this state to the next state."
    )
    context = models.TextField(
        null=True, blank=True, help_text="Provide the main prompt or description of the state, explaining its purpose."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

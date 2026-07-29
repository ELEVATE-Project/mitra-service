from django.db import models
from chatbot.models import ChatSession, Profile, CompanyBot, UsageCallType


# Purpose:  Persistent audit record for every billable provider call made during a chat session.
#           Backs the ChatSession.total_cost running total.
# Fields:
#   session      — Chat session this call belongs to (CASCADE delete).
#   profile      — User who incurred the cost (SET_NULL so logs survive profile deletion).
#   company_bot  — Bot configuration in use (SET_NULL on delete).
#   call_type    — Category: LLM | TTS | STT | TRANSLATE | TRANSLITERATE.
#   provider     — External service name (e.g. "GOOGLE", "AI4Bharat").
#   model_name   — Specific model or voice used.
#   input_units  — Tokens (LLM), characters (TTS/translate/transliterate), or seconds (STT).
#   output_units — Same unit type as input_units for the response side.
#   input_cost   — USD cost for input units (6dp for sub-cent precision).
#   output_cost  — USD cost for output units.
#   total_cost   — input_cost + output_cost; also aggregated onto ChatSession.total_cost.
#   other_params — Escape hatch for provider-specific metadata.
# Written by: record_usage_cost() in usage_cost_utils.py
# Read by:    usage_cost_dashboard and related admin views.
class UsageCostLog(models.Model):

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='usage_cost_logs')
    profile = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True)
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.SET_NULL, null=True, blank=True)

    call_type = models.CharField(max_length=20, choices=UsageCallType.choices)
    provider = models.CharField(max_length=100, null=True, blank=True)
    model_name = models.CharField(max_length=255, null=True, blank=True)

    # Units are token counts for LLM, character counts for TTS/translate/transliterate,
    # and seconds for STT. Cost fields use 6 decimal places to capture sub-cent precision.
    input_units = models.IntegerField(default=0)
    output_units = models.IntegerField(default=0)
    input_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    output_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=6, default=0)

    other_params = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Usage Cost Log'
        # verbose_name_plural controls the Django admin sidebar label for this model.
        verbose_name_plural = 'Usage Cost Dashboard'
        indexes = [
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.call_type} - {self.session_id} - {self.total_cost}"

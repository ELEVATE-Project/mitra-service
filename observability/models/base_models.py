from django.core.validators import MaxValueValidator, MinValueValidator
from .enums import TestCaseInputFormat, TCRunStatus, TCRunMetrics, TCStatus
from django.db import models
from django.utils.translation import gettext_lazy as _
from chatbot.models import CompanyBot, LLMModel, LLMProvider, ChatSession
from observability.celery_tasks import llm_test_cases
from django.db.models.signals import post_save
from django.dispatch import receiver


class CompanyBotTestCases(models.Model):
    company_bot = models.ForeignKey(
        CompanyBot, on_delete=models.CASCADE, null=True, blank=True)
    testcase_input = models.TextField(blank=True, null=True)
    expected_output = models.TextField(blank=False, null=False)
    chat_session = models.ForeignKey(
        ChatSession, blank=True, null=True, on_delete=models.CASCADE)
    message = models.TextField(blank=True, null=True)
    retrieval_context = models.TextField(blank=True, null=True)
    input_format = models.CharField(
        max_length=100, choices=TestCaseInputFormat, default=TestCaseInputFormat.JSON)
    # need to do: Need to hadle this
    json_output_schema = models.TextField(blank=True, null=True)


class CompanyBotTCRun(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.CASCADE)
    llm_model = models.CharField(
        max_length=100, choices=LLMModel.choices, default=LLMModel.GPT4_O_MINI)
    provider = models.CharField(
        max_length=100, choices=LLMProvider.choices, default=LLMProvider.OPENAI)
    status = models.CharField(
        max_length=100, choices=TCRunStatus.choices, default=TCRunStatus.RUNNING)

    metrics_result = models.TextField(null=True, blank=True)


class TCBotRunMetrics(models.Model):
    bot_tc_run = models.ForeignKey(
        CompanyBotTestCases, on_delete=models.CASCADE, null=False, blank=False
    )
    metric_name = models.CharField(
        max_length=100, null=False, blank=False, choices=TCRunMetrics.choices)
    prompt_instructions = models.TextField(null=True, blank=True),
    assessment_questions = models.TextField(
        blank=True, null=True)
    metric_threshold_value = models.FloatField(null=False, default=0.7, validators=[
        MaxValueValidator(1),
        MinValueValidator(0)
    ])
    metric_score = models.FloatField(null=True, blank=True, validators=[
        MaxValueValidator(1),
        MinValueValidator(0)
    ])
    reason = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.metric_name


class BotRunTestCaseMap(models.Model):
    bot_run = models.ForeignKey(CompanyBotTCRun, on_delete=models.CASCADE)
    test_case = models.ForeignKey(
        CompanyBotTestCases, on_delete=models.CASCADE)
    metric_name = models.CharField(
        max_length=100, null=False, blank=False, choices=TCRunMetrics.choices)
    score = models.FloatField(null=True, blank=True, validators=[
        MaxValueValidator(1),
        MinValueValidator(0)
    ])
    reason = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=100, choices=TCStatus.choices, null=True, blank=True
    )

    def __str__(self):
        return self.metric_name


@receiver(post_save, sender=CompanyBotTCRun)
def run_test_cases(sender, instance, created, **kwargs):
    if created:
        print("created tc run", created, instance.pk)
        llm_test_cases.run.delay(instance.company_bot.pk, instance.pk)

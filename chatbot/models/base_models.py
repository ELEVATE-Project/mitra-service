import os
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.contrib.auth.hashers import make_password
from simple_history.models import HistoricalRecords
from chatbot.models.enums import (
    EntityStatus, LLMModel, GenderChoices, ProfileType, ChatStatus,
    FeedbackChoices, CompanyBotTypeChoices, CompanyBotDynamicContextType, CompanyChatSourceChoices,
    ChatStageChoices, VoiceProvider, VoiceType, LLMProvider
)


S3_BASE_URL = os.getenv('S3_MEDIA_URL')


class Company(models.Model):

    def get_file_upload_path(self, filename):
        folder_name = 'chatbot/company/{}'.format(self.slug)
        upload_path = f"{folder_name}/{filename}"
        return upload_path

    name = models.CharField(max_length=100)
    slug = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, choices=EntityStatus.choices)
    logo = models.ImageField(upload_to=get_file_upload_path, max_length=1000, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        indexes = [
            models.Index(fields=['slug']),
        ]

    def get_public_url(self):
        return f"{S3_BASE_URL}{self.logo.name}"


class CompanyBot(models.Model):

    def get_file_upload_path(self, filename):
        folder_name = self.company.slug+'/'+'static-media'
        upload_path = f"{folder_name}/{filename}"
        return upload_path

    name = models.CharField(max_length=100, help_text="Enter the name of the bot.")
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, help_text="Select the company this bot belongs to."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    context = models.TextField(help_text="Provide the bot's main prompt or description of its purpose.")
    max_token = models.IntegerField(default=2048, validators=[MinValueValidator(1)])
    bot_temperature = models.FloatField(
        default=0,
        help_text="Set the temperature for controlling response randomness (0-1). Lower values produce more "
                  "deterministic responses."
    )
    top_k = models.IntegerField(
        default=2, validators=[MinValueValidator(1)],
        help_text="Set the top-k value for the bot's response selection. This defines how many top options to consider "
                  "for each response."
    )
    llm_model = models.CharField(
        max_length=100, choices=LLMModel.choices, default=LLMModel.GPT4_O_MINI,
        help_text="Select the LLM model to be used by the bot (e.g., GPT-4o, GPT-4)."
    )
    filter_score = models.FloatField(
        default=0.8,
        help_text="Set the filter score for bot response selection (0-1). Responses below this score will be "
                  "filtered out."
    )
    end_context = models.TextField(
        null=True, blank=True,
        help_text="Provide additional prompt or context to append at the end of the main prompt to guide the "
                  "conversation"
    )
    introductory_message = models.CharField(
        max_length=1000, null=True, blank=True,
        help_text="Provide an introductory message that the bot will present when the conversation starts."
    )
    tag_context = models.TextField(
        null=True, blank=True,
        help_text="Provide any information or context related to variables (like Python-bound variables) that will be "
                  "inserted into the prompt."
    )
    route = models.CharField(
        max_length=100, default='/', help_text="Specify the route or API endpoint for interacting with the bot."
    )

    bot_type = models.CharField(max_length=30, choices=CompanyBotTypeChoices.choices,
                                default=CompanyBotTypeChoices.SIMPLE)
    llm_key = models.CharField(max_length=255, null=True, blank=True)
    dynamic_context = models.TextField(
        null=True, blank=True,
        help_text="Provide dynamic context that can be adjusted during the bot's interactions, such as "
                  "personalized data."
    )
    dynamic_context_type = models.CharField(max_length=20, choices=CompanyBotDynamicContextType.choices,
                                            null=True, blank=True)
    pre_context = models.TextField(
        null=True, blank=True, help_text="Provide pre-context that will be set before the main prompt to shape the "
                                         "conversation."
    )
    tool_context= models.TextField(null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.name

    class Meta:
        indexes = [
            models.Index(fields=['company']),
        ]


class Profile(models.Model):

    def get_file_upload_path(self, filename):
        folder_name = self.company.slug+'/'+'profile'+'/'+self.email
        upload_path = f"{folder_name}/{filename}"
        return upload_path

    first_name = models.CharField(max_length=100)
    userid = models.CharField(max_length=200, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    email = models.EmailField(max_length=100, null=False, blank=False)
    phone = models.CharField(max_length=20, null=True, blank=True)
    alternate_phone = models.CharField(max_length=20, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=20, choices=EntityStatus.choices, default=EntityStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    company = models.ForeignKey(Company, on_delete=models.DO_NOTHING, null=False, blank=False)
    password = models.CharField(max_length=1000, null=True, blank=True)
    profile_type = models.CharField(max_length=20, choices=ProfileType.choices, default=ProfileType.USER)
    profile_code = models.CharField(max_length=100, null=True, blank=True)
    location = models.CharField(max_length=1000, null=True, blank=True)
    caste = models.CharField(max_length=1000, null=True, blank=True)
    gender = models.CharField(max_length=1000, null=True, blank=True, choices=GenderChoices.choices)
    designation = models.TextField(null=True, blank=True)
    org_associated = models.CharField(max_length=1000, null=True, blank=True)
    product_interested = models.CharField(max_length=1000, null=True, blank=True)
    company_spoc = models.CharField(max_length=1000, null=True, blank=True)
    other_params = models.JSONField(null=True, blank=True)
    source = models.CharField(max_length=1000, null=True, blank=True)
    preferred_route = models.CharField(max_length=1000, null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return self.first_name

    def clean(self):
        super().clean()

        if self.phone:
            if Profile.objects.filter(phone=self.phone, company=self.company).exists():
                raise ValidationError({
                        'phone': 'A profile with this phone number already exists for the specified company.'
                    })

    def save(self, *args, **kwargs):
        if self.password and 'pbkdf2_sha256' not in self.password:
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ('email', 'company')
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['phone']),
        ]


class CompanyChat(models.Model):
    message = models.TextField()
    translated_message = models.TextField(null=True, blank=True)
    chunks = models.TextField(null=True)
    sender = models.ForeignKey(Profile, related_name='sender', on_delete=models.SET_NULL, null=True)
    receiver = models.ForeignKey(Profile, related_name='receiver', on_delete=models.SET_NULL, null=True)
    session = models.CharField(max_length=255)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, choices=ChatStatus.choices, null=True, blank=True)
    feedback = models.CharField(max_length=20, choices=FeedbackChoices.choices, null=True, blank=True)
    source = models.CharField(max_length=20, choices=CompanyChatSourceChoices.choices,
                              default=CompanyChatSourceChoices.WEB)
    message_type = models.CharField(max_length=20, null=True, blank=True)
    stage = models.CharField(max_length=500, choices=ChatStageChoices.choices, null=True, blank=True)

    def __str__(self):
        return self.message

    class Meta:
        indexes = [
            models.Index(fields=['session']),
            models.Index(fields=['created_at']),
            models.Index(fields=['sender']),
            models.Index(fields=['receiver']),
        ]

    def save(self, *args, **kwargs):
        if not self.created_at:
            self.created_at = timezone.now()
        super(CompanyChat, self).save(*args, **kwargs)


class Voice(models.Model):
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.SET_NULL, null=True, blank=True)
    type = models.CharField(max_length=300, choices=VoiceType.choices, null=True, blank=True)
    provider = models.CharField(max_length=300, null=True, blank=True,
                                choices=VoiceProvider.choices, default=VoiceProvider.AI4Bharat)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider}-{self.type}"

    class Meta:
        indexes = [
            models.Index(fields=['company_bot']),
            models.Index(fields=['created_at']),
            models.Index(fields=['type']),
            models.Index(fields=['provider']),
        ]

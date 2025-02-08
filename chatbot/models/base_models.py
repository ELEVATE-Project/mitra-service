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
    ChatStageChoices, VoiceProvider, VoiceType
)

S3_BASE_URL = os.getenv('S3_BASE_URL')


class Company(models.Model):

    def get_file_upload_path(self, filename):
        folder_name = 'chatbot/company/{}'.format(self.slug)
        upload_path = f"{folder_name}/{filename}"
        return upload_path

    name = models.CharField(max_length=100)
    slug = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, choices=EntityStatus.choices)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        indexes = [
            models.Index(fields=['slug']),
        ]


class CompanyBot(models.Model):

    def get_file_upload_path(self, filename):
        folder_name = self.company.slug+'/'+'static-media'
        upload_path = f"{folder_name}/{filename}"
        return upload_path

    name = models.CharField(max_length=100)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    context = models.TextField()
    bot_temperature = models.FloatField(default=0)
    top_k = models.IntegerField(default=2, validators=[MinValueValidator(1)])
    llm_model = models.CharField(max_length=100, choices=LLMModel.choices, default=LLMModel.GPT3_5)
    filter_score = models.FloatField(default=0.8)
    end_context = models.TextField(null=True, blank=True)
    introductory_message = models.CharField(max_length=1000, null=True, blank=True)
    tag_context = models.TextField(null=True, blank=True)
    route = models.CharField(max_length=100, default='/')
    bot_type = models.CharField(max_length=30, choices=CompanyBotTypeChoices.choices,
                                default=CompanyBotTypeChoices.SIMPLE)
    llm_key = models.CharField(max_length=255, null=True, blank=True)
    dynamic_context = models.TextField(null=True, blank=True)
    dynamic_context_type = models.CharField(max_length=20, choices=CompanyBotDynamicContextType.choices,
                                            null=True, blank=True)
    pre_context = models.TextField(null=True, blank=True)
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
    designation = models.CharField(max_length=200, null=True, blank=True)
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
    source_msg_id = models.CharField(max_length=256, null=True, blank=True)
    whatsapp_message_id = models.CharField(max_length=255, null=True, blank=True)
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

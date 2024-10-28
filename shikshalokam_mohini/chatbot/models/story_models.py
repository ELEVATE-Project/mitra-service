import os
import base64

from django.db import models
from django_s3_storage.storage import S3Storage
from django.core.validators import MinLengthValidator

from chatbot.models import Profile, TagChoices, StoryLanguageChoices, StorySourceChoices, MediaTypeChoices, \
    StoryStatusChoices, Company

storage = S3Storage(aws_s3_bucket_name='static-media.gritworks.ai')
S3_BASE_URL = os.getenv('S3_MEDIA_URL')


class Story(models.Model):
    title = models.CharField(max_length=1000)
    author = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True)
    content = models.TextField(null=True, blank=True)
    tweet = models.TextField(null=True, blank=True)
    session = models.CharField(max_length=255, unique=True)
    objective = models.TextField(null=True, blank=True)
    action_steps = models.TextField(null=True, blank=True)
    impact = models.TextField(null=True, blank=True)
    micro_improvement = models.TextField(null=True, blank=True)
    location = models.CharField(max_length=1000, null=True, blank=True)
    formatted_content = models.TextField(null=True, blank=True)
    language = models.CharField(max_length=1000, choices=StoryLanguageChoices.choices,
                                default=StoryLanguageChoices.ENGLISH)
    source = models.CharField(max_length=1000, choices=StorySourceChoices.choices,
                              default=StorySourceChoices.AI_GENERATED)
    story_code = models.CharField(max_length=100, null=True, blank=True)
    stage = models.CharField(max_length=100, choices=StoryStatusChoices.choices, default=StoryStatusChoices.PENDING)
    summary = models.TextField(null=True, blank=True)
    other_params = models.JSONField(null=True, blank=True)

    client_created_at = models.DateTimeField(null=True, blank=True)
    client_updated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    class Meta:
        indexes = [
            models.Index(fields=['title']),
            models.Index(fields=['session']),
            models.Index(fields=['author'])
        ]


class StoryMedia(models.Model):

    def get_file_upload_path(self, filename):
        folder_name = 'chatbot/storymedia/{}'.format(self.story.id)
        upload_path = f"{folder_name}/{filename}"
        return upload_path

    name = models.CharField(max_length=1000)
    file = models.FileField(storage=storage, upload_to=get_file_upload_path, max_length=1000)
    story = models.ForeignKey(Story, related_name='story_media', on_delete=models.CASCADE)
    include_in_story = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    base64_str = models.TextField(null=True, blank=True)
    media_type = models.CharField(max_length=100, choices=MediaTypeChoices.choices, null=True, blank=True)

    def get_public_url(self):
        return f"{S3_BASE_URL}{self.file.name}"

    def save(self, *args, **kwargs):
        self.base64_str = base64.b64encode(self.file.read()).decode('utf-8')
        super().save(*args, **kwargs)


class Tag(models.Model):
    name = models.CharField(max_length=1000, unique=True, null=False, blank=False,
                            validators=[MinLengthValidator(limit_value=3)])
    status = models.CharField(max_length=100, choices=TagChoices.choices, default=TagChoices.PENDING)
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, null=True, blank=True)

    created_by = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class StoryTag(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.DO_NOTHING)
    is_primary = models.BooleanField(default=False)

    created_by = models.ForeignKey(Profile, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.story.title} - {self.tag.name}"

    class Meta:
        unique_together = ('story', 'tag')

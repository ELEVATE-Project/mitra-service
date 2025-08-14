import json
import os
import base64
from celery import shared_task
from django.db import models
from chatbot.models import Profile, CompanyBot, MediaTypeChoices, MediaTemplateChoices, PDFStrategyChoices, Tag
from chatbot.utils.database_util import upsert_single_file, delete_single_file
from chatbot.utils.knowledge_service.auto_tag_utils import save_auto_tags
from shikshalokam.models.enums import PriorityChoices

S3_BASE_URL = os.getenv('S3_MEDIA_URL')


class ProfileMedia(models.Model):

    def get_file_upload_path(self, filename):
        folder_name = 'chatbot/profilemedia/{}'.format(self.profile.id)
        upload_path = f"{folder_name}/{filename}"
        return upload_path

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    file = models.FileField(upload_to=get_file_upload_path, max_length=1000)
    base64_str = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_public_url(self):
        # Assuming your S3 bucket is public, you can directly construct the URL
        return f"{S3_BASE_URL}{self.file.name}"

    def save(self, *args, **kwargs):
        self.base64_str = base64.b64encode(self.file.read()).decode('utf-8')
        super().save(*args, **kwargs)


class Media(models.Model):

    def get_file_upload_path(self, filename):
        folder_name = f'shikshalokam/media/{self.company_bot.id}'
        upload_path = f"{folder_name}/{filename}"
        return upload_path

    @shared_task
    def save_in_vector_db(media_id):
        print('Save in vector for media_id: {}'.format(media_id))
        media = Media.objects.get(id=media_id)
        kvs = KeyValue.objects.filter(media=media)
        metadata = {
            'source': 'file',
            'url': str(media.url) if media.url is not None else S3_BASE_URL + media.file.name,
            'company': media.company_bot.company.slug,
            'created_at': str(media.created_at),
        }
        other_tags = dict()
        for kv in kvs:
            if kv.key in ['TITLE OF THE PROJECT', 'priority',
                          'TARGET STAKEHOLDER', 'DURATION', 'DESCRIPTION',
                          'OBJECTIVE', 'PROJECT LEVEL LEARNING RESOURCE', 'TASK NAME',
                          'SUB TASK (If any)', 'NAME OF TASK LEVEL LEARNING RESOURCE']:
                metadata[kv.key] = kv.value
            else:
                other_tags[kv.key] = kv.value
        other_tags['s3_link'] = S3_BASE_URL + media.file.name
        metadata['other_tags'] = str(other_tags)
        metadata['tags'] = list(media.tags.values_list('name', flat=True))
        with media.file.open("rb") as file:
            file_content = file.read()
        file_name = media.file.name.split("/")[-1]

        status_code, response_text = upsert_single_file(file_name, file_content, metadata, media)
        print(status_code, response_text)

        if status_code == 200:
            save_auto_tags(media)
        else:
            print(f"Vector DB upsert failed for media {media.id}, skipping auto-tag")


    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            self.save_in_vector_db.apply_async(args=(self.id,), countdown=1)

    @shared_task
    def delete_from_vector_db(media_id):
        print('Deleting from vector for media_id: {}'.format(media_id))
        status_code, response_text = delete_single_file(media_id)
        print(status_code, response_text)
        return status_code

    def delete(self, *args, **kwargs):
        status_code = 200 #self.delete_from_vector_db(self.id)
        if status_code == 200:
            super().delete(*args, **kwargs)
        else:
            raise Exception(
                f"Failed to delete from vector DB for media_id: {self.id}. Status: {status_code}"
            )

    def get_s3_url(self):
        return f"{S3_BASE_URL}{self.file.name}"

    name = models.CharField(max_length=1000)
    url = models.URLField(max_length=1000, null=True, blank=True)
    priority = models.CharField(max_length=50, default=PriorityChoices.P1, choices=PriorityChoices.choices)
    media_type = models.CharField(max_length=100, choices=MediaTypeChoices.choices, default=MediaTypeChoices.TXT)
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.DO_NOTHING)
    file = models.FileField(upload_to=get_file_upload_path, max_length=1000)
    description = models.TextField(null=True, blank=True)
    tags = models.ManyToManyField(Tag, related_name="medias")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class MediaVector(models.Model):
    media = models.ForeignKey(Media, on_delete=models.CASCADE, related_name='media_vector')
    vector_id = models.CharField(max_length=1000, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class KeyValue(models.Model):
    media = models.ForeignKey(Media, on_delete=models.CASCADE, related_name='key_values')
    key = models.CharField(max_length=1000)
    value = models.CharField(max_length=10000)

    def __str__(self):
        return f"{self.key}: {self.value}"


class MediaTemplate(models.Model):
    name = models.CharField(max_length=100, null=True, unique=True)
    template_content = models.TextField(null=True)
    template_type = models.CharField(choices=MediaTemplateChoices.choices, max_length=100, null=True)
    pdf_strategy = models.CharField(choices=PDFStrategyChoices.choices, max_length=100, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

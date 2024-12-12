import json
import os
import base64

from celery import shared_task
from django.db import models
from chatbot.models import Profile, CompanyBot, MediaTypeChoices
from django_s3_storage.storage import S3Storage

from chatbot.utils.database_util import upsert_single_file

S3_BASE_URL = os.getenv('S3_MEDIA_URL')
storage = S3Storage(aws_s3_bucket_name='mohini-static.shikshalokam.org')


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
        folder_name = self.company_bot.company.slug
        upload_path = f"{folder_name}/{filename}"
        return upload_path

    @shared_task
    def save_in_vector_db(media_id):
        print('Save in vector for media_id: {}'.format(media_id))
        media = Media.objects.get(id=media_id)
        media_vector = MediaVector.objects.filter(media=media)
        media_vector = media_vector[0] if media_vector else None
        kvs = KeyValue.objects.filter(media=media)
        metadata = {
            'source': 'file',
            'source_id': media_id,
            'url': str(media.url) if media.url is not None else S3_BASE_URL + media.file.name,
            'company': media.company.slug,
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
        if media_vector is not None:
            metadata['id'] = media_vector.vector_id
        other_tags['s3_link'] = S3_BASE_URL + media.file.name
        metadata['other_tags'] = str(other_tags)
        status_code, response_text = upsert_single_file(media.name, media.file, metadata, media.media_type)
        print(status_code, response_text)
        response_vector = json.loads(response_text)
        if media_vector is None:
            media_vector = MediaVector(media=media, vector_id=response_vector['ids'][0])
            media_vector.save()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.save_in_vector_db.apply_async(args=(self.id,), countdown=1)

    def get_s3_url(self):
        return f"{S3_BASE_URL}{self.file.name}"

    name = models.CharField(max_length=1000)
    url = models.URLField(max_length=1000, null=True, blank=True)
    media_type = models.CharField(max_length=100, choices=MediaTypeChoices.choices, default=MediaTypeChoices.TXT)
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.DO_NOTHING)
    file = models.FileField(storage=storage, upload_to=get_file_upload_path, max_length=1000)
    description = models.TextField(null=True, blank=True)

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

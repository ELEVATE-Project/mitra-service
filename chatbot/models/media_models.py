import os
import base64
from celery import shared_task
from django.db import models
from chatbot.models import Profile, CompanyBot, MediaTypeChoices, MediaTemplateChoices, PDFStrategyChoices, Tag, \
    FileTypeChoices
from chatbot.utils.database_util import upsert_single_file, delete_single_file
from chatbot.utils.knowledge_service.auto_tag_utils import save_auto_tags
from shikshalokam.models.enums import PriorityChoices
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, TrigramSimilarity

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
        for kv in kvs:
            metadata[kv.key] = kv.value
        metadata['tags'] = list(media.tags.values_list('name', flat=True))
        with media.file.open("rb") as file:
            file_content = file.read()
        file_name = media.file.name.split("/")[-1]

        status_code, response_text = upsert_single_file(file_name, file_content, metadata, media)
        print(status_code, response_text)


    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            self.save_in_vector_db.apply_async(args=(self.id,), countdown=1)

    @shared_task
    def delete_from_vector_db(media_id):
        print('Deleting from vector for media_id: {}'.format(media_id))
        media = Media.objects.get(id=media_id)
        company_slug = media.company_bot.company.slug if media.company_bot and media.company_bot.company else None
        status_code, response_text = delete_single_file(media_id, company_slug)
        print(status_code, response_text)
        return status_code

    def delete(self, *args, **kwargs):
        status_code = self.delete_from_vector_db(self.id)
        if status_code == 200:
            super().delete(*args, **kwargs)
        else:
            raise Exception(
                f"Failed to delete from vector DB for media_id: {self.id}. Status: {status_code}"
            )

    @classmethod
    def find_trigram_similar(cls, extracted_text, company_bot_id, similarity_threshold=0.85, exclude_id=None):
        """
        Find media with similar text using trigram similarity (local check)
        """
        if not extracted_text or len(extracted_text.strip()) < 50:
            return []

        text_sample = extracted_text[:1500].strip()

        queryset = cls.objects.filter(company_bot_id=company_bot_id)
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)

        similar_media = (
            queryset
            .annotate(
                similarity=TrigramSimilarity('extracted_text', text_sample)
            )
            .filter(similarity__gte=similarity_threshold)
            .order_by('-similarity')
            .values('id', 'name', 'similarity', 'created_at', 'file')[:5]
        )

        return list(similar_media)

    def get_s3_url(self):
        return f"{S3_BASE_URL}{self.file.name}"

    name = models.CharField(max_length=1000)
    url = models.URLField(max_length=1000, null=True, blank=True)
    priority = models.CharField(max_length=50, default=PriorityChoices.P1, choices=PriorityChoices.choices)
    media_type = models.CharField(max_length=100, choices=FileTypeChoices.choices, default=FileTypeChoices.TXT)
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.DO_NOTHING)
    file = models.FileField(upload_to=get_file_upload_path, max_length=1000)
    description = models.TextField(null=True, blank=True)
    extracted_text = models.TextField(null=True, blank=True)
    tags = models.ManyToManyField(Tag, related_name="medias")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        indexes = [
            GinIndex(
                SearchVector('extracted_text', config='english'),
                name='media_extracted_text_gin'
            ),
            GinIndex(
                fields=['extracted_text'], name='media_extracted_text_trgm',
                opclasses=['gin_trgm_ops'],
            )
        ]

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

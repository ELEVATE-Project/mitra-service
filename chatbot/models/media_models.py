import os
import base64
from django.db import models
from chatbot.models import Profile, CompanyBot, MediaTemplateChoices, PDFStrategyChoices, Tag, \
    FileTypeChoices, Company, MediaTypeChoices, FileDisplayMode
from shikshalokam.models.enums import PriorityChoices
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, TrigramSimilarity
from simple_history.models import HistoricalRecords
from chatbot.celery_tasks.knowledge_service.media_tasks import save_in_vector_db, update_in_vector_db

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


    def save(self, *args, company_slug=None, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            task = save_in_vector_db.apply_async(args=(self.id, company_slug), countdown=1)
            return
        else:
            from chatbot.celery_tasks.knowledge_service.media_tasks import delete_from_vector_db
            try:
                result = delete_from_vector_db(self.id)
                status_code = result if isinstance(result, int) else 200
                if status_code != 200:
                    raise Exception(f"Vector DB deletion failed with status {status_code}")

                print(f"Vector DB deletion status for media_id {self.id}: {status_code}")
                task = save_in_vector_db.apply_async(args=(self.id, company_slug), countdown=1)
                from celery.result import AsyncResult
            except Exception as e:
                print(f"Error deleting from vector DB for media_id {self.id}: {str(e)}")
                status_code = 500
            # task = update_in_vector_db.apply_async(args=(self.id, company_slug), countdown=1)
            return

    def delete(self, *args, **kwargs):
        from chatbot.celery_tasks.knowledge_service.media_tasks import delete_from_vector_db
        
        # Try to delete from vector DB first
        try:
            result = delete_from_vector_db(self.id)
            status_code = result if isinstance(result, int) else 200
            print(f"Vector DB deletion status for media_id {self.id}: {status_code}")
        except Exception as e:
            print(f"Error deleting from vector DB for media_id {self.id}: {str(e)}")
            status_code = 500
        
        # Always delete from Django DB regardless of vector DB status
        super().delete(*args, **kwargs)

    @classmethod
    def find_trigram_similar(
            cls, extracted_text, company_slug, similarity_threshold=0.85, exclude_id=None
    ):
        """
        Find media with similar text using trigram similarity (local check)
        """
        if not extracted_text or len(extracted_text.strip()) < 50:
            return []

        text_sample = extracted_text[:1500].strip()

        company = Company.objects.get(slug=company_slug)
        queryset = cls.objects.filter(company_bot__company=company)

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
    organization = models.ForeignKey(Company, on_delete=models.CASCADE, null=True, blank=True)
    url = models.URLField(max_length=1000, null=True, blank=True)
    priority = models.CharField(max_length=50, default=PriorityChoices.P1, choices=PriorityChoices.choices)
    media_type = models.CharField(max_length=100, choices=FileTypeChoices.choices, default=FileTypeChoices.TXT)
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.DO_NOTHING)
    file = models.FileField(upload_to=get_file_upload_path, max_length=1000)
    markdown_file = models.FileField(upload_to=get_file_upload_path, max_length=1000, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    extracted_text = models.TextField(null=True, blank=True)
    tags = models.ManyToManyField(Tag, related_name="medias")
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='subdocuments'
    )
    display_mode = models.CharField(
        max_length=20, choices=FileDisplayMode.choices, default=FileDisplayMode.VISIBLE
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    history = HistoricalRecords()

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


class MediaImage(models.Model):
    """Store images associated with Media documents"""

    def get_file_upload_path(self, filename):
        folder_name = f'shikshalokam/media/{self.media.company_bot.id}/images'
        upload_path = f"{folder_name}/{filename}"
        return upload_path

    name = models.CharField(max_length=1000)
    file = models.FileField(upload_to=get_file_upload_path, max_length=1000, null=True, blank=True)
    media = models.ForeignKey(Media, on_delete=models.CASCADE, related_name='images')
    page = models.IntegerField(null=True, blank=True)
    index = models.IntegerField(default=0)
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    media_type = models.CharField(max_length=100, choices=MediaTypeChoices.choices, null=True, blank=True)
    base64_str = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['page', 'index']

    def __str__(self):
        return f"Image {self.index} for {self.media.name}"


class MediaVector(models.Model):
    media = models.ForeignKey(Media, on_delete=models.CASCADE, related_name='media_vector')
    vector_id = models.CharField(max_length=1000, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class KeyValue(models.Model):
    media = models.ForeignKey(Media, on_delete=models.CASCADE, related_name='key_values')
    key = models.CharField(max_length=1000)
    value = models.TextField(null=True, blank=True)

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

from celery import shared_task
import os

from chatbot.utils.database_util import update_single_file, delete_single_file, upsert_single_file

S3_BASE_URL = os.getenv('S3_MEDIA_URL')


def prepare_vector_db_data(media_id, include_updated_at=False, company_slug=None):
    """Helper method to prepare data for vector DB operations"""
    from chatbot.models import KeyValue, Media, Company
    media = Media.objects.get(id=media_id)
    kvs = KeyValue.objects.filter(media=media)
    company_obj = None
    if company_slug:
        company_obj = Company.objects.filter(slug=company_slug).first()
    company_obj = company_obj or media.organization

    metadata = {
        'source': 'file',
        'url': str(media.url) if media.url is not None else S3_BASE_URL + media.file.name,
        'markdown_url':  "" if not media.markdown_file else S3_BASE_URL + media.markdown_file.name,
        'company': company_obj.slug,
        'created_at': str(media.created_at),
        'type': media.media_type,
        'priority': media.priority,
    }

    if include_updated_at:
        metadata['updated_at'] = str(media.updated_at)

    # Add file_size if file exists
    if media.file:
        try:
            metadata['file_size'] = media.file.size
        except (ValueError, AttributeError):
            metadata['file_size'] = None

    # Add organization_url if organization exists
    if company_obj and company_obj.url:
        metadata['organization_url'] = company_obj.url

    for kv in kvs:
        metadata[kv.key] = kv.value
    metadata['tags'] = list(media.tags.values_list('name', flat=True))

    with media.file.open("rb") as file:
        file_content = file.read()
    file_name = media.file.name.split("/")[-1]

    return media, file_name, file_content, metadata


@shared_task
def save_in_vector_db(media_id, company_slug=None):
    print(f"Save in vector for media_id: {media_id}, company_slug: {company_slug}")
    media, file_name, file_content, metadata = prepare_vector_db_data(
        media_id=media_id,
        include_updated_at=False,
        company_slug=company_slug
    )
    status_code, response_text = upsert_single_file(file_name, file_content, metadata, media)
    print(status_code, response_text)
    return status_code


@shared_task
def update_in_vector_db(media_id, company_slug=None):
    print('Update in vector for media_id: {}'.format(media_id))
    media, file_name, file_content, metadata = prepare_vector_db_data(
        media_id=media_id,
        include_updated_at=True,
        company_slug=company_slug
    )
    status_code, response_text = update_single_file(media_id, file_name, file_content, metadata, media)
    print("Updated in vector DB:", status_code, response_text)
    return status_code

@shared_task
def delete_from_vector_db(media_id):
    print('Deleting from vector for media_id: {}'.format(media_id))
    from chatbot.models import Media
    media = Media.objects.get(id=media_id)
    company_slug = media.organization.slug if media and media.organization else None
    status_code, response_text = delete_single_file(media_id, company_slug)
    print(status_code, response_text)
    return status_code

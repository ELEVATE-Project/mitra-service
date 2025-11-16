import json
from datetime import datetime

import requests
import os
DATABASE_INTERFACE_BEARER_TOKEN = os.getenv('DATABASE_INTERFACE_BEARER_TOKEN')

SEARCH_TOP_K = 3

base_url = os.getenv('VECTOR_DB_BASE_URL')


def upsert_single_file(filename, file, metadata, media):
    url = f"http://{base_url}/api/documents"

    if isinstance(metadata, dict):
        metadata_json = json.dumps(metadata)
    else:
        metadata_json = metadata

    # Build payload with new format
    payload = {
        'metadata': metadata_json,
        'source_id': str(media.id),
        'priority': media.priority
    }
    
    # Add company_id if available
    if hasattr(media, 'company_bot') and media.company_bot and media.company_bot.company:
        payload['company_id'] = media.company_bot.company.slug
    elif hasattr(media, 'organization') and media.organization:
        payload['company_id'] = media.organization.slug
    
    # Add title if available (from KeyValue or media name)
    title = None
    if hasattr(media, 'key_values'):
        from chatbot.models import KeyValue
        title_kv = KeyValue.objects.filter(media=media, key__iexact='TITLE').first()
        if title_kv:
            title = title_kv.value
    if not title:
        title = media.name
    if title:
        payload['title'] = title
    
    # Add summary if available (from description)
    if hasattr(media, 'description') and media.description:
        payload['summary'] = media.description
    
    # Add tags if available
    if hasattr(media, 'tags'):
        tags_list = list(media.tags.values_list('name', flat=True))
        if tags_list:
            payload['tags'] = json.dumps(tags_list)
    
    files = [
        ('file', (filename, file, media.media_type))
    ]
    headers = {
        'accept': 'application/json',
    }
    print("payload: ", payload)
    response = requests.request("POST", url, headers=headers, data=payload, files=files)
    print("upserted: ", response.json())
    return response.status_code, response.text


def delete_single_file(media_id, company_slug=None):
    url = f"http://{base_url}/api/documents/{media_id}"

    params = {'company_id': company_slug} if company_slug else {}

    headers = {
        'accept': 'application/json',
    }
    response = requests.request("DELETE", url, headers=headers, params=params)
    print("deleted: ", response.json())
    return response.status_code, response.text


def update_single_file(media_id, filename, file, metadata, media):
    """Update a file in the vector database by deleting and re-uploading"""
    url = f"http://{base_url}/api/documents/{media_id}"

    if isinstance(metadata, dict):
        metadata_json = json.dumps(metadata)
    else:
        metadata_json = metadata

    # Add updated_at timestamp
    if isinstance(metadata, dict):
        metadata['updated_at'] = str(datetime.now())
        metadata_json = json.dumps(metadata)

    payload = {
        'metadata': metadata_json,
        'priority': media.priority
    }

    # Add company_id for safety verification if available
    if hasattr(media, 'company_bot') and media.company_bot and media.company_bot.company:
        payload['company_id'] = media.company_bot.company.slug
    elif hasattr(media, 'organization') and media.organization:
        payload['company_id'] = media.organization.slug
    
    # Add title if available (from KeyValue or media name)
    title = None
    if hasattr(media, 'key_values'):
        from chatbot.models import KeyValue
        title_kv = KeyValue.objects.filter(media=media, key__iexact='TITLE').first()
        if title_kv:
            title = title_kv.value
    if not title:
        title = media.name
    if title:
        payload['title'] = title
    
    # Add summary if available (from description)
    if hasattr(media, 'description') and media.description:
        payload['summary'] = media.description
    
    # Add tags if available
    if hasattr(media, 'tags'):
        tags_list = list(media.tags.values_list('name', flat=True))
        if tags_list:
            payload['tags'] = json.dumps(tags_list)

    files = [
        ('file', (filename, file, media.media_type))
    ]
    headers = {
        'accept': 'application/json',
    }

    print("update payload: ", payload)
    response = requests.request("PUT", url, headers=headers, data=payload, files=files)
    print("updated: ", response.json())
    return response.status_code, response.text

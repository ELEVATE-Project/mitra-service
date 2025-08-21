import json
import requests
import os
DATABASE_INTERFACE_BEARER_TOKEN = os.getenv('DATABASE_INTERFACE_BEARER_TOKEN')

SEARCH_TOP_K = 3

base_url = os.getenv('VECTOR_DB_BASE_URL')


def upsert_single_file(filename, file, metadata, media):
    url = f"https://{base_url}/api/upload"

    if isinstance(metadata, dict):
        metadata_json = json.dumps(metadata)
    else:
        metadata_json = metadata

    payload = {
        'metadata': metadata_json,
        'source_id': str(media.id),
        'priority': media.priority
    }
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
    url = f"https://{base_url}/api/documents"

    payload = {
        'source_id': str(media_id)
    }
    if company_slug:
        payload['company_id'] = company_slug

    headers = {
        'accept': 'application/json',
    }
    print("payload: ", payload)
    response = requests.request("DELETE", url, headers=headers, data=json.dumps(payload))
    print("deleted: ", response.json())
    return response.status_code, response.text

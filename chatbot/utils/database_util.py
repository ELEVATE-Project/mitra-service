import json
import requests
import os
DATABASE_INTERFACE_BEARER_TOKEN = os.getenv('DATABASE_INTERFACE_BEARER_TOKEN')

SEARCH_TOP_K = 3


def upsert_single_file(filename, file, metadata, file_type):
    url = "https://demo-mitra.shikshalokam.org/api/upload"

    payload = {
        'metadata': json.dumps(metadata)
    }
    files = [
        ('file', file)
    ]
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/json'
    }
    response = requests.request("POST", url, headers=headers, data=payload, files=files)
    return response.status_code, response.text

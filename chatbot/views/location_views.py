import json
import os
import requests
from rest_framework.decorators import api_view
from rest_framework.response import Response


location_auth = os.getenv('LOCATION_AUTH')
location_base_url = os.getenv('LOCATION_BASE_URL')


@api_view(['GET'])
def get_location_view(request):

    params = request.query_params

    parent_id = params.get('parentId')

    url = location_base_url

    filters = {"parentId": parent_id} if parent_id else {"type": "state"}

    payload = json.dumps({
        "request": {
            "filters": filters
        }
    })
    headers = {
        'Authorization': f'Bearer ' + location_auth,
        'Content-Type': 'application/json'
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    print("res: ", response)
    json_response = response.json()
    print("json_response: ", json_response)
    location_list = json_response.get('result').get('response')

    return Response({
        'status': 'ok',
        'list': location_list
    }, status=200)

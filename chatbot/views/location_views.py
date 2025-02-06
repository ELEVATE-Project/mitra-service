import json
import os
import requests
from rest_framework.decorators import api_view
from rest_framework.response import Response


location_auth = os.getenv('LOCATION_AUTH')


@api_view(['GET'])
def get_location_view(request):

    params = request.query_params

    parent_id = params.get('parentId')

    url = "https://dev.sunbirdsaas.com/api/data/v1/location/search"

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
    json_response = response.json()
    location_list = json_response.get('result').get('response')

    return Response({
        'status': 'ok',
        'list': location_list
    }, status=200)

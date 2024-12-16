import os

import requests
from pydantic_core._pydantic_core import ValidationError

from chatbot.models import Profile, Company
from chatbot.models.geo_models import ProfileAddress
from chatbot.serializer.profile_serializer import ProfileSerializer

base_url = os.getenv("SHIKSHALOKAM_BASE_URL")


def create_profile_utils(access_token):
    url = f"https://{base_url}/profile/read"

    headers = {
        "X-auth-token": access_token,
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        json_response = response.json()
        print("json_response: ", json_response)

        if not json_response or "result" not in json_response:
            raise ValidationError("Invalid response from the API")

        result = json_response.get("result")
        email = result.get('email')
        userid = result.get('id')
        name = result.get('name')
        preferred_language = result.get('preferred_language', {}).get('value')
        organization = result.get('organization', {}).get('name')
        block = result.get('block', {}).get('label')
        state = result.get('state', {}).get('label')
        district = result.get('district', {}).get('label')
        user_roles = result.get('user_roles', [])


        company = Company.objects.get(slug='shikshalokamstaging')

        profile_data = {
            "email": email,
            "first_name": name,
            "preferred_route": preferred_language,
            "org_associated": organization,
            "password": 'grit@123',
            "company": company,
            "designation": user_roles
        }

        address_data = {
            "block": block,
            "state": state,
            "district": district,
        }

        profile, created = Profile.objects.update_or_create(
            userid=userid,
            defaults=profile_data
        )

        if address_data:
            ProfileAddress.objects.update_or_create(
                profile=profile,
                defaults=address_data
            )
        print("profile: ", profile)
        serialized_profile = ProfileSerializer(profile).data
        print("serialized_profile: ", serialized_profile)
        return serialized_profile

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while making the API call: {e}")
        return None
    except ValidationError as e:
        print(f"Validation error: {e}")
        return None

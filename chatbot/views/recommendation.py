import os
from rest_framework.decorators import api_view
import requests
from django.http import JsonResponse
from chatbot.models import Profile
from chatbot.serializer.profile_serializer import ProfileSerializer
from chatbot.utils.profile_utils import create_profile_utils
from shikshalokam.models import Project, ProjectCreatedBy
from shikshalokam.serializer import ProjectSerializer
import jwt


recommendation_base_url = os.getenv("RECOMMENDATION_BASE_URL")


@api_view(["GET"])
def generate_recommendation(request):
    body = request.query_params
    limit = body.get("limit")
    page = body.get("page", 1)
    language = body.get("language")
    access_token = request.headers.get("X-auth-token")

    default_response = {
        'result': {
            "data": [],
            "count": 0
        }
    }

    try:

        decoded = jwt.decode(access_token, options={"verify_signature": False})
        # print(decoded)
        if decoded:
            user_id = decoded.get('data', {}).get('id')
        else:
            return JsonResponse(default_response, status=200, safe=False)


        # print(f"user_id={user_id} page={page} limit={limit} language={language}")

        try:
            res_profile = create_profile_utils(access_token=access_token)
            print("res_profile: ", res_profile)
            current_profile = Profile.objects.get(userid=user_id)

            print("got a profile: ", current_profile)
        except Profile.DoesNotExist:
            print("profile does not exist so creating one")
            try:
                create_profile_utils(access_token=access_token)
                current_profile = Profile.objects.get(userid=user_id)
                print("Profile successfully created and retrieved.")
            except Profile.DoesNotExist:
                print("Failed to create or retrieve profile.")
                return JsonResponse(default_response, status=200, safe=False)

        projects = Project.objects.filter(generated_by=ProjectCreatedBy.EXPERT_VETTED)
        project_serialized = ProjectSerializer(projects, many=True).data
        current_profile_serialized = ProfileSerializer(current_profile).data

        data = {
            "current_profile": current_profile_serialized,
            "project_templates": project_serialized
        }

        url = recommendation_base_url
        response = requests.post(url, json=data)
        response.raise_for_status()

        results = response.json()
        matched_projects = []
        if results:
            matched_projects = results.get('matched_projects')
        count = len(matched_projects)

        if limit:
            page = int(page)
            limit = int(limit)
            print("limit: ", limit)
            print("page: ", page)
            start_index = (page - 1) * limit
            end_index = start_index + limit
            paginated_projects = matched_projects[start_index:end_index]
        else:
            paginated_projects = matched_projects


        # paginated_projects = paginator.paginate_queryset(matched_projects, request)

        return JsonResponse({
            'result': {
                "data": paginated_projects,
                "count": count
            }
        }, safe=False)
    except Exception as e:
        print(f"Error: {e}")
        return JsonResponse(default_response, status=200, safe=False)


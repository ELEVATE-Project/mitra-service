from rest_framework.decorators import api_view
import requests
from django.http import JsonResponse

from chatbot.models import Profile
from chatbot.serializer.profile_serializer import ProfileSerializer
from shikshalokam.models import Project
from shikshalokam.serializer import ProjectSerializer


@api_view(["POST"])
def generate_recommendation(request):
    body = request.data
    email = body.get("email")

    current_profile = Profile.objects.get(email=email)
    if not current_profile:
        return JsonResponse({'message': 'Profile not found'}, status=404)

    other_profiles = Profile.objects.exclude(email=email).exclude(id=1)

    current_profile_serialized = ProfileSerializer(current_profile).data
    other_profiles_serialized = ProfileSerializer(other_profiles, many=True).data

    data = {
        "current_profile": current_profile_serialized,
        "other_profiles": other_profiles_serialized
    }

    url = "http://localhost:9001/similarity-score/"
    response = requests.post(url, json=data)
    response.raise_for_status()

    results = response.json()

    recommended_projects = get_project_recommendation(results)
    print("\n\nrecommended_projects: ", recommended_projects)

    return JsonResponse(results)


def get_project_recommendation(request):
    profile_details = request.get('profile_details')
    similarity_result = request.get('similarity_result')
    try:
        if profile_details and similarity_result and similarity_result[0].get('score') > 0:
            profile_id = profile_details.get('id')
            projects = Project.objects.filter(author=profile_id)[:3]
            serialized_projects = ProjectSerializer(projects, many=True).data

            if serialized_projects:
                return serialized_projects

        return []
    except Exception as e:
        print("Error: ", e)
        return []

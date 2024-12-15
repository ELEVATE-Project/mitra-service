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
    user_id = body.get("user_id")
    page = body.get("email")
    limit = body.get("limit")
    language = body.get("language")

    current_profile = Profile.objects.get(userid=user_id)
    if not current_profile:
        return JsonResponse({'message': 'Profile not found'}, status=404)

    other_profiles = Profile.objects.exclude(userid=user_id).exclude(id=1)

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

    recommended_projects = get_project_recommendation(request=results, limit=limit)
    print("\n\nrecommended_projects: ", recommended_projects)

    return JsonResponse(results)


def get_project_recommendation(request, limit):
    profile_details = request.get('profile_details')
    similarity_result = request.get('similarity_result')
    recommended_projects = []

    try:
        if profile_details and similarity_result and similarity_result[0].get('score') > 0:
            profile_id = profile_details.get('id')
            projects = Project.objects.filter(author=profile_id)[:limit]
            serialized_projects = ProjectSerializer(projects, many=True).data

            if serialized_projects:
                return serialized_projects

            for project in projects:
                project_template = project.project_template
                categories = project.categories.all()
                tasks = project.tasks.all()

                serialized_project = ProjectSerializer(project).data
                project_template_data = {
                    'template_id': project_template.template_id,
                    'title': project_template.title,
                    'description': project_template.description,
                } if project_template else {}

                serialized_categories = [{'category_id': cat.category_id, 'name': cat.name} for cat in categories]
                serialized_tasks = [{
                    'task_id': task.task_id, 'task_name': task.task_name,
                    'description': task.description, 'task_status': task.task_status
                } for task in tasks]

                serialized_project.update({
                    'template': project_template_data,
                    'categories': serialized_categories,
                    'tasks': serialized_tasks,
                })

                recommended_projects.append(serialized_project)

        return recommended_projects
    except Exception as e:
        print("Error: ", e)
        return []

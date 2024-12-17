import traceback
import django_filters
from rest_framework import generics
from django.http import JsonResponse
from chatbot.models import Profile
from chatbot.utils.shikshalokam_mitra_utils import create_project_utils
from shikshalokam.models import Project, Task, Evidence
from shikshalokam.serializer import ProjectSerializer
from rest_framework.decorators import api_view
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist


class ProjectListCreateView(generics.ListCreateAPIView):
    queryset = Project.objects.prefetch_related('task__evidence').select_related(
        'project_template__category', 'author'
    ).all()
    serializer_class = ProjectSerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['id', 'project_id', 'program_id']


@api_view(['POST'])
@transaction.atomic
def duplicate_project_view(request):
    body = request.query_params
    project_id = body.get("id")
    user_id = body.get("userId")

    access_token = request.headers.get("accessToken")

    if not access_token or not user_id or not project_id:
        return JsonResponse({'message': f"Access token and userid and projectid is required"}, status=404)


    try:
        new_author = Profile.objects.get(userid=user_id)
    except Profile.DoesNotExist:
        return JsonResponse({'message': f"Profile not found for userid: {user_id}"}, status=404)

    try:
        original_project = Project.objects.prefetch_related('task__evidence').get(id=project_id)
        user_action_steps = [task.task_name for task in original_project.task.all()]

        try:
            duration = int(original_project.expected_duration) if original_project.expected_duration else None
        except ValueError:
            duration = None

        response = create_project_utils(
            access_token=access_token, user_problem_statement=original_project.expected_problem_statement,
            user_action_steps=user_action_steps, project_title=original_project.expected_title,
            project_duration_weeks=duration
        )

        print("response: ", response)
        if not response:
            return JsonResponse({'message': 'Error in Shikshalokam Project API'}, status=500, safe=False)

        project_id = response.get('programId')
        program_id = response.get('projectId')


        duplicate_project = Project.objects.create(
            **{
                field.name: getattr(original_project, field.name)
                for field in Project._meta.fields
                if field.name not in ['id', 'author', 'project_id', 'program_id', 'created_at', 'updated_at', 'history']
            },
            project_id=project_id,
            program_id=program_id,
            author=new_author,
        )

        for original_task in original_project.task.all():
            duplicate_task = Task.objects.create(
                **{
                    field.name: getattr(original_task, field.name)
                    for field in Task._meta.fields
                    if field.name not in ['id', 'project', 'created_at', 'updated_at', 'history', 'created_by']
                },
                project=duplicate_project
            )

            for original_evidence in original_task.evidence.all():
                Evidence.objects.create(
                    **{
                        field.name: getattr(original_evidence, field.name)
                        for field in Evidence._meta.fields
                        if field.name not in ['id', 'created_at', 'updated_at', 'history', 'created_by']
                    },
                    task=duplicate_task
                )

        serialized_project = ProjectSerializer(duplicate_project).data

        return JsonResponse(serialized_project, status=200, safe=False)


    except ObjectDoesNotExist:
        traceback.print_exc()

        return JsonResponse({'message': f"Project with id {project_id} does not exist."}, status=404, safe=False)

    except Exception as e:
        traceback.print_exc()

        return JsonResponse({
            'message': f"An error occurred while duplicating the project: {str(e)}"
        }, status=500, safe=False)

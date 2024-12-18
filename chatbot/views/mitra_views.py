from chatbot.models import Profile
from chatbot.utils.shikshalokam_mitra_utils import create_project_utils, create_mitra_project_utils
from rest_framework.decorators import api_view
from rest_framework.response import Response
from chatbot.utils.mitra_base_utils import get_mitra_paraphrase_utils, generate_objective_utils, \
    generate_action_list_utils, generate_title_utils
from shikshalokam.utils.project_utils import update_project_status_utils
from django.http import JsonResponse


@api_view(['POST'])
def paraphrase_view(request):
    body = request.data
    user_input = body.get('user_input')
    print("User Input: ", user_input)

    paraphrased_output = get_mitra_paraphrase_utils(paraphrase_problem=user_input)
    print("\n\nParaphrased Output: ", paraphrased_output)
    return Response({
        'status': 'ok',
        'paraphrased_output': paraphrased_output
    }, status=200)


@api_view(['POST'])
def generate_objectives_view(request):
    body = request.data
    user_input = body.get('user_input')
    print("User Input: ", user_input)

    objective_list = generate_objective_utils(user_problem_statement=user_input)

    return Response({
        'status': 'ok',
        'objective_list': objective_list
    }, status=200)


@api_view(['POST'])
def generate_action_list_view(request):
    body = request.data
    user_problem_statement = body.get('user_problem_statement')
    user_objective = body.get('user_objective')
    print("User Problem Statement: ", user_problem_statement)
    print("User Objective: ", user_objective)

    input_data = {
        "user_problem_statement": user_problem_statement,
        "user_objective": user_objective
    }
    action_list = generate_action_list_utils(
        input_data=input_data
    )

    return Response({
        'status': 'ok',
        'action_list': action_list
    }, status=200)


@api_view(['POST'])
def generate_title_view(request):
    body = request.data
    user_problem_statement = body.get('user_problem_statement')
    user_objective = body.get('user_objective')
    user_action_list = body.get('user_action_list')
    input_data = {
        "user_problem_statement": user_problem_statement,
        "user_objective": user_objective,
        "user_action_list": user_action_list
    }

    title = generate_title_utils(input_data=input_data)

    return Response({
        'status': 'ok',
        'title': title
    }, status=200)


@api_view(['POST'])
def create_project_view(request):
    body = request.data
    access_token = body.get('access_token')
    session = body.get('session')
    user_problem_statement = body.get('user_problem_statement')
    user_action_steps = body.get('user_action_steps')
    project_duration = body.get('project_duration')
    project_title = body.get('project_title')
    project_objective = body.get('user_objective')
    profile_id = body.get('profile_id')

    print("project_title: ", project_title)
    print("profile_id: ", profile_id)

    response = create_project_utils(
        access_token=access_token, user_problem_statement=user_problem_statement,
        user_action_steps=user_action_steps, project_title=project_title,
        project_duration_weeks=project_duration
    )

    project_id = response.get('programId')
    program_id = response.get('projectId')
    profile = Profile.objects.get(id=profile_id)

    result = ''
    if project_id and program_id and profile:

        result = create_mitra_project_utils(
            profile=profile,
            session=session,
            expected_problem_statement=user_problem_statement,
            project_title=project_title,
            project_duration=project_duration,
            project_objective=project_objective,
            user_action_steps=user_action_steps,
            project_id=project_id,
            program_id=program_id
        )

        print("Result: ", result)

    return Response({
        'status': 'ok',
        'result': response,
        'mitra_result': result
    }, status=200)


@api_view(['POST'])
def update_project_status_view(request):
    body = request.data
    access_token = body.get('access_token')
    project_id = body.get('project_id')
    flow = body.get('flow')

    response = update_project_status_utils(
        project_id=project_id, access_token=access_token, flow=flow
    )

    return JsonResponse(response.get("message"), status=response.get("status"), safe=False)

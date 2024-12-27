import json

from chatbot.models import Profile
from chatbot.translate.ai4Bharat.text_to_text import call_ai4bharat_translation_api
from chatbot.utils.shikshalokam_mitra_utils import create_project_utils, create_mitra_project_utils
from rest_framework.decorators import api_view
from rest_framework.response import Response
from chatbot.utils.mitra_base_utils import get_mitra_paraphrase_utils, generate_objective_utils, \
    generate_action_list_utils, generate_title_utils
from shikshalokam.models import Project
from shikshalokam.utils.project_utils import update_project_status_utils
from django.http import JsonResponse


@api_view(['POST'])
def paraphrase_view(request):
    body = request.data
    user_input = body.get('user_input')
    language = body.get('language')
    print("User Input: ", user_input)

    if language !='en':
        user_input = call_ai4bharat_translation_api(
            source_language=language, target_language='en', message_body=user_input
        )
        print("user_translated_message: ", user_input)

    paraphrased_output = get_mitra_paraphrase_utils(paraphrase_problem=user_input)

    if language !='en' and paraphrased_output.lower() != 'no':
        paraphrased_output = call_ai4bharat_translation_api(
            source_language='en', target_language=language, message_body=paraphrased_output
        )
        print("llm_translated_message: ", paraphrased_output)

    print("\n\nParaphrased Output: ", paraphrased_output)
    return Response({
        'status': 'ok',
        'paraphrased_output': paraphrased_output
    }, status=200)


@api_view(['POST'])
def generate_objectives_view(request):
    body = request.data
    user_input = body.get('user_input')
    language = body.get('language')
    print("User Input: ", user_input)

    if language !='en':
        user_input = call_ai4bharat_translation_api(
            source_language=language, target_language='en', message_body=user_input
        )
        print("user_translated_message: ", user_input)

    objective_list, chunk_response = generate_objective_utils(user_problem_statement=user_input)
    translated_list = None
    if language !='en':
        translated_list = call_ai4bharat_translation_api(
            source_language='en', target_language=language, message_body=json.dumps(objective_list)
        )
        if isinstance(translated_list, str):
            try:
                translated_list = json.loads(translated_list)
            except Exception as e:
                print(e)
        print("llm_translated_message: ", translated_list)
    if translated_list:
        objective_list = translated_list
    print("type of: ", type(objective_list))
    print("type of: ", type(translated_list))
    return Response({
        'status': 'ok',
        'objective_list': objective_list,
        'chunks': chunk_response
    }, status=200)


@api_view(['POST'])
def generate_action_list_view(request):
    body = request.data
    user_problem_statement = body.get('user_problem_statement')
    user_objective = body.get('user_objective')
    language = body.get('language')
    print("User Problem Statement: ", user_problem_statement)
    print("User Objective: ", user_objective)

    if language !='en':
        user_problem_statement = call_ai4bharat_translation_api(
            source_language=language, target_language='en', message_body=user_problem_statement
        )
        print("user_problem_statement: ", user_problem_statement)
        user_objective = call_ai4bharat_translation_api(
            source_language=language, target_language='en', message_body=user_objective
        )
        print("user_objective: ", user_objective)

    input_data = {
        "user_problem_statement": user_problem_statement,
        "user_objective": user_objective
    }

    action_list = generate_action_list_utils(
        input_data=input_data
    )

    if language != 'en':
        for action_item in action_list:
            action_steps = action_item.get('actionSteps', [])
            if action_steps:
                translated_steps = call_ai4bharat_translation_api(
                    source_language='en', target_language=language,
                    message_body=json.dumps(action_steps)
                )

                if isinstance(translated_steps, str):
                    try:
                        translated_steps = json.loads(translated_steps)
                    except Exception as e:
                        print("Error parsing translated steps: ", e)
                        translated_steps = action_steps

                action_item['actionSteps'] = translated_steps

        print("Translated action list: ", action_list)

    print("type of action_list: ", type(action_list))

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
    language = body.get('language')

    if language !='en':
        user_problem_statement = call_ai4bharat_translation_api(
            source_language=language, target_language='en', message_body=user_problem_statement
        )
        print("user_problem_statement: ", user_problem_statement)
        user_objective = call_ai4bharat_translation_api(
            source_language=language, target_language='en', message_body=user_objective
        )
        print("user_objective: ", user_objective)
        user_action_list = call_ai4bharat_translation_api(
            source_language=language, target_language='en', message_body=user_action_list
        )
        print("user_action_list: ", user_action_list)


    input_data = {
        "user_problem_statement": user_problem_statement,
        "user_objective": user_objective,
        "user_action_list": user_action_list
    }

    title = generate_title_utils(input_data=input_data)

    if language != 'en':
        title = call_ai4bharat_translation_api(
            source_language='en', target_language=language, message_body=title
        )
        print("llm_translated_message: ", title)

    print("\n\ntitle Output: ", title)


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
    chunks = body.get('chunks')

    print("project_title: ", project_title)
    print("profile_id: ", profile_id)

    response = create_project_utils(
        access_token=access_token, user_problem_statement=user_problem_statement,
        user_action_steps=user_action_steps, project_title=project_title,
        project_duration_weeks=project_duration, chunks=chunks, session=session,
        status='started'
    )

    project_id = response.get('projectId')
    program_id = response.get('programId')
    profile = Profile.objects.get(id=profile_id)

    result = ''
    if project_id and program_id and profile:

        result = create_mitra_project_utils(
            profile=profile,
            actual_problem_statement=user_problem_statement,
            project_title=project_title,
            project_duration=project_duration,
            project_objective=project_objective,
            user_action_steps=user_action_steps,
            project_id=project_id,
            program_id=program_id,
            chunks=chunks
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

    # required_project = Project.objects.filter(project_id=project_id).first()
    # program_id = required_project.program_id

    response = update_project_status_utils(
        project_id=project_id, access_token=access_token, flow=flow
    )

    return JsonResponse(response.get("message"), status=response.get("status"), safe=False)

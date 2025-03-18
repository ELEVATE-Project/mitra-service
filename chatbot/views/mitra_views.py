import json
import traceback

from chatbot.models import Profile, CompanyBot, Voice, VoiceType, BotVernacular
from chatbot.utils.shikshalokam_mitra_utils import create_project_utils, create_mitra_project_utils
from rest_framework.decorators import api_view
from rest_framework.response import Response
from chatbot.utils.mitra_base_utils import get_mitra_paraphrase_utils, generate_objective_utils, \
    generate_action_list_utils, generate_title_utils, validate_objective_utils, validate_actions_utils, \
    validate_title_utils
from chatbot.utils.shikshalokam_story_utils import update_story_pdf
from chatbot.utils.story_llama_utils import translate_field
from shikshalokam.models import Project
from shikshalokam.utils.project_utils import update_project_status_utils
from django.http import JsonResponse
import json_repair


@api_view(['POST'])
def paraphrase_view(request):
    body = request.data
    user_input = body.get('user_input')
    language = body.get('language')
    should_paraphrase_text = body.get('paraphrase_text')
    print("User Input: ", user_input)

    company_bot = CompanyBot.objects.get(route='/paraphrase')
    voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()
    if language != 'en':
        user_input = translate_field(
            voice_provider=voice_provider, message_body=user_input, source_language=language,
            target_language='en'
        )
        print("user_translated_message: ", user_input)

    paraphrased_output = get_mitra_paraphrase_utils(
        paraphrase_problem=user_input, should_paraphrase_text=should_paraphrase_text
    )

    if language !='en' and isinstance(paraphrased_output, str) and paraphrased_output.lower() != 'no':
        paraphrased_output = translate_field(
            voice_provider=voice_provider, message_body=user_input, target_language=paraphrased_output,
            source_language='en'
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
    print("language: ", language)

    company_bot = CompanyBot.objects.get(route='/objective')
    voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()
    if language != 'en':
        user_input = translate_field(
            voice_provider=voice_provider, message_body=user_input, source_language=language,
            target_language='en'
        )
        print("user_translated_message: ", user_input)

    objective_list, chunk_response = generate_objective_utils(user_problem_statement=user_input)
    translated_list = None
    if language !='en':
        translated_list = translate_field(
            voice_provider=voice_provider, message_body=json.dumps(objective_list), target_language=language,
            source_language='en'
        )
        if isinstance(translated_list, str):
            try:
                translated_list = json_repair.repair_json(translated_list, return_objects=True)
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
def validate_objectives_view(request):
    body = request.data
    user_input = body.get('user_input')
    language = body.get('language')
    print("User Input: ", user_input)

    company_bot = CompanyBot.objects.get(route='/objective')
    bot_vernacular = BotVernacular.objects.filter(company_bot=company_bot, language=language).first()
    error_message = bot_vernacular.error_message if bot_vernacular.error_message else "Please try again!"
    if language !='en':
        voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()
        user_input = translate_field(
            voice_provider=voice_provider, message_body=user_input, source_language=language,
            target_language='en'
        )
        print("user_translated_message: ", user_input)

    response = validate_objective_utils(user_input=user_input)
    return Response({
        'status': 'ok',
        'result': response,
        'error_message': error_message
    }, status=200)


@api_view(['POST'])
def validate_actions_view(request):
    body = request.data
    user_input = body.get('user_input')
    user_objective = body.get('user_objective')
    language = body.get('language')
    problem_statement = body.get('problem_statement')
    print("User Input: ", user_input)
    print("User language: ", language)
    print("User Objective: ", user_objective)
    print("User Problem Statement: ", problem_statement)

    company_bot = CompanyBot.objects.get(route='/action_list')
    bot_vernacular = BotVernacular.objects.filter(company_bot=company_bot, language=language).first()
    error_message = bot_vernacular.error_message if bot_vernacular.error_message else "Please try again!"
    if language !='en':
        voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()

        if isinstance(user_input, list):
            user_input = [
                translate_field(
                    voice_provider=voice_provider, message_body=action, source_language=language,
                    target_language='en'
                ) for action in user_input
            ]
        else:
            user_input = translate_field(
                voice_provider=voice_provider, message_body=user_input, source_language=language,
                target_language='en'
            )
        user_objective = translate_field(
            voice_provider=voice_provider, message_body=user_objective, source_language=language,
            target_language='en'
        )
        problem_statement = translate_field(
            voice_provider=voice_provider, message_body=problem_statement, source_language=language,
            target_language='en'
        )
        print("user_translated_message: ", user_input)
        print("user_translated_objective: ", user_objective)
        print("user_translated_problem_statement: ", problem_statement)
        print("error_translated_message: ", error_message)

    response = validate_actions_utils(
        user_input=user_input, user_objective=user_objective, problem_statement=problem_statement
    )
    return Response({
        'status': 'ok',
        'result': response,
        'error_message': error_message
    }, status=200)


@api_view(['POST'])
def generate_action_list_view(request):
    body = request.data
    user_problem_statement = body.get('user_problem_statement')
    user_objective = body.get('user_objective')
    language = body.get('language')
    print("User Problem Statement: ", user_problem_statement)
    print("User Objective: ", user_objective)
    print("User language: ", language)

    company_bot = CompanyBot.objects.get(route='/action_list')
    voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()
    if language != 'en':
        user_problem_statement = translate_field(
            voice_provider=voice_provider, message_body=user_problem_statement, source_language=language,
            target_language='en'
        )
        user_objective = translate_field(
            voice_provider=voice_provider, message_body=user_objective, source_language=language,
            target_language='en'
        )
        print("user_problem_statement: ", user_problem_statement)
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
                translated_steps =translate_field(
                    voice_provider=voice_provider, message_body=json.dumps(action_steps), target_language=language,
                    source_language='en'
                )

                if isinstance(translated_steps, str):
                    try:
                        translated_steps = json_repair.repair_json(translated_steps, return_objects=True)
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

    company_bot = CompanyBot.objects.get(route='/title')
    voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()
    if language != 'en':
        user_problem_statement = translate_field(
            voice_provider=voice_provider, message_body=user_problem_statement, source_language=language,
            target_language='en'
        )
        user_objective = translate_field(
            voice_provider=voice_provider, message_body=user_objective, source_language=language,
            target_language='en'
        )
        if isinstance(user_action_list, list):
            user_action_list = user_action_list[0]
            user_action_list = user_action_list.get('actionSteps')
            print("user_action_list: ", user_action_list)
            user_action_list = [
                translate_field(
                    voice_provider=voice_provider, message_body=action, source_language=language,
                    target_language='en'
                ) for action in user_action_list
            ]
        else:
            user_action_list = translate_field(
                voice_provider=voice_provider, message_body=user_action_list, source_language=language,
                target_language='en'
            )
        print("user_problem_statement: ", user_problem_statement)
        print("user_objective: ", user_objective)
        print("user_action_list: ", user_action_list)

    input_data = {
        "user_problem_statement": user_problem_statement,
        "user_objective": user_objective,
        "user_action_list": user_action_list
    }

    title = generate_title_utils(input_data=input_data)

    if language != 'en':
        title = translate_field(
            voice_provider=voice_provider, message_body=title, target_language=language,
            source_language='en'
        )
        print("llm_translated_message: ", title)

    print("\n\ntitle Output: ", title)


    return Response({
        'status': 'ok',
        'title': title
    }, status=200)


@api_view(['POST'])
def validate_title_view(request):
    body = request.data
    user_actions = body.get('user_actions')
    user_objective = body.get('user_objective')
    language = body.get('language')
    problem_statement = body.get('problem_statement')
    user_input = body.get('user_input')
    print("User Input: ", user_input)
    print("User Actions: ", user_actions)
    print("User language: ", language)
    print("User Objective: ", user_objective)
    print("User Problem Statement: ", problem_statement)

    company_bot = CompanyBot.objects.get(route='/title')
    bot_vernacular = BotVernacular.objects.filter(company_bot=company_bot, language=language).first()
    error_message = bot_vernacular.error_message if bot_vernacular.error_message else "Please try again!"
    if language != 'en':
        voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()

        if isinstance(user_actions, list):
            user_actions = user_actions[0]
            user_actions = user_actions.get('actionSteps')
            print("user_action_list: ", user_actions)
            user_actions = [
                translate_field(
                    voice_provider=voice_provider, message_body=action, source_language=language,
                    target_language='en'
                ) for action in user_actions
            ]
        else:
            user_actions = translate_field(
                voice_provider=voice_provider, message_body=user_actions, source_language=language,
                target_language='en'
            )
        user_objective = translate_field(
            voice_provider=voice_provider, message_body=user_objective, source_language=language,
            target_language='en'
        )
        problem_statement = translate_field(
            voice_provider=voice_provider, message_body=problem_statement, source_language=language,
            target_language='en'
        )
        user_input = translate_field(
            voice_provider=voice_provider, message_body=user_input, source_language=language,
            target_language='en'
        )
        print("user_translated_message: ", user_input)
        print("user_translated_actions: ", user_actions)
        print("user_translated_objective: ", user_objective)
        print("user_translated_problem_statement: ", problem_statement)
        print("error_translated_message: ", error_message)
    response = validate_title_utils(
        user_input=user_input, user_objective=user_objective, problem_statement=problem_statement,
        user_actions=user_actions
    )
    return Response({
        'status': 'ok',
        'result': response,
        'error_message': error_message
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
    language = body.get('language')

    print("project_title: ", project_title)
    print("profile_id: ", profile_id)

    if not chunks:
        return Response({
            'status': 'error',
            'message': 'Project source cant be empty',
        }, status=500)

    response = create_project_utils(
        access_token=access_token, user_problem_statement=user_problem_statement,
        user_action_steps=user_action_steps, project_title=project_title,
        project_duration_weeks=project_duration, chunks=chunks, session=session,
        project_objective=project_objective, status='started'
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
            chunks=chunks,
            language=language,
            session=session
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
    try:
        project = Project.objects.filter(project_id=project_id).first()
        session = project.story.session
        print("session: ", session)
        update_story_pdf(is_edit_story=True, session=session, access_token=access_token, flow=None)
        response = update_project_status_utils(
            project_id=project_id, access_token=access_token, flow=flow
        )
        return JsonResponse(response.get("message"), status=response.get("status"), safe=False)
    except Exception as e:
        traceback.print_exc()

        print("Error during status update: ", e)
        return JsonResponse({'message': f"{e}"}, status=500)

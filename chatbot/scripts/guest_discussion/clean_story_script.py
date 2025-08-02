import json
import os
from chatbot.models import Story, ChatSession, CompanyChat, CompanyBot, Voice, VoiceType, ChatType, BotVernacular
from chatbot.utils.audio_provider_utils import text_translate_provider
import json_repair
import logging
from django.utils.timezone import make_aware
from datetime import datetime
import boto3
from retrying import retry
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from chatbot.utils.chat_utils import format_message_as_per_bedrock_format
from chatbot.utils.transliterate_utils import transliterate_text

logger = logging.getLogger('django')
llm_retry_number = int(os.getenv('LLM_RETRY_NUMBER', 3))
AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')


###Steps To Follow:
    #First step is to call get_story_count() and store the ids (Adjust the date as needed)
    #Second step is to call clean_specific_stories() and pass the story ids we collected in First Step


def translate_field(voice_provider, message_body, target_language, source_language="en"):
    """For regular translation (used for location)"""
    if not message_body or message_body == '':
        return message_body
    response = text_translate_provider(
        voice_provider=voice_provider, message_body=message_body, target_language=target_language,
        source_language=source_language
    )
    if response.get('status') == 200:
        return response.get('content')
    else:
        return message_body


def transliterate_field(voice_provider, message_body, target_language, source_language="en"):
    """For transliteration (used for names and organizations)"""
    if not message_body or message_body == '':
        return message_body
    is_sentence = ' ' in message_body
    response = transliterate_text(
        voice_provider=voice_provider, message_body=message_body, target_language=target_language,
        source_language=source_language,
        is_sentence=is_sentence
    )
    if response.get('status') == 200:
        return response.get('content')
    else:
        return message_body


def get_prompt_from_company_bot(company_bot):
    """Get prompt from company bot context field"""
    return company_bot.context if company_bot.context else ""


def get_tools_from_company_bot(company_bot):
    """Get tools from company bot tool_context field"""
    if not company_bot.tool_context:
        return None

    try:
        tools = json.loads(company_bot.tool_context)
        return tools
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Error parsing tool_context for company_bot {company_bot.id}: {e}")
        return None


def correct_metadata_for_story(story):
    try:
        if not story.other_params:
            return f"Story ID {story.id} skipped (not translated yet)"

        company_bot = CompanyBot.objects.get(route='/chaupal-story-script')

        prompt = get_prompt_from_company_bot(company_bot)
        if not prompt:
            logger.error(f"No prompt found in company_bot context for {company_bot.id}")
            return f"❌ No prompt found in company_bot context for Story ID {story.id}"

        company_chats = CompanyChat.objects.filter(session=story.session).order_by('created_at')

        flow_company_bot = CompanyBot.objects.get(route='/guided_guest')
        bot_vernacular = BotVernacular.objects.filter(company_bot=flow_company_bot).first()
        intro_to_pass = None
        if bot_vernacular:
            if story.author.first_name == '' or not story.author.first_name:
                intro_to_pass = bot_vernacular.alt_introductory_message
            else:
                intro_to_pass = bot_vernacular.introductory_message

        messages = format_message_as_per_bedrock_format(chats=company_chats, intro=intro_to_pass)

        translate_provider = Voice.objects.filter(
            company_bot=company_bot, type=VoiceType.TextToText
        ).first()

        transliterate_provider = Voice.objects.filter(
            company_bot=company_bot, type=VoiceType.Transliterate
        ).first()

        formatted_prompt = [{"text": prompt}]

        tools = get_tools_from_company_bot(company_bot)
        if not tools:
            logger.error(f"No tools found in company_bot tool_context for {company_bot.id}")
            return f"❌ No tools found in company_bot tool_context for Story ID {story.id}"

        response = handle_bedrock_model(
            system_prompt=formatted_prompt,
            messages=messages,
            model_name=company_bot.llm_model,
            temperature=company_bot.bot_temperature,
            max_token=company_bot.max_token,
            company_bot=company_bot,
            tools=tools
        )
        print("response: ", response)
        logger.info(f"response: {response}")
        result = get_clean_output(response=response)
        print("result: ", result)
        logger.info(f"result: {result}")

        if result and isinstance(result, str):
            result = json_repair.repair_json(result, return_objects=True)

        updated = False
        for key in ["user_name", "location", "organization", "participants_count", "discussion_date"]:
            if value := result.get(key):
                if key in ["user_name", "organization"]:
                    if story.language != 'en':
                        value = transliterate_field(
                            voice_provider=transliterate_provider,
                            message_body=str(value),
                            target_language=story.language,
                            source_language="en"
                        )
                elif key in ["location", "district"]:
                    if story.language != 'en':
                        value = translate_field(
                            voice_provider=translate_provider,
                            message_body=str(value),
                            target_language=story.language,
                            source_language="en"
                        )

                story.other_params[key] = value
                updated = True
            else:
                if key == "organization":
                    story.other_params[key] = ""
                logger.info(f"🔸 {key} missing in Story ID {story.id}")
                print(f"🔸 {key} missing in Story ID {story.id}")

        if updated:
            story.save(update_fields=["other_params"])
            logger.info(f"✅ Updated Story ID {story.id}")
            return f"✅ Updated Story ID {story.id}"
        else:
            logger.info(f"🟡 No changes for Story ID {story.id}")
            return f"🟡 No changes for Story ID {story.id}"

    except Exception as e:
        logger.error(f"❌ Error in Story ID {story.id}: {str(e)}")
        return f"❌ Error in Story ID {story.id}: {str(e)}"


def clean_all_stories(start=0, end=100):
    session_ids = list(
        ChatSession.objects.filter(session_type=ChatType.shikshaChaupal)
        .values_list('session', flat=True)
    )

    stories = Story.objects.filter(session__in=session_ids) \
                  .exclude(other_params=None) \
                  .order_by('-id')[start:end]

    print(f"Cleaning stories from {start} to {end}... Total: {stories.count()}")

    for story in stories:
        print(correct_metadata_for_story(story))


def get_story_count(start_time, end_time):
    if not start_time:
        start_time = make_aware(datetime(2025, 7, 15, 0, 0))
    if not end_time:
        end_time = make_aware(datetime(2025, 7, 28, 23, 59, 59))

    session_ids = list(
        ChatSession.objects.filter(
            session_type=ChatType.shikshaChaupal,
            created_at__gt=start_time,
            created_at__lt=end_time
        )
        .order_by('created_at')
        .values_list('session', flat=True)
    )
    if session_ids:
        logger.info(f"Found {len(session_ids)} sessions")
        logger.info(f"First session ID: {session_ids[0]}, Last session ID: {session_ids[-1]}")

        print("First session id: ", session_ids[0])
        print("Last session id: ", session_ids[-1])
    else:
        print("No sessions found.")

    story_ids = list(
        Story.objects.filter(session__in=session_ids)
        .exclude(other_params=None)
        .order_by('-id')
        .values_list('id', flat=True)
    )

    logger.info(f"Total stories: {len(story_ids)}")
    print(f"Total stories: {len(story_ids)}")
    return story_ids


def clean_specific_stories(story_ids):
    stories = Story.objects.filter(id__in=story_ids)

    print(f"Cleaning {stories.count()} failed stories...")
    logger.info(f"Cleaning {stories.count()} failed stories...")

    for story in stories:
        print(correct_metadata_for_story(story))


def retry_if_result_none(result):
    return result is None


@retry(stop_max_attempt_number=llm_retry_number, retry_on_result=retry_if_result_none, wrap_exception=True)
def handle_bedrock_model(
        company_bot, system_prompt=None, messages=None, max_token=None, temperature=None, top_p=None,
        model_name=None, region_name='us-west-2', tools=None, is_json_response=False
):
    connect_timeout = company_bot.connect_timeout
    read_timeout = company_bot.read_timeout

    boto_config = BotoConfig(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        retries={"mode": "adaptive"}
    )

    bedrock_runtime = boto3.client(
        service_name='bedrock-runtime',
        region_name=region_name,
        aws_access_key_id=AWS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        config=boto_config
    )

    if model_name:
        model_id = model_name
    else:
        model_id = 'meta.llama3-1-8b-instruct-v1:0'

    inference_config = {}

    if max_token:
        inference_config['maxTokens'] = max_token
    if temperature is not None:
        inference_config['temperature'] = temperature
    if top_p:
        inference_config['topP'] = top_p
    if messages and messages[-1]['role'] == 'assistant':
        messages.pop()

    try:
        request_payload = {
            'modelId': model_id,
            'messages': messages,
            'system': system_prompt,
        }
        if inference_config:
            request_payload['inferenceConfig'] = inference_config
        if tools:
            request_payload['toolConfig'] = tools.get('toolConfig', tools)

        response = bedrock_runtime.converse(**request_payload)
        content_arr = response['output']['message']['content']
        content = content_arr[0]
        content_tool = content.get('toolUse')
        if content_tool:
            if isinstance(content_tool, str):
                final_output = json_repair.repair_json(content_tool, return_objects=True)
            else:
                final_output = content_tool
        else:
            content_text = content.get('text')
            json_start = content_text.find('{')
            if json_start != -1:
                json_str = content_text[json_start:]
                json_str = json_str.replace('\n', '').replace('\r', '').strip()
                while json_str and (json_str.endswith("'") or json_str.endswith('"') or json_str.endswith(',')):
                    json_str = json_str[:-1].strip()
                try:
                    final_output = json_repair.repair_json(json_str, return_objects=True)
                except json.JSONDecodeError as e:
                    print('Error decoding JSON: ', e)
                    return None
            elif is_json_response:
                return None
            else:
                return content_text

        return final_output

    except ClientError as e:
        error_response = e.response
        print("❌ ClientError:")
        print("Error Code:", error_response["Error"]["Code"])
        print("Error Message:", error_response["Error"]["Message"])
        print("Request ID:", error_response.get("ResponseMetadata", {}).get("RequestId"))
        return None

    except Exception as e:
        print(f"Error processing request: {e}")
        return None


def get_clean_output(response):
    if response and isinstance(response, dict):
        extracted_data = response.pop("parameters", response.pop("input", None))
        if extracted_data and isinstance(extracted_data, dict):
            response.clear()
            response.update(extracted_data)

    response_json_content = response
    if response_json_content and isinstance(response_json_content, str):
        response_json_content = json_repair.repair_json(response_json_content, return_objects=True)

    if isinstance(response_json_content, dict) and response_json_content.get("type"):
        if "value" in response_json_content:
            value = response_json_content.get("value")
        elif "parameters" in response_json_content:
            value = response_json_content.get("parameters")
        else:
            value = None
        if value and isinstance(value, str) and value.strip():
            value = json_repair.repair_json(value, return_objects=True)
            response_json_content = value
        else:
            response_json_content = {}

    return response_json_content

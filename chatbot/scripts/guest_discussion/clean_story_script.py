import json
import os
from chatbot.models import Story, Profile, ChatSession, CompanyChat, CompanyBot, Voice, VoiceType, ChatType, \
    BotVernacular
from langfuse.decorators import observe
from langfuse.openai import openai
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

logger = logging.getLogger('django')
llm_retry_number = int(os.getenv('LLM_RETRY_NUMBER', 3))
AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')

###Steps To Follow:
    #First step is to call get_story_count() and store the ids (Adjust the date as needed)
    #Second step is to call clean_specific_stories() and pass the story ids we collected in First Step


def translate_field(voice_provider, message_body, target_language, source_language="en"):
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

def format_message_as_per_openai_format(chats, prompt):
    ai_user = Profile.objects.get(id=1)
    messages = [
        {'role': 'system', 'content': prompt},
        {'role': 'user', 'content': "Hello"},
        {'role': 'assistant', 'content': (
            "Welcome! I’m MItra, and I’m here to capture the important discussions from your Shiksha Chaupal. "
            "I know you and your community have shared valuable insights—both challenges and solutions. Before we get "
            "started, can you first tell me your name?"
        )}
    ]
    for chat in chats:
        if chat.receiver == ai_user:
            user_message = chat.translated_message or chat.message
            messages.append({'role': 'user', 'content': user_message})
        else:
            messages.append({'role': 'assistant', 'content': chat.message})
    return messages


def format_prompt():
    return """
You are a data cleaner for field interviews. The conversation below was transcribed from a voice-based survey and may have incorrect or missing metadata.

From the **conversation between the user and the assistant roles only**, extract the following fields **accurately and only if clearly present**:

- "user_name": Name of the person being interviewed (if clearly stated). Do **not** guess or infer from unrelated statements.
- "organization": The name of the school or group the person is associated with. If it's provided as a JSON string, simplify it into a readable string. Ignore if the mention doesn’t resemble an organization.
- "participants_count": EXACT number of people present in the meeting (in numeric form). Ignore vague or unrelated mentions.
- "discussion_date": The date when the meeting happened, strictly in **"YYYY-MM-DD"** format (e.g., "2024-04-12"). 
- "location": Format as "Village, District, State" (e.g., "Udaipur, Rajasthan"). Only return this field if at least one part (district or state) is explicitly mentioned by the user. Do not guess or infer the state from the district unless both are clearly mentioned. If the user provides a state code (e.g., "BR"), expand it to the full name (e.g., "Bihar"). Use proper title case for district and state names.

  ➤ Examples: (For reference only)
    - If user says "Udaipur Rajasthan", return: "Udaipur, Rajasthan"
    - If user says "Udaipur BR", return: "Udaipur, Bihar"
    - If user says only "Rajasthan", return: "Rajasthan" (field is skipped if no district or town-like word is mentioned)
    - If user says only "Udaipur", return: "Udaipur" (no state is added unless explicitly stated)

  If the user provides a complete date in another clear format (like "22 April 2025" or "22 Apr 2025"), reformat it into "YYYY-MM-DD".

   Do **not** guess or infer if the date is incomplete or unclear (e.g., only "February 2025", "22nd", "last week").

NOTE: Only return fields that are explicitly stated or clearly indicated in the conversation. If something is not mentioned or is ambiguous, leave it out of the output.

Respond **only** with a valid JSON object and no extra text or commentary.

Your output must be a VALID JSON:

{
  "user_name": "",
  "location": "",
  "organization": "",
  "participants_count": "",
  "discussion_date": ""
}

"""

def get_tool_call():
    return {
        "toolConfig": {
            "tools": [
                {
                    "toolSpec": {
                        "name": "extract_interview_metadata",
                        "description": "Extract metadata fields from voice-based survey conversations. Only return fields that are explicitly stated or clearly indicated in the conversation. Do not guess or infer missing information.",
                        "inputSchema": {
                            "json": {
                                "type": "object",
                                "properties": {
                                    "user_name": {
                                        "type": "string",
                                        "description": "Name of the person being interviewed (only if clearly stated). Do not guess or infer from unrelated statements."
                                    },
                                    "location": {
                                        "type": "string",
                                        "description": "Location in 'Village, District, State' format (e.g., 'Udaipur, Rajasthan'). Only return if at least district or state is explicitly mentioned. Expand state codes to full names. Use proper title case."
                                    },
                                    "organization": {
                                        "type": "string",
                                        "description": "Name of school or group the person is associated with. Simplify JSON strings into readable format. Ignore if mention doesn't resemble an organization."
                                    },
                                    "participants_count": {
                                        "type": "integer",
                                        "description": "Exact number of people present in the meeting (numeric form only). Ignore vague or unrelated mentions."
                                    },
                                    "discussion_date": {
                                        "type": "string",
                                        "description": "Date when meeting happened in 'YYYY-MM-DD' format only (e.g., '2024-04-12'). Convert clear date formats but do not guess incomplete or unclear dates."
                                    }
                                },
                                "required": ["user_name", "location", "organization", "participants_count", "discussion_date"]
                            }
                        }
                    }
                }
            ]
        }
    }


def correct_metadata_for_story(story):
    try:
        if not story.other_params:
            return f"Story ID {story.id} skipped (not translated yet)"

        prompt = format_prompt()
        company_chats = CompanyChat.objects.filter(session=story.session).order_by('created_at')
        # messages = format_message_as_per_openai_format(chats=company_chats, prompt=prompt)
        flow_company_bot = CompanyBot.objects.get(route='/guided_guest')
        bot_vernacular = BotVernacular.objects.filter(company_bot=flow_company_bot).first()
        intro_to_pass=None
        if bot_vernacular:
            intro_to_pass = bot_vernacular.alt_introductory_message
        messages = format_message_as_per_bedrock_format(chats=company_chats, intro=intro_to_pass)

        company_bot = CompanyBot.objects.get(route='/chaupal-story')
        voice_provider = Voice.objects.filter(
            company_bot=company_bot, type=VoiceType.TextToText
        ).first()
        formatted_prompt = [{"text": prompt}]
        tools = get_tool_call()

        # result = handle_openai_model(
        #     messages=messages,
        #     temperature=0.2,
        #     max_token=4096,
        #     top_p=1.0,
        #     model_name="gpt-4o-mini",
        #     key_name='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',
        #     is_actual_key=True
        # )
        #
        # print("formatted_prompt: ", formatted_prompt)
        # print("messages: ", messages)
        # print("tools: ", tools)

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
        result = get_clean_output(response=response)
        print("result: ", result)

        # print("result: ", result)
        # print("result type: ", type(result))
        if result and isinstance(result, str):
            result = json_repair.repair_json(result, return_objects=True)
        updated = False
        for key in ["user_name", "location", "organization", "participants_count", "discussion_date"]:
            if value := result.get(key):
                # Only translate if it's not a count or date
                if key in ["user_name", "location", "organization"]:
                    if story.language != 'en':
                        value = translate_field(
                            voice_provider=voice_provider,
                            message_body=str(value),
                            target_language=story.language,
                            source_language="en"
                        )
                story.other_params[key] = value
                updated = True
            else:
                if key == "organization":
                    story.other_params[key] = ""
                logger.debug(f"🔸 {key} missing in Story ID {story.id}")
                print(f"🔸 {key} missing in Story ID {story.id}")

        if updated:
            story.save(update_fields=["other_params"])
            logger.debug(f"✅ Updated Story ID {story.id}")

            return f"✅ Updated Story ID {story.id}"
        else:
            logger.debug(f"🟡 No changes for Story ID {story.id}")
            return f"🟡 No changes for Story ID {story.id}"

    except Exception as e:
        logger.debug(f"❌ Error in Story ID {story.id}: {str(e)}")
        return f"❌ Error in Story ID {story.id}: {str(e)}"


@observe()
def handle_openai_model(
        messages, max_token=None, temperature=None, company_bot=None, model_name=None, is_json_response=True,
        stream=False, key_name='OPENAI_API_KEY', is_actual_key=False, tools=None, tool_choice=None, client_choice=None,
        top_p=None
):
    client = client_choice or openai
    client.api_key = key_name if is_actual_key else os.getenv(key_name)

    if not client.api_key:
        raise ValueError(f"No API key found for '{key_name}'")

    request_data = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_token,
        "temperature": temperature,
        "top_p": top_p,
        "response_format": {"type": "json_object"} if is_json_response else None,
        "stream": stream
    }

    # Clean None values
    request_data = {k: v for k, v in request_data.items() if v is not None}

    # print("Requesting model with data:", request_data)
    response = client.chat.completions.create(**request_data)
    # print("Raw response:", response)

    if is_json_response:
        content = response.choices[0].message.content
        return json.loads(content) if content else {}
    elif tools:
        return {} if not response.choices[0].message.tool_calls else response.choices[0].message.content
    else:
        return response.choices[0].message.content


def clean_all_stories(start=0, end=100):
    session_ids = list(
        ChatSession.objects.filter(session_type=ChatType.shikshaChaupal)
        .values_list('session', flat=True)
    )

    stories = Story.objects.filter(session__in=session_ids)\
        .exclude(other_params=None)\
        .order_by('-id')[start:end]

    print(f"Cleaning stories from {start} to {end}... Total: {stories.count()}")

    for story in stories:
        print(correct_metadata_for_story(story))


def get_story_count():
    start_time = make_aware(datetime(2025, 7, 15, 0, 0))
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

    logger.debug(f"Total stories: {len(story_ids)}")
    print(f"Total stories: {len(story_ids)}")
    return story_ids


def clean_specific_stories(story_ids):
    stories = Story.objects.filter(id__in=story_ids)

    print(f"Cleaning {stories.count()} failed stories...")

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

        # 'meta.llama3-1-70b-instruct-v1:0'

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
            request_payload['toolConfig'] = tools.get('toolConfig')

        # print("request_payload: ", request_payload)
        response = bedrock_runtime.converse(**request_payload)
        # print("Response: ", response)
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
                    # print(f"Loads final_output: {final_output}")

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

    # print("response_json_content: ", response_json_content)

    return response_json_content
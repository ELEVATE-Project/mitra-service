import requests
import json
import os
from django.core.validators import URLValidator
from langfuse.decorators import observe
from langfuse.openai import openai
from chatbot.models import LLMModel
import boto3
import json_repair
from retrying import retry, RetryError
import logging
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError


logger = logging.getLogger('django')
validate = URLValidator()
AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
llm_retry_number = int(os.getenv('LLM_RETRY_NUMBER'))


@observe()
def handle_llama_model(
        messages, max_token, model_name=None, is_json_format=True, temperature=None, top_p=None, seed=None, n=None,
        stream=False, url_to_use=None
):

    if url_to_use:
        url = url_to_use
    else:
        url = os.getenv('LLAMA_BASE_URL') + 'v1/chat/completions'
        # finetune_url = os.getenv('LLAMAFINETUNE_BASE_URL') + 'v1/chat/completions'

    payload = {
        "messages": messages,
        "max_tokens": max_token,
    }

    if model_name:
        payload["model"] = model_name
    else:
        payload["model"] = LLMModel.LLAMA_3_1_8B_OPS

    if is_json_format:
        payload["response_format"] = {"type": "json_object"}
    if seed is not None:
        payload["seed"] = seed
    if n is not None:
        payload["n"] = n
    if top_p is not None:
        payload["top_p"] = top_p
    if temperature is not None:
        payload["temperature"] = temperature

    headers = {
        "Content-Type": "application/json"
    }
    response = requests.post(
        url,
        headers=headers,
        data=json.dumps(payload),
        stream=stream
    )
    print(response.content)
    response_str = str(response.content, encoding="utf-8")

    if is_json_format:
        response_json = json.loads(response_str)
        response_content = response_json['choices'][0]['message']['content']
        response_content = response_content.replace('\n', '').replace('\t', '').replace(
            '\r', '').replace('\\n', '').replace('\\t', '').replace('\\r', '')
        print("BEFORE LOADS: ", response_content)
        response_json = json.loads(response_content)
        return response_json
    else:
        return response_str


@observe()
def handle_openai_model(
        messages, max_token=None, temperature=None, company_bot=None, model_name=None, is_json_response=True,
        stream=False, key_name='OPENAI_API_KEY', is_actual_key=False, tools=None, tool_choice=None, client_choice=None,
        top_p=None, system_prompt=None
):
    if client_choice:
        client = client_choice
    else:
        client = openai

    if is_actual_key:
        client_api_key = key_name
    else:
        client_api_key = os.getenv(key_name)

    client.api_key = client_api_key

    if not client.api_key:
        raise ValueError(f"No API key found for '{key_name}'. Please set the environment variable correctly.")

    if model_name:
        model_to_use = model_name
    elif company_bot:
        model_to_use = company_bot.llm_model
    else:
        model_to_use = LLMModel.GPT4_O_MINI

    if system_prompt and isinstance(system_prompt, list):
        messages = system_prompt+messages

    request_data = {
        "model": model_to_use,
        "messages": messages,
    }

    if max_token:
        request_data["max_tokens"]= max_token
    if temperature:
        request_data['temperature']= temperature
    if is_json_response:
        request_data["response_format"] = {"type": "json_object"}
    if stream:
        request_data["stream"] = stream
    if tools:
        request_data["tools"]= tools
        if tool_choice:
            request_data["tool_choice"]= tool_choice
    if top_p:
        request_data['top_p'] = top_p
    print("request_data: ", request_data)
    response = client.chat.completions.create(**request_data)
    print("raw res: ", response)
    if is_json_response:
        response_content = response.choices[0].message.content
        response_json = None
        if response_content:
            response_json = json.loads(response_content)
        return response_json
    elif tools:
        tool_calls = response.choices[0].message.tool_calls
        if tool_calls and len(tool_calls) > 0:
            return {}
        return response.choices[0].message.content if response.choices else response
    else:
        return response.choices[0].message.content if response.choices else response

def retry_if_result_none(result):
    return result is None

@observe()
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
    additional_model_fields = {}

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

        # logger.info('Bedrock request payload: %s', request_payload)
        # print('Conversation Bedrock request payload: ', request_payload)
        response = bedrock_runtime.converse(**request_payload)
        # logger.info('Bedrock response: %s', response)
        # print('Bedrock response: ', response)

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
                    # logger.info('Loads final_output: %s', final_output)
                except json.JSONDecodeError as e:
                    # logger.error('Error decoding JSON: %s', e, exc_info=True)
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
            # return None
    except Exception as e:
        logger.error('Error processing request: %s', e, exc_info=True)
        return None


@observe()
def handle_bedrock_invoke_model(
        messages=None, max_token=None, temperature=None, top_p=None,
        model_name=None, region_name='us-west-2', tools=None
):

    if model_name:
        model_id = model_name
    else:
        model_id = 'meta.llama3-1-8b-instruct-v1:0'
        # model_id = 'meta.llama3-2-3b-instruct-v1:0'

    print("USING MODEL ID: ", model_id)

    print("Messages: ", messages)
    try:

        body = json.dumps({
            "prompt": json.dumps(messages),
            "max_gen_len": max_token,
            "temperature": temperature,
            "top_p": top_p
        })

        bedrock_runtime = boto3.client(
            service_name='bedrock-runtime',
            region_name=region_name,
            aws_access_key_id=AWS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY
        )

        response = bedrock_runtime.invoke_model(
            body=body,
            modelId=model_id,
            accept="application/json",
            contentType="application/json"
        )

        a = response.get('body').read()
        # print(a)
        # print(type(a))
        b = a.decode('utf-8')
        response_body = json.loads(b)
        print(response_body)
        print(type(response_body))

        result = response_body.get('generation', '')
        print("\nResult:\n\t", result)


        return result

    except Exception as e:
        print(f"Error processing request: {e}")

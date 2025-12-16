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

def get_pricing_from_company_bot(company_bot, model_id):
    """Extract pricing from company_bot.other_params"""
    try:
        if not company_bot.other_params:
            return None

        # Parse other_params
        if isinstance(company_bot.other_params, str):
            other_params = json.loads(company_bot.other_params)
        else:
            other_params = company_bot.other_params

        # Check if pricing data exists
        pricing_data = other_params.get('model_pricing')
        if not pricing_data:
            logger.info(f"❌ No pricing_data key found in company bot other params.")
            return None

        logger.info(f"🔍 Searching for model_id: '{model_id}'")
        logger.info(f"🔍 Available pricing keys: {list(pricing_data.keys())}")

        # Get pricing for current model
        model_pricing = pricing_data.get(model_id)
        if not model_pricing:
            logger.info(f"❌ No exact match found for: '{model_id}'")
            model_pricing = pricing_data.get('llama3-3-70b')

        if model_pricing and 'input_cost_per_1k' in model_pricing and 'output_cost_per_1k' in model_pricing:
            return {
                'input': float(model_pricing['input_cost_per_1k']),
                'output': float(model_pricing['output_cost_per_1k'])
            }

        return None

    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        logger.error(f"Error parsing pricing from company_bot.other_params: {e}")
        return None

def retry_if_result_none(result):
    return result is None

@observe()
@retry(stop_max_attempt_number=llm_retry_number, retry_on_result=retry_if_result_none, wrap_exception=True)
def handle_bedrock_model(
        company_bot, system_prompt=None, messages=None, max_token=None, temperature=None, top_p=None,
        model_name=None, region_name='us-west-2', tools=None, is_json_response=False, aws_key=None,
        aws_secret_key=None
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
        aws_access_key_id=aws_key if aws_key else AWS_KEY,
        aws_secret_access_key=aws_secret_key if aws_secret_key else AWS_SECRET_KEY,
        config=boto_config
    )
    print("aws_key used: ", aws_key if aws_key else AWS_KEY)
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
    if messages and (
            len(messages) > company_bot.chat_history_limit
            or messages[-1]['role'] != 'user'
    ):
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]['role'] == 'user':
                messages = messages[max(0, i - company_bot.chat_history_limit): i + 1]
                break
        else:
            messages = []

    try:
        request_payload = {
            'modelId': model_id,
            'messages': messages,
            'system': system_prompt,
        }
        if inference_config:
            request_payload['inferenceConfig'] = inference_config
        if tools:
            print("tools: ", tools)
            request_payload['toolConfig'] = tools.get('toolConfig')

        logger.info('Bedrock request payload: %s', request_payload)
        print('Conversation Bedrock request payload: ', request_payload)
        response = bedrock_runtime.converse(**request_payload)
        # logger.info('Bedrock response: %s', response)
        print('Bedrock response: ', response)

        usage_metrics = response.get('usage', {})
        if usage_metrics:
            logger.info("--------------USAGE METRICS-------------")
            input_tokens = usage_metrics.get('inputTokens', 0)
            output_tokens = usage_metrics.get('outputTokens', 0)
            total_tokens = usage_metrics.get('totalTokens', 0)
            logger.info(f'💰 Token Usage - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}')
            print(f'💰 Token Usage - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}')

            pricing = get_pricing_from_company_bot(
                company_bot=company_bot, model_id=model_id
            )
            if pricing:
                input_cost = (input_tokens / 1000) * pricing['input']
                output_cost = (output_tokens / 1000) * pricing['output']
                total_cost = input_cost + output_cost

                logger.info(
                    f'💵 Model Cost - Input: ${input_cost:.6f} (${pricing["input"]}/1K), Output: ${output_cost:.6f} '
                    f'(${pricing["output"]}/1K), Total: ${total_cost:.6f}')
                print(
                    f'💵 Model Cost - Input: ${input_cost:.6f} (${pricing["input"]}/1K), Output: ${output_cost:.6f} '
                    f'(${pricing["output"]}/1K), Total: ${total_cost:.6f}')
            else:
                logger.info('💵 No pricing data configured in company_bot.other_params')
                print('💵 No pricing data configured in company_bot.other_params')

            # Log additional metrics if available
            if 'stopReason' in response.get('stopReason', ''):
                stop_reason = response.get('stopReason')
                logger.info(f'🛑 Stop Reason: {stop_reason}')
                print(f'🛑 Stop Reason: {stop_reason}')
        else:
            logger.info('⚠️ No usage metrics found in response')
            print('⚠️ No usage metrics found in response')

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
                    print(f"Loads final_output: {final_output}")
                    logger.info('Loads final_output: %s', final_output)
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
            logger.error("❌ Bedrock ClientError:")
            logger.error(f"Error Code: {error_response['Error']['Code']}")
            logger.error(f"Error Message: {error_response['Error']['Message']}")
            logger.error(f"Request ID: {error_response.get('ResponseMetadata', {}).get('RequestId')}")
            print("❌ ClientError:")
            print("Error Code:", error_response["Error"]["Code"])
            print("Error Message:", error_response["Error"]["Message"])
            print("Request ID:", error_response.get("ResponseMetadata", {}).get("RequestId"))
            # return None
    except Exception as e:
        logger.error('Error processing request: %s', e, exc_info=True)
        print(f'❌ Error processing Bedrock request: {e}')
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

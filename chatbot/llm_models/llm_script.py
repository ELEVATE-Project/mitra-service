import requests
import json
import os
from django.core.validators import URLValidator
from langfuse.decorators import observe
from langfuse.openai import openai
from chatbot.models import LLMModel
import json_repair
from retrying import retry
import logging
from chatbot.utils.llm import LLM
from chatbot.models.enums import LLMProvider


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
    
    if model_name:
        model_id = model_name
    else:
        model_id = 'meta.llama3-1-8b-instruct-v1:0'

    print("aws_key used: ", aws_key if aws_key else AWS_KEY)
    
    # Prepare LLM environment configuration
    llm_env_conf = {
        "AWS_REGION": region_name,
        "AWS_ACCESS_KEY_ID": aws_key if aws_key else AWS_KEY,
        "AWS_SECRET_ACCESS_KEY": aws_secret_key if aws_secret_key else AWS_SECRET_KEY
    }
    
    # Clean up messages - remove last assistant message if present
    if messages and messages[-1]['role'] == 'assistant':
        messages.pop()
    
    # Add system prompt to messages if provided
    # TODO: Check if system prompt is a string or a list
    formatted_messages = []
    if system_prompt:
        if isinstance(system_prompt, list):
            formatted_messages.extend(system_prompt)
        else:
            formatted_messages.append({"role": "system", "content": system_prompt})
    formatted_messages.extend(messages)

    try:
        # Initialize LLM client with LiteLLM
        llm = LLM(
            model=model_id,
            provider=LLMProvider.BEDROCK,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_token,
            llm_env_conf=llm_env_conf
        )
        
        # Prepare tools in LiteLLM format if provided
        litellm_tools = None
        if tools:
            print("tools: ", tools)
            # LiteLLM expects tools in OpenAI format, convert if necessary
            # TODO: Check if tools is a dictionary or a list
            litellm_tools = tools.get('toolConfig', {}).get('tools', []) if isinstance(tools, dict) else tools
        
        logger.info('LiteLLM Bedrock request - Model: %s, Messages count: %d', model_id, len(formatted_messages))
        print(f'LiteLLM Bedrock request - Model: {model_id}, Messages count: {len(formatted_messages)}')
        
        # Make the LLM call using LiteLLM
        response = llm.prompt(messages=formatted_messages, tools=litellm_tools)
        
        print('LiteLLM Bedrock response: ', response)

        # Extract usage metrics from LiteLLM response
        usage_metrics = getattr(response, 'usage', None)
        if usage_metrics:
            logger.info("--------------USAGE METRICS-------------")
            input_tokens = getattr(usage_metrics, 'prompt_tokens', 0)
            output_tokens = getattr(usage_metrics, 'completion_tokens', 0)
            total_tokens = getattr(usage_metrics, 'total_tokens', 0)
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
        else:
            logger.info('⚠️ No usage metrics found in response')
            print('⚠️ No usage metrics found in response')

        # Extract content from LiteLLM response (OpenAI format)
        if not response.choices or len(response.choices) == 0:
            logger.error('No choices in response')
            return None
            
        message = response.choices[0].message
        
        # Check for tool calls first
        tool_calls = getattr(message, 'tool_calls', None)
        if tool_calls and len(tool_calls) > 0:
            tool_call = tool_calls[0]
            if hasattr(tool_call, 'function'):
                function_args = tool_call.function.arguments

                final_output = {
                    "name": tool_call.function.name,
                    "input": function_args
                }

                return final_output
        
        # Extract text content
        content_text = message.content
        if not content_text:
            return None
            
        # Try to extract JSON from content
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
                return final_output
            except json.JSONDecodeError as e:
                if is_json_response:
                    return None
                return content_text
        elif is_json_response:
            return None
        else:
            return content_text

    except Exception as e:
        logger.error('Error processing LiteLLM request: %s', e, exc_info=True)
        print(f'❌ Error processing LiteLLM Bedrock request: {e}')
        return None


@observe()
def handle_bedrock_invoke_model(
        messages=None, max_token=None, temperature=None, top_p=None,
        model_name=None, region_name='us-west-2', tools=None, aws_key=None,
        aws_secret_key=None
):
    if model_name:
        model_id = model_name
    else:
        model_id = 'meta.llama3-1-8b-instruct-v1:0'
        # model_id = 'meta.llama3-2-3b-instruct-v1:0'

    print("USING MODEL ID: ", model_id)

    print("Messages: ", messages)
    try:
        # Prepare LLM environment configuration
        llm_env_conf = {
            "AWS_REGION": region_name,
            "AWS_ACCESS_KEY_ID": aws_key if aws_key else AWS_KEY,
            "AWS_SECRET_ACCESS_KEY": aws_secret_key if aws_secret_key else AWS_SECRET_KEY
        }

        # Initialize LLM client with LiteLLM
        llm = LLM(
            model=model_id,
            provider=LLMProvider.BEDROCK,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_token,
            llm_env_conf=llm_env_conf
        )

        # Prepare tools in LiteLLM format if provided
        litellm_tools = None
        if tools:
            print("tools: ", tools)
            litellm_tools = tools.get('toolConfig', {}).get('tools', []) if isinstance(tools, dict) else tools

        logger.info('LiteLLM Bedrock invoke_model - Model: %s, Messages count: %d', model_id, len(messages))
        print(f'LiteLLM Bedrock invoke_model - Model: {model_id}, Messages count: {len(messages)}')

        # Make the LLM call using LiteLLM
        response = llm.prompt(messages=messages, tools=litellm_tools)

        print('LiteLLM Bedrock response: ', response)

        # Extract usage metrics from LiteLLM response
        usage_metrics = getattr(response, 'usage', None)
        if usage_metrics:
            input_tokens = getattr(usage_metrics, 'prompt_tokens', 0)
            output_tokens = getattr(usage_metrics, 'completion_tokens', 0)
            total_tokens = getattr(usage_metrics, 'total_tokens', 0)
            logger.info(f'💰 Token Usage - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}')
            print(f'💰 Token Usage - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}')

        # Extract content from LiteLLM response
        if not response.choices or len(response.choices) == 0:
            logger.error('No choices in response')
            return None

        message = response.choices[0].message

        a = response.get('body').read()
        # print(a)
        # print(type(a))
        b = a.decode('utf-8')
        response_body = json.loads(b)
        print(response_body)
        print(type(response_body))

        # Extract and return text content
        result = response_body.get('generation', '')
        print("\nResult:\n\t", result)

        return result

    except Exception as e:
        logger.error('Error processing LiteLLM invoke_model request: %s', e, exc_info=True)
        print(f"❌ Error processing request: {e}")
        return None

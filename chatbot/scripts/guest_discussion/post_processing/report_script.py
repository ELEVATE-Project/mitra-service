from typing import List, Dict, Any
from tqdm import tqdm
from chatbot.models import CompanyBot
import json
import os
import boto3
import json_repair
from retrying import retry
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor, as_completed


# -------------- CONFIG ------------------
INPUT_FILE = 'chatbot/scripts/report/ReportList.json'
OUTPUT_FILE = 'chatbot/scripts/report/final_output.json'
MAX_WORKERS = 4
BATCH_SIZE = 20
llm_retry_number = int(os.getenv('LLM_RETRY_NUMBER', 3))
AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
# -------------- LLM CALL ------------------

def build_prompt(challenges: List[str], solutions: List[str]) -> List[Dict[str, Any]]:
    challenge_str = "\n".join([f"{i+1}. {c}" for i, c in enumerate(challenges)])
    solution_str = "\n".join([f"{i+1}. {s}" for i, s in enumerate(solutions)])

    message = f"""
    These are the challenges and solution from the report:
CHALLENGES:
{challenge_str}

SOLUTIONS:
{solution_str}
"""
    return [{"role": "user", "content": [{"text": message.strip()}]}]


def chunk_data(data: List[Any], batch_size: int) -> List[List[Any]]:
    return [data[i:i + batch_size] for i in range(0, len(data), batch_size)]


def process_stories_parallel(stories: List[Dict[str, Any]]) -> None:
    results = {}

    # Load existing output
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            try:
                results = json.load(f)
            except json.JSONDecodeError:
                print("⚠️ Output file is corrupted. Starting fresh.")

    processed_ids = set(results.keys())
    remaining_stories = [s for s in stories if s["id"] not in processed_ids]
    story_batches = chunk_data(remaining_stories, BATCH_SIZE)

    print(f"🔧 Processing {len(story_batches)} batches with {MAX_WORKERS} workers (batch size = {BATCH_SIZE})...")

    def process_one_batch(batch: List[Dict[str, Any]]) -> Dict[str, Any]:
        batch_results = {}
        for story in batch:
            story_result = call_llm_for_story(story)
            batch_results.update(story_result)
        return batch_results

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_one_batch, batch) for batch in story_batches]

        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing Story Batches"):
            batch_output = future.result()
            results.update(batch_output)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"✅ Output saved to {OUTPUT_FILE}")


def call_llm_for_story(story: Dict[str, Any]) -> Dict[str, Any]:
    story_id = story["id"]
    data = json.loads(story["data"])
    challenges = data.get("challenges", [])
    solutions = data.get("solutions", [])

    if not challenges or not solutions:
        return {story_id: {"reorder_steps": []}}

    messages = build_prompt(challenges, solutions)
    company_bot = CompanyBot.objects.filter(route='/script_report').first()
    if not company_bot:
        return {story_id: {"error": "No bot found"}}

    tools = company_bot.tool_context
    if tools and isinstance(tools, str):
        tools = json_repair.repair_json(tools, return_objects=True)

    formatted_prompt = [{"text": company_bot.context}]
    response = handle_bedrock_model(
        system_prompt=formatted_prompt,
        messages=messages,
        model_name=company_bot.llm_model,
        temperature=company_bot.bot_temperature,
        max_token=company_bot.max_token,
        company_bot=company_bot,
        tools=tools
    )
    cleaned = get_clean_output(response=response)
    return {story_id: {"reorder_steps": cleaned}}

# -------------- MAIN ------------------

def run_story_matcher(input_file: str = INPUT_FILE):
    with open(input_file, "r") as f:
        data = json.load(f)

    print(f"🚀 Loaded {len(data)} stories")
    process_stories_parallel(data)



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

    response_json_content = response.get('reorder_steps')
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
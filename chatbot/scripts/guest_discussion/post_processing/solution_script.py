import uuid
from typing import List, Dict, Any
from tqdm import tqdm
from chatbot.models import CompanyBot, LLMModel
import json
import os
import boto3
import json_repair
from retrying import retry
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor, as_completed
from langfuse.openai import openai


# -------------- CONFIG ------------------
INPUT_FILE = 'chatbot/scripts/solutions/all_solutions.json'
OUTPUT_FILE = 'chatbot/scripts/solutions/llm_unique_solutions_output.json'
SECOND_OUTPUT_FILE = 'chatbot/scripts/solutions/flat_solutions_output.json'
BATCH_SIZE = 6000
MAX_WORKERS = 1
llm_retry_number = int(os.getenv('LLM_RETRY_NUMBER'))
AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')

# -------------- CORE FUNCTIONS ------------------

def chunk_data(data: List[str], batch_size: int) -> List[List[str]]:
    return [data[i:i + batch_size] for i in range(0, len(data), batch_size)]

def build_user_message(batch: List[str], company_bot) -> List[Dict[str, Any]]:
    solutions_text = "\n".join([f"- {solution}" for solution in batch])
    messages = [
        {'role': 'system', 'content': company_bot.context},
        {
            'role': 'user',
            'content': f"""Given the list of solutions below, identify and return a JSON list of **unique and consolidated** solutions:\n\n{solutions_text}\n\nRespond ONLY in this format:\n[\n  "unique solution 1",\n  "unique solution 2"\n]"""
        }
    ]
    # return [
    #     {
    #         'role': 'user',
    #         'content': [{
    #             'text': f"""Given the list of solutions below, identify and return a JSON list of **unique and consolidated** solutions:\n\n{solutions_text}\n\nRespond ONLY in this format:\n[\n  "unique solution 1",\n  "unique solution 2"\n]"""
    #         }]
    #     }
    # ]

    return messages

def call_llm(batch: List[str], index: int) -> Dict[str, Any]:
    company_bot = CompanyBot.objects.filter(route='/solutions_script').first()
    messages = build_user_message(batch, company_bot)
    if not company_bot:
        return {f"batch_{index}_error": "No Bot Found"}

    # tool = company_bot.tool_context
    # if tool and isinstance(tool, str):
    #     tool = json_repair.repair_json(tool, return_objects=True)

    # formatted_prompt = [{
    #     'text': company_bot.context
    # }]

    # output = handle_bedrock_model(
    #     system_prompt=formatted_prompt, messages=messages, model_name=company_bot.llm_model,
    #     temperature=company_bot.bot_temperature, max_token=company_bot.max_token, company_bot=company_bot,
    #     tools=tool
    # )

    output = handle_openai_model(
        messages=messages,
        temperature=0.0,
        max_token=32768,
        top_p=1.0,
        model_name=LLMModel.GPT4_1_MINI,
        key_name='OPENAI_API_KEY',
        is_actual_key=False
    )

    if output:
        output=get_clean_output(response=output)

    key = f"solution"
    return {key: output}


def process_all_batches(data: List[str], batch_size: int = BATCH_SIZE, max_workers: int = MAX_WORKERS, save_to_file: bool = True) -> Dict[str, Any]:
    chunks = chunk_data(data, batch_size)
    results = {}

    # Load existing output if present and saving to file
    if save_to_file and os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            try:
                results = json.load(f)
            except json.JSONDecodeError:
                print("⚠️ Warning: Output file is corrupted or empty, starting fresh.")

    print(f"🚀 Starting processing of {len(chunks)} batches with {max_workers} workers...")

    def run_one_batch(idx_batch):
        idx, batch = idx_batch
        print(f"[Worker] Running batch {idx}")
        result = call_llm(batch, idx)
        return idx, result

    # Parallel execution
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_one_batch, (i, chunk)) for i, chunk in enumerate(chunks)]

        for future in tqdm(as_completed(futures), total=len(futures), desc="Batches Completed"):
            idx, result = future.result()
            batch_key = f"solution_{idx}"
            results[batch_key] = result.get("solution")

    if save_to_file:
        with open(OUTPUT_FILE, "w") as f:
            json.dump(results, f, indent=2)
        print(f"✅ Saved {len(chunks)} batches to {OUTPUT_FILE}")
    
    return results


# -------------- DB FETCHING ------------------
def fetch_solutions_from_db(date_from: str, date_till: str) -> List[str]:
    from datetime import datetime
    from chatbot.models import Story, SessionFlowName
    
    try:
        # Parse dates (DD-MM-YYYY format)
        start_date = datetime.strptime(date_from, '%d-%m-%Y')
        end_date = datetime.strptime(date_till, '%d-%m-%Y')
        
        # Make end_date inclusive by setting to end of day
        end_date = end_date.replace(hour=23, minute=59, second=59)
        
        # Query stories in date range
        stories = Story.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date
        ).values_list('other_params', flat=True)
        
        solutions = []
        guest_discussion_flow = SessionFlowName.GuestDiscussion.value  # 'guest-discussion'
        
        for other_params in stories:
            if other_params and isinstance(other_params, dict):
                # Filter by flow
                flow = other_params.get('flow')
                if flow != guest_discussion_flow:
                    continue
                
                # Extract solutions from 'solutions_discussed'
                solutions_discussed = other_params.get('solutions_discussed')
                
                if solutions_discussed:
                    # Handle both list and string formats
                    if isinstance(solutions_discussed, list):
                        for solution in solutions_discussed:
                            if isinstance(solution, str) and solution.strip():
                                solutions.append(solution.strip())
                    elif isinstance(solutions_discussed, str) and solutions_discussed.strip():
                        # Single string - add it directly
                        solutions.append(solutions_discussed.strip())
        
        # Handle empty results
        if not solutions:
            print(f"⚠️ No solutions found in date range {date_from} to {date_till}")
            print(f"   Stories fetched: {stories.count()}, Flow filter: {guest_discussion_flow}")
            return []
        
        print(f"✓ Fetched {len(solutions)} solutions from {stories.count()} stories")
        print(f"  Date range: {date_from} to {date_till}")
        return solutions
        
    except Exception as e:
        print(f"❌ Error fetching from database: {e}")
        import traceback
        traceback.print_exc()
        return []


# -------------- ENTRY POINT ------------------
def run_unique_solution_processing(
    start: int = 0, 
    end: int = None, 
    input_file: str = None,
    input_data: List[str] = None,
    date_from: str = None,
    date_till: str = None,
    batch_size: int = BATCH_SIZE,
    max_workers: int = MAX_WORKERS
):
    solutions = None
    
    # Priority: input_data > date_range > input_file
    if input_data:
        print(f"📥 Using provided input data")
        solutions = input_data
    elif date_from and date_till:
        print(f"📅 Fetching solutions from database: {date_from} to {date_till}")
        solutions = fetch_solutions_from_db(date_from, date_till)
        if not solutions:
            print("❌ No solutions fetched from database. Exiting.")
            return
    elif input_file:
        print(f"📂 Loading solutions from file: {input_file}")
        with open(input_file, "r") as f:
            solutions = json.load(f)
    else:
        print("❌ No input source provided. Please provide input_data, date range, or input_file.")
        return

    # Normalize solutions to list of strings
    if isinstance(solutions, list) and all(isinstance(c, dict) and 'solution' in c for c in solutions):
        solutions = [c['solution'] for c in solutions]

    total = len(solutions)
    end = end if end is not None else total
    selected_solutions = solutions[start:end]

    print(f"🚀 Processing {len(selected_solutions)} solutions from index {start} to {end} (Total available: {total})")
    
    return process_all_batches(selected_solutions, batch_size=batch_size, max_workers=max_workers, save_to_file=True)



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

        print("request_payload: ", request_payload)
        response = bedrock_runtime.converse(**request_payload)
        print("Response: ", response)
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
    print("Cleaning: ", response)
    if response and isinstance(response, dict):
        extracted_data = response.pop("parameters", response.pop("input", None))
        if extracted_data and isinstance(extracted_data, dict):
            response.clear()
            response.update(extracted_data)

    response_json_content = response.get('unique_solutions')
    reason_content = response.get('reason_for_uniqueness')
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

    print("response_json_content: ", response_json_content)
    print("reason_content: ", reason_content)

    return response_json_content


def convert_solutions_to_flat_list(batch_results: Dict[str, Any] = None, output_file_path=OUTPUT_FILE, save_to_file: bool = True, save_file_path=SECOND_OUTPUT_FILE) -> List[str]:
    flat_solutions = []

    # Use provided batch_results or load from file
    if batch_results is not None:
        solutions_dict = batch_results
    else:
        # Check if output file exists
        if not os.path.exists(output_file_path):
            print(f"⚠️ Warning: Output file {output_file_path} not found.")
            return flat_solutions

        # Read data from output file
        try:
            with open(output_file_path, "r") as f:
                solutions_dict = json.load(f)
        except json.JSONDecodeError:
            print(f"⚠️ Warning: Output file {output_file_path} is corrupted or empty.")
            return flat_solutions
        except Exception as e:
            print(f"❌ Error reading file {output_file_path}: {e}")
            return flat_solutions

    # Iterate through all solution batches and extract plain strings
    for batch_key, solutions_list in solutions_dict.items():
        # Check if the value is a list and not None
        if isinstance(solutions_list, list):
            # Add each solution string directly (not as dict)
            for solution_item in solutions_list:
                if isinstance(solution_item, str) and solution_item.strip():
                    # Already a string
                    flat_solutions.append(solution_item.strip())
                elif isinstance(solution_item, dict) and 'solution' in solution_item:
                    # Extract string from dict
                    solution_text = solution_item['solution']
                    if isinstance(solution_text, str) and solution_text.strip():
                        flat_solutions.append(solution_text.strip())

    print("Len flat_solutions: ", len(flat_solutions))

    # Save the flat solutions to a new file only if requested
    if save_to_file:
        try:
            with open(save_file_path, "w") as f:
                json.dump(flat_solutions, f, indent=2)
            print(f"✅ Converted solutions saved to {save_file_path}")
        except Exception as e:
            print(f"❌ Error saving to file {save_file_path}: {e}")

    return flat_solutions


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


# -------------- MAIN EXECUTION ------------------
if __name__ == "__main__":
    # Hardcoded date range for testing
    DATE_FROM = "01-01-2026"  # DD-MM-YYYY
    DATE_TILL = "10-02-2026"  # DD-MM-YYYY
    
    print(f"\n{'='*60}")
    print(f"🚀 SOLUTION SCRIPT - DIRECT EXECUTION")
    print(f"{'='*60}")
    print(f"📅 Date Range: {DATE_FROM} to {DATE_TILL}")
    print(f"{'='*60}\n")
    
    # Run the processing
    run_unique_solution_processing(
        date_from=DATE_FROM,
        date_till=DATE_TILL
    )
    
    print(f"\n{'='*60}")
    print(f"✅ Script execution completed!")
    print(f"{'='*60}\n")
    
    # Convert to flat list
    print("🔄 Converting to flat list...")
    convert_solutions_to_flat_list()
    print("✅ Flat list conversion completed!")

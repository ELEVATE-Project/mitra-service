from typing import List, Dict, Any
from tqdm import tqdm
from chatbot.models import CompanyBot
import json
import os
import json_repair
from retrying import retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from chatbot.utils.llm import LLM
from chatbot.models.enums import LLMProvider


# -------------- CONFIG ------------------
INPUT_FILE = 'chatbot/scripts/challenges/all_challenges_v3.json'
OUTPUT_FILE = 'chatbot/scripts/challenges/llm_unique_challenges_output.json'
SECOND_OUTPUT_FILE = 'chatbot/scripts/challenges/flat_challenges_output.json'
BATCH_SIZE = 100
MAX_WORKERS = 4
llm_retry_number = int(os.getenv('LLM_RETRY_NUMBER'))
AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
# 5336 --> 4500 --> 4000 --> 3500 --> 3100 --> (274 llm calls till now)
# -------------- CORE FUNCTIONS ------------------

def chunk_data(data: List[str], batch_size: int) -> List[List[str]]:
    return [data[i:i + batch_size] for i in range(0, len(data), batch_size)]

def build_user_message(batch: List[str]) -> List[Dict[str, Any]]:
    challenges_text = "\n".join([f"- {challenge}" for challenge in batch])
    return [
        {
            'role': 'user',
            'content': [{
                'text': f"""Given the list of challenges below, identify and return a JSON list of **unique and consolidated** challenges:\n\n{challenges_text}\n\nRespond ONLY in this format:\n[\n  "unique challenge 1",\n  "unique challenge 2"\n]"""
            }]
        }
    ]

def call_llm(batch: List[str], index: int) -> Dict[str, Any]:
    messages = build_user_message(batch)
    company_bot = CompanyBot.objects.filter(route='/challenges_script').first()
    if not company_bot:
        return {f"batch_{index}_error": "No Bot Found"}

    tool = company_bot.tool_context
    if tool and isinstance(tool, str):
        tool = json_repair.repair_json(tool, return_objects=True)

    formatted_prompt = [{
        'text': company_bot.context
    }]

    output = handle_bedrock_model(
        system_prompt=formatted_prompt, messages=messages, model_name=company_bot.llm_model,
        temperature=company_bot.bot_temperature, max_token=company_bot.max_token, company_bot=company_bot,
        tools=tool
    )
    if output:
        output=get_clean_output(response=output)

    key = f"challenge"
    return {key: output}


def process_all_batches(data: List[str]) -> None:
    chunks = chunk_data(data, BATCH_SIZE)
    results = {}

    # Load existing output if present
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            try:
                results = json.load(f)
            except json.JSONDecodeError:
                print("⚠️ Warning: Output file is corrupted or empty, starting fresh.")

    print(f"🚀 Starting processing of {len(chunks)} batches with {MAX_WORKERS} workers...")

    def run_one_batch(idx_batch):
        idx, batch = idx_batch
        print(f"[Worker] Running batch {idx}")
        result = call_llm(batch, idx)
        return idx, result

    # Parallel execution
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(run_one_batch, (i, chunk)) for i, chunk in enumerate(chunks)]

        for future in tqdm(as_completed(futures), total=len(futures), desc="Batches Completed"):
            idx, result = future.result()
            batch_key = f"challenge_{idx}"
            results[batch_key] = result.get("challenge")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"✅ Appended {len(chunks)} new batches to {OUTPUT_FILE}")


# -------------- ENTRY POINT ------------------
def run_unique_challenge_processing(start: int = 0, end: int = None, input_file: str = INPUT_FILE):
    with open(input_file, "r") as f:
        challenges = json.load(f)

    if isinstance(challenges, list) and all(isinstance(c, dict) and 'challenge' in c for c in challenges):
        challenges = [c['challenge'] for c in challenges]

    total = len(challenges)
    end = end if end is not None else total
    selected_challenges = challenges[start:end]

    print(f"🚀 Loaded {len(selected_challenges)} challenges from index {start} to {end} (Total available: {total})")
    process_all_batches(selected_challenges)



def retry_if_result_none(result):
    return result is None

@retry(stop_max_attempt_number=llm_retry_number, retry_on_result=retry_if_result_none, wrap_exception=True)
def handle_bedrock_model(
        company_bot, system_prompt=None, messages=None, max_token=None, temperature=None, top_p=None,
        model_name=None, region_name='us-west-2', tools=None, is_json_response=False
):
    # use default model if not provided
    if model_name:
        model_id = model_name
    else:
        model_id = 'meta.llama3-1-8b-instruct-v1:0'
        # 'meta.llama3-1-70b-instruct-v1:0'

    # remove last assistant message if exists
    if messages and messages[-1]['role'] == 'assistant':
        messages.pop()

    # Prepare system message if system_prompt provided
    if system_prompt:
        # Convert system_prompt format to messages format
        if isinstance(system_prompt, list) and len(system_prompt) > 0:
            system_text = system_prompt[0].get('text', '')
            if system_text:
                messages = [{'role': 'system', 'content': system_text}] + messages

    try:
        # Initialize LLM with liteLLM
        llm = LLM(
            model=model_id,
            provider=LLMProvider.BEDROCK,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_token
        )

        print("request_payload: ", {
            'model': model_id,
            'messages': messages,
            'temperature': temperature,
            'top_p': top_p,
            'max_tokens': max_token,
            'tools': tools
        })

        # Call LLM
        response = llm.prompt(messages=messages, tools=tools)
        print("Response: ", response)

        # extract content from response
        content_arr = response.choices[0].message.content
        
        # Check for tool calls
        if hasattr(response.choices[0].message, 'tool_calls') and response.choices[0].message.tool_calls:
            tool_call = response.choices[0].message.tool_calls[0]
            if isinstance(tool_call.function.arguments, str):
                final_output = json_repair.repair_json(tool_call.function.arguments, return_objects=True)
            else:
                final_output = tool_call.function.arguments
        else:
            # extract JSON from text content
            content_text = content_arr if isinstance(content_arr, str) else str(content_arr)
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

    except Exception as e:
        print(f"Error processing request: {e}")
        return None


def get_clean_output(response):
    if response and isinstance(response, dict):
        extracted_data = response.pop("parameters", response.pop("input", None))
        if extracted_data and isinstance(extracted_data, dict):
            response.clear()
            response.update(extracted_data)

    response_json_content = response.get('unique_challenges')
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


def convert_challenges_to_flat_list(output_file_path=OUTPUT_FILE, save_file_path=SECOND_OUTPUT_FILE):
    flat_challenges = []

    # Check if output file exists
    if not os.path.exists(output_file_path):
        print(f"⚠️ Warning: Output file {output_file_path} not found.")
        return flat_challenges

    # Read data from output file
    try:
        with open(output_file_path, "r") as f:
            challenges_dict = json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ Warning: Output file {output_file_path} is corrupted or empty.")
        return flat_challenges
    except Exception as e:
        print(f"❌ Error reading file {output_file_path}: {e}")
        return flat_challenges

    # Iterate through all challenge batches
    for batch_key, challenges_list in challenges_dict.items():
        # Check if the value is a list and not None
        if isinstance(challenges_list, list):
            # Add each challenge string as a separate dictionary
            for challenge_text in challenges_list:
                if challenge_text and isinstance(challenge_text, str):
                    flat_challenges.append({"challenge": challenge_text})

    # print("flat_challenges: ", flat_challenges)

    # Save the flat challenges to a new file
    try:
        with open(save_file_path, "w") as f:
            json.dump(flat_challenges, f, indent=2)
        print(f"✅ Converted challenges saved to {save_file_path}")
    except Exception as e:
        print(f"❌ Error saving to file {save_file_path}: {e}")

    print("Len flat_challenges: ", len(flat_challenges))
    return flat_challenges

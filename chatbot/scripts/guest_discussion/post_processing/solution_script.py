from chatbot.models import CompanyBot, LLMModel
from concurrent.futures import ThreadPoolExecutor, as_completed
from langfuse.openai import openai
from tqdm import tqdm
from typing import List, Dict, Any
import json
import json_repair
import os


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
        key_name='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',
        is_actual_key=True
    )

    if output:
        output=get_clean_output(response=output)

    key = f"solution"
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
            batch_key = f"solution_{idx}"
            results[batch_key] = result.get("solution")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"✅ Appended {len(chunks)} new batches to {OUTPUT_FILE}")


# -------------- ENTRY POINT ------------------
def run_unique_solution_processing(start: int = 0, end: int = None, input_file: str = INPUT_FILE):
    with open(input_file, "r") as f:
        solutions = json.load(f)

    if isinstance(solutions, list) and all(isinstance(c, dict) and 'solution' in c for c in solutions):
        solutions = [c['solution'] for c in solutions]

    total = len(solutions)
    end = end if end is not None else total
    selected_solutions = solutions[start:end]

    print(f"🚀 Loaded {len(selected_solutions)} solutions from index {start} to {end} (Total available: {total})")
    process_all_batches(selected_solutions)



def retry_if_result_none(result):
    return result is None

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


def convert_solutions_to_flat_list(output_file_path=OUTPUT_FILE, save_file_path=SECOND_OUTPUT_FILE):
    flat_solutions = []

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

    # Iterate through all solution batches
    for batch_key, solutions_list in solutions_dict.items():
        # Check if the value is a list and not None
        if isinstance(solutions_list, list):
            # Add each solution string as a separate dictionary
            for solution_text in solutions_list:
                if solution_text and isinstance(solution_text, str):
                    flat_solutions.append({"solution": solution_text})

    print("flat_solutions: ", flat_solutions)
    print("Len flat_solutions: ", len(flat_solutions))

    # Save the flat solutions to a new file
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

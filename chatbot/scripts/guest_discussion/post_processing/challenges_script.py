from typing import List, Dict, Any, Optional, Tuple
from tqdm import tqdm
from chatbot.models import CompanyBot
import json
import os
import json_repair
from retrying import retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from chatbot.utils.llm import LLM
from chatbot.models.enums import LLMProvider
from chatbot.llm_models.llm_script import handle_bedrock_model


# -------------- CONFIG ------------------
INPUT_FILE = 'chatbot/scripts/guest_discussion/post_processing/chaupal_four_challenge.json'
OUTPUT_FILE = 'chatbot/scripts/challenges/llm_unique_challenges_output.json'
SECOND_OUTPUT_FILE = 'chatbot/scripts/challenges/flat_challenges_output.json'
DEFAULT_BATCH_SIZE = 5
DEFAULT_MAX_WORKERS = 2
llm_retry_number = int(os.getenv('LLM_RETRY_NUMBER', '3'))
AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
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
    try:
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
            output = get_clean_output(response=output)

        key = f"challenge"
        return {key: output}
    except Exception as e:
        print(f"Error in call_llm for batch {index}: {str(e)}")
        return {"challenge": None}


def process_all_batches(
    data: List[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_workers: int = DEFAULT_MAX_WORKERS,
    save_to_file: bool = False,
    output_file: str = OUTPUT_FILE
) -> Dict[str, Any]:
    """Process all batches and return results dictionary.
    """
    chunks = chunk_data(data, batch_size)
    results = {}

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
            batch_key = f"challenge_{idx}"
            results[batch_key] = result.get("challenge")

    if save_to_file:
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        print(f"✅ Saved {len(chunks)} batches to {output_file}")

    return results


# -------------- ENTRY POINT ------------------
def run_unique_challenge_processing(
    start: int = 0,
    end: int = None,
    input_file: str = None,
    input_data: List[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_workers: int = DEFAULT_MAX_WORKERS,
    save_to_file: bool = False,
    output_file: str = OUTPUT_FILE,
    second_output_file: str = SECOND_OUTPUT_FILE
) -> Tuple[Dict[str, Any], List[str]]:
    """Run unique challenge processing.
    """
    # Get challenges from input_data or input_file
    if input_data is not None:
        challenges = input_data
    elif input_file:
        with open(input_file, "r") as f:
            challenges = json.load(f)
    else:
        input_file = INPUT_FILE
        with open(input_file, "r") as f:
            challenges = json.load(f)

    # Extract challenge strings if input is list of dicts
    if isinstance(challenges, list) and all(isinstance(c, dict) and 'challenge' in c for c in challenges):
        challenges = [c['challenge'] for c in challenges]

    total = len(challenges)
    end = end if end is not None else total
    selected_challenges = challenges[start:end]

    print(f"🚀 Loaded {len(selected_challenges)} challenges from index {start} to {end} (Total available: {total})")
    
    # Process batches
    batch_results = process_all_batches(
        selected_challenges,
        batch_size=batch_size,
        max_workers=max_workers,
        save_to_file=save_to_file,
        output_file=output_file
    )

    # Convert to flat list
    flat_challenges = convert_challenges_to_flat_list(
        batch_results=batch_results,
        save_to_file=save_to_file,
        save_file_path=second_output_file
    )
    
    return batch_results, flat_challenges



def retry_if_result_none(result):
    return result is None

def get_clean_output(response):
    try:
        if isinstance(response, str):
            try:
                response = json_repair.repair_json(response, return_objects=True)
            except Exception:
                return None

        if isinstance(response, list):
            cleaned = []

            for item in response:
                if isinstance(item, str):
                    cleaned.append(item.strip())

                elif isinstance(item, dict) and "challenge" in item:
                    val = item.get("challenge")
                    if isinstance(val, str) and val.strip():
                        cleaned.append(val.strip())

            return cleaned if cleaned else None

        if isinstance(response, dict):
            if 'type' in response and 'value' in response:
                return get_clean_output(response.get('value'))
            
            # Extract from common parameter keys
            extracted = (
                response.get("parameters")
                or response.get("input")
                or response.get("unique_challenges")
            )

            return get_clean_output(extracted)

        return None
    except Exception as e:
        print(f"Error in get_clean_output: {str(e)}")
        return None



def convert_challenges_to_flat_list(
    batch_results: Dict[str, Any] = None,
    output_file_path: str = OUTPUT_FILE,
    save_to_file: bool = False,
    save_file_path: str = SECOND_OUTPUT_FILE
) -> List[str]:
    """
    Convert batch-wise LLM output into a single flat list of strings.
    """
    flat_challenges = []
    
    # Use provided batch_results or load from file
    if batch_results is not None:
        challenges_dict = batch_results
    else:
        # Check if output file exists
        if not os.path.exists(output_file_path):
            print(f"⚠️ Warning: Output file {output_file_path} not found.")
            return flat_challenges

        # Load batch output
        try:
            with open(output_file_path, "r") as f:
                challenges_dict = json.load(f)
        except Exception as e:
            print(f"❌ Error reading {output_file_path}: {e}")
            return flat_challenges

    # Flatten
    for _, challenges_list in challenges_dict.items():
        if isinstance(challenges_list, list):
            for challenge in challenges_list:
                if isinstance(challenge, str) and challenge.strip():
                    flat_challenges.append(challenge.strip())

    # Save flat list if requested
    if save_to_file:
        try:
            with open(save_file_path, "w") as f:
                json.dump(flat_challenges, f, indent=2)
            print(f"✅ Converted challenges saved to {save_file_path}")
        except Exception as e:
            print(f"❌ Error saving file: {e}")

    print("Len flat_challenges:", len(flat_challenges))
    return flat_challenges


if __name__ == "__main__":
    run_unique_challenge_processing()

from typing import List, Dict, Any
from tqdm import tqdm
from chatbot.models import CompanyBot, Story
import json
import os
import boto3
import json_repair
from retrying import retry
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.db import transaction

# -------------- CONFIG ------------------
MASTER_VILLAGES_FILE = 'chatbot/scripts/guest_discussion/master_villages.json'
MAX_WORKERS = 4
BATCH_SIZE = 20
llm_retry_number = int(os.getenv('LLM_RETRY_NUMBER', 3))
AWS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')


# -------------- LLM CALL ------------------

def build_prompt(location: str, master_villages: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """Build prompt for village name mapping"""

    # Format the master villages data for the prompt
    villages_text = ""
    for district, villages in master_villages.items():
        villages_list = ", ".join(villages)
        villages_text += f"\n{district.upper()} district: {villages_list}"

    message = f"""
    MASTER VILLAGES LIST (by district):
    {villages_text}

    LOCATION TO MAP: "{location}"
    """

    return [{"role": "user", "content": [{"text": message.strip()}]}]


def chunk_data(data: List[Any], batch_size: int) -> List[List[Any]]:
    """Split data into chunks for parallel processing"""
    return [data[i:i + batch_size] for i in range(0, len(data), batch_size)]


def load_master_villages() -> Dict[str, List[str]]:
    """Load master villages JSON file"""
    try:
        with open(MASTER_VILLAGES_FILE, "r", encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ Master villages file not found: {MASTER_VILLAGES_FILE}")
        return {}
    except json.JSONDecodeError:
        print(f"❌ Invalid JSON in master villages file: {MASTER_VILLAGES_FILE}")
        return {}


def process_stories_parallel(stories: List[Story], master_villages: Dict[str, List[str]]) -> Dict[str, List[int]]:
    """Process stories in parallel batches"""

    if not master_villages:
        print("❌ No master villages data available")
        return {"skipped_no_english_json": [], "failed_village_mapping": []}

    # Filter stories and track skipped ones
    stories_to_process = []
    skipped_no_english_json = []

    for story in stories:
        if story.other_params:
            # Check if english_json exists
            english_json = story.other_params.get('english_json', {})
            location = english_json.get('location') or story.other_params.get('location')

            if not location:
                skipped_no_english_json.append(story.id)
                continue

            # Check if village mapping already exists
            if 'village' not in story.other_params:
                stories_to_process.append(story)

    print(f"📊 Summary:")
    print(f"   - Total stories: {len(stories)}")
    print(f"   - Skipped (no english_json): {len(skipped_no_english_json)}")
    print(f"   - To process: {len(stories_to_process)}")

    if not stories_to_process:
        print("✅ No stories need village mapping")
        return {
            "skipped_no_english_json": skipped_no_english_json,
            "failed_village_mapping": []
        }

    story_batches = chunk_data(stories_to_process, BATCH_SIZE)

    print(
        f"🔧 Processing {len(stories_to_process)} stories in {len(story_batches)} batches with {MAX_WORKERS} workers (batch size = {BATCH_SIZE})...")

    def process_one_batch(batch: List[Story]) -> Dict[str, List]:
        batch_results = []
        batch_failed = []
        for story in batch:
            result = call_llm_for_village_mapping(story, master_villages)
            if result:
                batch_results.append(result)
            else:
                batch_failed.append(story.id)
        return {"successful": batch_results, "failed": batch_failed}

    all_updates = []
    failed_village_mapping = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_one_batch, batch) for batch in story_batches]

        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing Story Batches"):
            batch_output = future.result()
            all_updates.extend(batch_output["successful"])
            failed_village_mapping.extend(batch_output["failed"])

    # Bulk update stories
    update_stories_in_db(all_updates)

    # Final summary
    print(f"\n📋 FINAL SUMMARY:")
    print(f"   ✅ Successfully processed: {len(all_updates)} stories")
    print(f"   ⚠️  Skipped (no english_json): {len(skipped_no_english_json)} stories")
    print(f"   ❌ Failed village mapping: {len(failed_village_mapping)} stories")

    return {
        "skipped_no_english_json": skipped_no_english_json,
        "failed_village_mapping": failed_village_mapping
    }


def call_llm_for_village_mapping(story: Story, master_villages: Dict[str, List[str]]) -> Dict[str, Any]:
    """Call LLM to map story location to village name"""

    try:
        # Get location from english_json if available
        location = ''
        if story.other_params:
            english_json = story.other_params.get('english_json', {})
            location = english_json.get('location', '')

            if not location:
                location = story.other_params.get('location', '')

        if not location:
            print(f"⚠️  Story {story.id}: No location found in english_json or other_params")
            return None

        messages = build_prompt(location, master_villages)
        company_bot = CompanyBot.objects.filter(route='/script_village_mapping').first()

        if not company_bot:
            print("❌ No bot found for route '/script_village_mapping'")
            return None

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
        print("----------------------------------")
        print("response: ", response)
        cleaned_response = get_clean_output(response=response)
        print("cleaned_response: ", cleaned_response)
        print("----------------------------------")

        if cleaned_response and isinstance(cleaned_response, dict):
            village_name = cleaned_response.get('village', 'others')
            district_name = cleaned_response.get('district', 'others')
            return {
                'story_id': story.id,
                'village': village_name,
                'district': district_name,
                'original_location': location
            }

        print(f"❌ Story {story.id}: Failed to get valid response from LLM")
        return None

    except Exception as e:
        print(f"❌ Error processing story {story.id}: {e}")
        return None


def update_stories_in_db(updates: List[Dict[str, Any]]) -> None:
    """Bulk update stories in database"""

    try:
        with transaction.atomic():
            for update in updates:
                story_id = update['story_id']
                village = update['village']
                district = update['district']

                try:
                    story = Story.objects.get(id=story_id)
                    if not story.other_params:
                        story.other_params = {}

                    story.other_params['village'] = village
                    story.other_params['district'] = district
                    english_json = story.other_params.get('english_json')
                    if not english_json or not isinstance(english_json, dict):
                        pass
                    else:
                        story.other_params['english_json']['village'] = village
                        story.other_params['english_json']['district'] = district


                    story.save(update_fields=['other_params'])

                    print(f"✅ Updated story {story_id}: {update['original_location']} -> {village}, {district}")

                except Story.DoesNotExist:
                    print(f"❌ Story {story_id} not found")
                except Exception as e:
                    print(f"❌ Error updating story {story_id}: {e}")

    except Exception as e:
        print(f"❌ Database transaction error: {e}")


# -------------- MAIN ------------------

def run_village_mapper(story_queryset=None) -> Dict[str, List[int]]:
    """Main function to run village mapping"""

    # Load master villages data
    master_villages = load_master_villages()
    if not master_villages:
        return {"skipped_no_english_json": [], "failed_village_mapping": []}

    # Get stories to process
    if story_queryset is None:
        # Get all stories that have other_params but no village mapping yet
        stories = Story.objects.filter(
            other_params__isnull=False
        ).exclude(
            other_params__village__isnull=False
        )
    else:
        stories = story_queryset

    stories_list = list(stories)
    print(f"🚀 Found {len(stories_list)} stories to analyze")

    if not stories_list:
        print("✅ No stories found to process")
        return {"skipped_no_english_json": [], "failed_village_mapping": []}

    return process_stories_parallel(stories_list, master_villages)


# -------------- UTILITY FUNCTIONS ------------------

def retry_if_result_none(result):
    return result is None


@retry(stop_max_attempt_number=llm_retry_number, retry_on_result=retry_if_result_none, wrap_exception=True)
def handle_bedrock_model(
        company_bot, system_prompt=None, messages=None, max_token=None, temperature=None, top_p=None,
        model_name=None, region_name='us-west-2', tools=None, is_json_response=False
):
    """Handle Bedrock model calls - keeping original function unchanged"""
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
    """Clean and extract output from LLM response"""
    print("Type of response: ", type(response))
    if response and isinstance(response, dict):
        extracted_data = response.pop("parameters", response.pop("input", None))
        print("extracted_data: ", extracted_data, " & type: ", type(extracted_data))
        if extracted_data and isinstance(extracted_data, dict):
            response.clear()
            response.update(extracted_data)

    response_json_content = response
    if response_json_content and isinstance(response_json_content, str) and "{" in response_json_content:
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


# -------------- USAGE EXAMPLES ------------------

# -------------- ANALYSIS FUNCTIONS ------------------

def analyze_skipped_stories(story_ids: List[int]) -> None:
    """Analyze stories that were skipped due to missing english_json"""
    if not story_ids:
        print("✅ No stories were skipped")
        return

    stories = Story.objects.filter(id__in=story_ids)

    print(f"\n🔍 ANALYSIS OF SKIPPED STORIES ({len(story_ids)} total):")
    print("=" * 50)

    for story in stories[:10]:  # Show first 10 as sample
        location = story.other_params.get('location', 'N/A') if story.other_params else 'N/A'
        print(f"Story ID: {story.id}")
        print(f"  Location: {location}")
        print(f"  Has english_json: {'english_json' in (story.other_params or {})}")
        print("-" * 30)

    if len(stories) > 10:
        print(f"... and {len(stories) - 10} more stories")


def analyze_failed_stories(story_ids: List[int]) -> None:
    """Analyze stories that failed village mapping"""
    if not story_ids:
        print("✅ No stories failed village mapping")
        return

    stories = Story.objects.filter(id__in=story_ids)

    print(f"\n🔍 ANALYSIS OF FAILED STORIES ({len(story_ids)} total):")
    print("=" * 50)

    for story in stories[:10]:  # Show first 10 as sample
        english_json = story.other_params.get('english_json', {}) if story.other_params else {}
        location = english_json.get('location', 'N/A')
        print(f"Story ID: {story.id}")
        print(f"  English Location: {location}")
        print("-" * 30)

    if len(stories) > 10:
        print(f"... and {len(stories) - 10} more stories")


def get_village_mapping_stats() -> Dict[str, Any]:
    """Get statistics about village mappings"""
    total_stories = Story.objects.filter(other_params__isnull=False).count()

    stories_with_english_json = Story.objects.filter(
        other_params__english_json__isnull=False
    ).count()

    stories_with_village = Story.objects.filter(
        other_params__village__isnull=False
    ).count()

    # Get village distribution
    village_distribution = {}
    stories_with_villages = Story.objects.filter(
        other_params__village__isnull=False
    ).values_list('other_params', flat=True)

    for other_params in stories_with_villages:
        village = other_params.get('village', 'unknown')
        village_distribution[village] = village_distribution.get(village, 0) + 1

    stats = {
        'total_stories_with_other_params': total_stories,
        'stories_with_english_json': stories_with_english_json,
        'stories_with_village_mapping': stories_with_village,
        'village_distribution': village_distribution,
        'most_common_villages': sorted(village_distribution.items(), key=lambda x: x[1], reverse=True)[:10]
    }

    print(f"\n📊 VILLAGE MAPPING STATISTICS:")
    print("=" * 40)
    print(f"Total stories with other_params: {stats['total_stories_with_other_params']}")
    print(f"Stories with english_json: {stats['stories_with_english_json']}")
    print(f"Stories with village mapping: {stats['stories_with_village_mapping']}")
    print(f"Unique villages mapped: {len(village_distribution)}")
    print(f"\nTop 10 villages:")
    for village, count in stats['most_common_villages']:
        print(f"  {village}: {count} stories")

    return stats


# -------------- USAGE EXAMPLES ------------------

def run_for_specific_stories(story_ids: List[int]) -> Dict[str, List[int]]:
    """Run village mapping for specific story IDs"""
    stories = Story.objects.filter(id__in=story_ids)
    summary = run_village_mapper(story_queryset=stories)

    # Analyze results
    analyze_skipped_stories(summary['skipped_no_english_json'])
    analyze_failed_stories(summary['failed_village_mapping'])

    return summary


def run_for_date_range(start_date, end_date) -> Dict[str, List[int]]:
    """Run village mapping for stories in date range"""
    stories = Story.objects.filter(
        created_at__gte=start_date,
        created_at__lte=end_date,
        other_params__isnull=False
    ).exclude(
        other_params__village__isnull=False
    )
    summary = run_village_mapper(story_queryset=stories)

    # Analyze results
    analyze_skipped_stories(summary['skipped_no_english_json'])
    analyze_failed_stories(summary['failed_village_mapping'])

    return summary

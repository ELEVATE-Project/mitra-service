from asgiref.sync import sync_to_async
from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import CompanyBot
from chatbot.utils.chat_query_handler import query_text_search
from chatbot.utils.story_llama_utils import translate_field
from shikshalokam.utils.action_list.action_parser import parse_llm_action_response
from shikshalokam.utils.action_list.action_validator import parse_validator_response, validate_and_fix_action_list
from shikshalokam.utils.chunks_utils import validate_inputs, filter_and_sort_chunks, prepare_chunks_for_template, render_template_with_context
import asyncio
import json_repair
import logging
import json

logger = logging.getLogger('django')

async def generate_action_list_parallel(query, objectives, company_bot, language, voice_provider, max_concurrency: int = 3):
    """Generate action lists for multiple objectives concurrently.

    NOTE: `max_concurrency` is implemented via a per-call semaphore so this function
    can be safely invoked from sync contexts using `async_to_sync` (no cross-event-loop
    semaphore binding).
    """
    sem = asyncio.Semaphore(max_concurrency)

    async def _one(objective):
        async with sem:
            return await asyncio.to_thread(
                generate_action_list_utils,
                query,
                objective,
                company_bot,
                language,
                voice_provider,
            )

    tasks = [_one(objective) for objective in objectives]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(f"parallel_results: {json.dumps(results)}")

    plans_list = []

    master_plan_name = []
    total_duration = 0
    action_steps = []

    for result in results:
        if result['status'] != 'ok':
            logger.error(f"[generate_action_list_view] Generation failed with status: {result['status']}, message: {result.get('message')}")
            raise ValueError(f"Generation failed with status: {result.get('status')}, message: {result.get('message')}")

        else:
            for item in result.get("action_list", []):
                duration_in_weeks = item.get('duration_weeks')

                if isinstance(duration_in_weeks, str):
                    duration_in_weeks = int(duration_in_weeks)

                if isinstance(duration_in_weeks, int):
                    total_duration += duration_in_weeks

                plans_list.append({
                    "plan_name": item['plan_name'],
                    "actionSteps": item['actionSteps'],
                })
                master_plan_name.append(item['plan_name'])


    master_plan_name = ' and '.join(list(set(master_plan_name)))

    combiner_bot = await sync_to_async(CompanyBot.objects.values('tag_context', 'context', 'tool_context', 'llm_model', 'bot_temperature', 'filter_score', 'max_token', 'connect_timeout', 'read_timeout', 'chat_history_limit').get)(route='/action_list_combiner')
    user_input = render_template_with_context(combiner_bot.get("tag_context"), { "plans": plans_list })

    user_message = [{
        'role': 'user',
        'content': [{'text': user_input}]
    }]

    system_prompt = [{'text': combiner_bot.get("context")}]
    tool_context = combiner_bot.get("tool_context")
    tool_context = json_repair.repair_json(tool_context, return_objects=True)

    response = handle_bedrock_model(
        system_prompt=system_prompt, messages=user_message, model_name=combiner_bot.get("llm_model"),
        temperature=combiner_bot.get("bot_temperature"), max_token=combiner_bot.get("max_token"), company_bot=company_bot,
        tools=tool_context, top_p=combiner_bot.get("filter_score"), is_json_response=True
    )

    logger.info(f"Response: {response}")

    if not response or not isinstance(response, dict):
        logger.info("Invalid validation response from LLM: %s", response)

    parsed_response = parse_validator_response(response)

    parsed_response = parsed_response.get("actionSteps", [])

    if isinstance(parsed_response, str):
        parsed_response = json_repair.repair_json(parsed_response, return_objects=True)

    if not isinstance(parsed_response, list):
        logger.error("Invalid response from LLM, `actionSteps` is not a list: %s", parsed_response)
        raise ValueError("Invalid response from LLM, `actionSteps` is not a list")

    for action_step in parsed_response:
        action_steps.append({
            "step": action_step.get("step"),
            "reason": action_step.get("reason", ""),
        })

    # TODO: Get the error message from BotVernacular and display it

    return {
        "status": "ok",
        "message": "Successfully generated action steps",
        "action_list": [
            {
                "plan_name": master_plan_name,
                "duration_weeks": total_duration,
                "actionSteps": action_steps
            }
        ]
    }


def generate_action_list_utils(query, objective_text, company_bot, language, voice_provider, plans=[]):
    try:
        if isinstance(objective_text, list):
            final_objective_text = ""
            for index in range(objective_text):
                final_objective_text += f"{index + 1}. {objective_text[index]}\n"

            objective_text = final_objective_text

        if language != 'en':
            logger.info(f"[generate_action_list_view] Translating inputs from {language} to English")
            query = translate_field(
                voice_provider=voice_provider, message_body=query, source_language=language,
                target_language='en'
            )
            objective_text = translate_field(
                voice_provider=voice_provider, message_body=objective_text, source_language=language,
                target_language='en'
            )
            logger.info(f"[generate_action_list_view] Translated problem statement: {query}")
            logger.info(f"[generate_action_list_view] Translated objective: {objective_text}")

        required_attrs = ['top_k', 'filter_score', 'context', 'tag_context', 'llm_model', 'bot_temperature', 'max_token']

        if not query or not isinstance(query, str):
            return {
                'status': 'error',
                'status_code': 400,
                'action_list': [],
                'chunks_response': None,
                'message': 'Invalid query: must be a non-empty string'
            }

        validation = validate_inputs(objective_text, company_bot, required_attrs)
        if not validation['valid']:
            return {
                'status': 'error',
                'status_code': 400,
                'action_list': [],
                'chunks_response': None,
                'message': validation['message']
            }

        try:
            chunks_response = query_text_search(
                query=objective_text, priority="P1", limit=company_bot.top_k
            )

            if chunks_response.get('error'):
                print(f"Error while fetching chunks: {chunks_response.get('error')}")
                logger.info(f"Error while fetching chunks: {chunks_response.get('error')}")


        except Exception as db_error:
            print(f"Error while fetching chunks: {db_error}")
            logger.info(f"Error while fetching chunks: {db_error}")
            return {
                'status': 'error',
                'status_code': 500,
                'action_list': [],
                'chunks_response': None,
                'message': f'Database query failed: {str(db_error)}'
            }

        filtered_chunks = []
        if chunks_response and chunks_response.get("results"):
            filtered_chunks = filter_and_sort_chunks(
                chunks_response, company_bot.filter_score, company_bot.top_k
            )

        try:
            chunks_data = prepare_chunks_for_template(filtered_chunks)

            context_data = {
                'user_query': query,
                'objective': objective_text,
                'chunks': chunks_data,
                'total_chunks': len(chunks_data),
                "plans": plans
            }

            rendered_content = render_template_with_context(
                company_bot.tag_context, context_data
            )

            messages = [{
                'role': 'user',
                'content': [{'text': rendered_content}]
            }]

            system_prompt = [{'text': company_bot.context}] if company_bot.context else [
                {'text': 'Generate action plans.'}]

            tool_context = company_bot.tool_context
            tool_context = json_repair.repair_json(tool_context, return_objects=True)

            response = handle_bedrock_model(
                system_prompt=system_prompt, messages=messages, model_name=company_bot.llm_model,
                temperature=company_bot.bot_temperature, max_token=company_bot.max_token, company_bot=company_bot,
                tools=tool_context, top_p=company_bot.filter_score,
            )

            try:
                validate_bot = CompanyBot.objects.filter(route='/validate_action_list').first()
                if validate_bot:
                    response = validate_and_fix_action_list(
                        messages=messages, response_json=response, company_bot=validate_bot
                    )
                    logger.info("Validation applied using validate_bot")
                else:
                    logger.info("No validate_bot found with route='/validate_action_list', skipping validation")

            except CompanyBot.DoesNotExist:
                logger.error("validate_bot not found, proceeding without validation")
            except Exception as validation_error:
                logger.error(f"Validation failed: {validation_error}, proceeding with original response")


            if company_bot and company_bot.end_context:
                response = validate_and_fix_action_list(messages=messages, response_json=response, company_bot=company_bot)

            if not response:
                return {
                    'status': 'error',
                    'status_code': 500,
                    'action_list': [],
                    'chunks_response': chunks_response,
                    'message': 'Invalid response from LLM'
                }

            action_list = parse_llm_action_response(response, filtered_chunks)
            logger.info(f"action_list: {action_list}")
            if not action_list:
                raise ValueError("LLM returned empty action list")

        except ValueError as e:
            return {
                'status': 'error',
                'status_code': 422,
                'action_list': [],
                'chunks_response': chunks_response,
                'message': str(e)
            }

        except Exception as llm_error:
            return {
                'status': 'error',
                'status_code': 500,
                'action_list': [],
                'chunks_response': chunks_response,
                'message': f'Error generating actions: {str(llm_error)}'
            }

        total_results = chunks_response.get('total_results', 0)
        return {
            'status': 'ok',
            'status_code': 200,
            'action_list': action_list,
            'filtered_chunks': filtered_chunks,
            'total_actions': len(action_list),
            'total_chunks_used': len(filtered_chunks),
            'total_chunks_found': total_results,
            'total_results': total_results,
            'chunks_response': chunks_response,
            'message': f'Successfully generated {len(action_list)} action plans'
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'status_code': 500,
            'action_list': [],
            'total_actions': 0,
            'total_chunks_used': 0,
            'total_chunks_found': 0,
            'total_results': 0,
            'chunks_response': None,
            'message': f'Internal server error: {str(e)}'
        }

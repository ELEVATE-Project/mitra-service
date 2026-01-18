from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import CompanyBot
from shikshalokam.utils.action_list.action_parser import parse_llm_action_response
from shikshalokam.utils.action_list.action_validator import validate_and_fix_action_list
from shikshalokam.utils.chunks_utils import validate_inputs, filter_and_sort_chunks, prepare_chunks_for_template, \
    render_template_with_context
import json_repair
import logging

logger = logging.getLogger('django')


def generate_action_list_utils(query, objective_text, company_bot):
    try:
        from chatbot.utils.chat_query_handler import query_text_search

        required_attrs = ['top_k', 'filter_score', 'context', 'tag_context', 'llm_model', 'bot_temperature',
                          'max_token']

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
                'total_chunks': len(chunks_data)
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

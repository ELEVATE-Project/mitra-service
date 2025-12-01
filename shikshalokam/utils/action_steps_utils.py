from chatbot.llm_models.llm_script import handle_bedrock_model
from shikshalokam.utils.chunks_utils import validate_inputs, filter_and_sort_chunks, prepare_chunks_for_template, \
    render_template_with_context
import json_repair
import json


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
                return {
                    'status': 'error',
                    'status_code': chunks_response.get('status_code', 500),
                    'action_list': [],
                    'chunks_response': None,
                    'message': chunks_response.get('message', 'API request failed')
                }

        except Exception as db_error:
            return {
                'status': 'error',
                'status_code': 500,
                'action_list': [],
                'chunks_response': None,
                'message': f'Database query failed: {str(db_error)}'
            }

        if not chunks_response or not chunks_response.get("results"):
            return {
                'status': 'ok',
                'status_code': 200,
                'action_list': [],
                'total_actions': 0,
                'total_chunks_used': 0,
                'total_chunks_found': 0,
                'total_results': 0,
                'chunks_response': chunks_response,
                'message': 'No chunks found from text-search API'
            }

        filtered_chunks = filter_and_sort_chunks(
            chunks_response, company_bot.filter_score, company_bot.top_k
        )

        if not filtered_chunks:
            total_chunks = len(chunks_response.get("results", []))
            return {
                'status': 'ok',
                'status_code': 200,
                'action_list': [],
                'total_actions': 0,
                'total_chunks_used': 0,
                'total_chunks_found': total_chunks,
                'total_results': total_chunks,
                'chunks_response': chunks_response,
                'message': f'No chunks met filter criteria'
            }

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

            if not response:
                return {
                    'status': 'error',
                    'status_code': 500,
                    'action_list': [],
                    'chunks_response': chunks_response,
                    'message': 'Invalid response from LLM'
                }

            action_list = parse_llm_action_response(response, filtered_chunks)

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


def parse_llm_action_response(response, filtered_chunks):
    print("llm response: ", response)
    if not response or not isinstance(response, dict):
        return []

    if 'output' in response:
        content = response.get('output', {}).get('message', {}).get('content', [])
        if content and isinstance(content, list):
            for item in content:
                if 'toolUse' in item:
                    tool_input = item['toolUse'].get('input', {})
                    if tool_input:
                        response = tool_input
                        break

    extracted_data = response.pop("parameters", response.pop("input", None))
    if extracted_data and isinstance(extracted_data, dict):
        response = extracted_data

    print("\nextracted_data: ", extracted_data)

    action_plans = (
        response.get('action_plan') or
        response.get('action_list') or
        response.get('action_plans') or
        response.get('actions') or
        []
    )

    if isinstance(action_plans, dict):
        if 'value' in action_plans:
            action_plans = action_plans['value']
        elif 'items' in action_plans:
            action_plans = action_plans['items']

    if isinstance(action_plans, str):
        try:
            action_plans = json_repair.repair_json(action_plans, return_objects=True)
        except:
            try:
                action_plans = json.loads(action_plans)
            except:
                action_plans = []

    if not isinstance(action_plans, list):
        action_plans = [action_plans] if action_plans else []

    action_list = []
    valid_source_ids = {chunk['source_id'] for chunk in filtered_chunks}

    for idx, plan in enumerate(action_plans):
        if isinstance(plan, dict):
            duration = plan.get('duration', '3')
            action_steps = plan.get('actionSteps', []) or plan.get('action_steps', []) or plan.get('steps', [])
            source_id = plan.get('source_id', '')
            chunk_index = plan.get('chunk_index', 0)

            if not source_id or source_id not in valid_source_ids:
                if chunk_index > 0 and chunk_index <= len(filtered_chunks):
                    source_id = filtered_chunks[chunk_index - 1]['source_id']
                elif idx < len(filtered_chunks):
                    source_id = filtered_chunks[idx]['source_id']
                else:
                    continue

            if action_steps and source_id:
                action_list.append({
                    'duration': str(duration),
                    'actionSteps': action_steps,
                    'source_id': source_id
                })

    print(f"\nParsed {len(action_list)} action plans from response")
    return action_list


def post_process_actions_with_source(action_list, filtered_chunks, chunks_response):
    try:
        if not action_list:
            return {
                'status': 'ok',
                'status_code': 200,
                'action_list': [],
                'message': 'No actions to process'
            }

        if not isinstance(action_list, list):
            return {
                'status': 'error',
                'status_code': 400,
                'action_list': [],
                'message': 'Invalid action_list: must be a list'
            }

        source_id_to_score = {chunk['source_id']: chunk['relevance_score'] for chunk in filtered_chunks}

        source_map = {}
        if chunks_response and chunks_response.get("results"):
            try:
                for result in chunks_response["results"]:
                    if not isinstance(result, dict):
                        print(f"Skipping invalid result in post_process: {result}")
                        continue

                    source_id = result.get('source_id', '') or result.get('metadata', {}).get('source_id', '')

                    if not source_id:
                        print(f"Skipping result without source_id: {result}")
                        continue

                    chunk_text = result.get('text', '')
                    metadata = result.get('metadata', {})
                    description = metadata.get('summary', '')
                    title = metadata.get('title', '') or metadata.get('TITLE', '')
                    url = metadata.get('url', '')
                    organization_slug = metadata.get('company', '')

                    organization_dict = {}
                    if organization_slug:
                        try:
                            from chatbot.models import Company
                            company = Company.objects.filter(slug=organization_slug).first()
                            if company:
                                organization_dict = {
                                    'name': company.name,
                                    'slug': company.slug
                                }
                            else:
                                organization_dict = {
                                    'name': organization_slug,
                                    'slug': organization_slug
                                }
                        except Exception as org_error:
                            print(f"Error fetching company for slug '{organization_slug}': {str(org_error)}")
                            organization_dict = {
                                'name': organization_slug,
                                'slug': organization_slug
                            }

                    source_map[source_id] = {
                        'source_id': source_id,
                        'chunk': chunk_text,
                        'description': description,
                        'title': title,
                        'url': url,
                        'organization': organization_dict
                    }
            except Exception as map_error:
                print(f"Error creating source_map: {str(map_error)}")
                return {
                    'status': 'error',
                    'status_code': 500,
                    'action_list': [],
                    'message': f'Error mapping source data: {str(map_error)}'
                }

        processed_actions = []
        for action in action_list:
            try:
                if not isinstance(action, dict):
                    print(f"Skipping invalid action: {action}")
                    continue

                source_id = action.get('source_id', '')
                score = source_id_to_score.get(source_id, 0)
                source_info = source_map.get(source_id, {
                    'source_id': source_id,
                    'chunk': '',
                    'description': '',
                    'title': '',
                    'url': '',
                    'organization': {}
                })

                processed_action = {
                    'duration': action.get('duration', '3'),
                    'actionSteps': action.get('actionSteps', []),
                    'score': score,
                    'source': source_info
                }
                processed_actions.append(processed_action)

            except Exception as action_error:
                print(f"Error processing action: {str(action_error)}")
                continue

        return {
            'status': 'ok',
            'status_code': 200,
            'action_list': processed_actions,
            'message': f'Successfully processed {len(processed_actions)} actions with source information'
        }

    except Exception as e:
        print(f"Unexpected error in post_process_actions_with_source: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'status_code': 500,
            'action_list': [],
            'message': f'Internal server error: {str(e)}'
        }

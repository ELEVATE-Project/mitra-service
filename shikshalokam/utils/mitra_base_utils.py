from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.utils.chat_query_handler import ask
from jinja2 import Template


def get_mitra_paraphrase_utils(paraphrase_problem, should_paraphrase_text, company_bot):
    messages = [{
                    'role': 'user',
                    'content': [{'text': paraphrase_problem}]
                }]

    paraphrase_prompt = company_bot.context
    validation_prompt = company_bot.end_context
    paraphrase_prompt = [{'text': paraphrase_prompt}]
    validation_prompt = [{'text': validation_prompt}]
    print('validation_prompt: ', validation_prompt)
    validation_response = handle_bedrock_model(
        system_prompt=validation_prompt, messages=messages,  model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token, company_bot=company_bot
    )
    print("validation_response: ", validation_response)
    is_validated = validation_response.get('is_validated')
    if is_validated.lower() == 'no' or not should_paraphrase_text:
        return validation_response
    print('paraphrase_prompt: ', paraphrase_prompt)
    paraphrase_response = handle_bedrock_model(
        system_prompt=paraphrase_prompt, messages=messages, model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token, company_bot=company_bot
    )
    print("paraphrase_response: ", paraphrase_response)
    paraphrase_response = paraphrase_response.get('paraphrased_challenge')
    return paraphrase_response


def generate_objective_utils(user_problem_statement, company_bot):
    """
    Generate objectives from user problem statement with proper error handling.
    
    Returns:
        dict: {
            'status': 'ok' | 'error',
            'status_code': 200 | 400 | 500,
            'objective_list': [...],
            'chunks_response': {...},
            'message': 'Success message or error description'
        }
    """
    try:
        from chatbot.utils.chat_query_handler import query_database
        
        # Validate inputs
        if not user_problem_statement or not isinstance(user_problem_statement, str):
            return {
                'status': 'error',
                'status_code': 400,
                'objective_list': [],
                'chunks_response': None,
                'message': 'Invalid user_problem_statement: must be a non-empty string'
            }
        
        if not company_bot:
            return {
                'status': 'error',
                'status_code': 400,
                'objective_list': [],
                'chunks_response': None,
                'message': 'Invalid company_bot: company_bot object is required'
            }
        
        # Validate company_bot attributes
        if not hasattr(company_bot, 'top_k') or not hasattr(company_bot, 'filter_score'):
            return {
                'status': 'error',
                'status_code': 400,
                'objective_list': [],
                'chunks_response': None,
                'message': 'Invalid company_bot: missing required attributes (top_k, filter_score)'
            }
        
        # Step 1: Search Qdrant for relevant chunks based on user question
        try:
            chunks_response = query_database(
                query_prompt=user_problem_statement, 
                priority_filter="p1", 
                limit=company_bot.top_k
            )
        except Exception as db_error:
            print(f"Database query error: {str(db_error)}")
            return {
                'status': 'error',
                'status_code': 500,
                'objective_list': [],
                'chunks_response': None,
                'message': f'Database query failed: {str(db_error)}'
            }
        
        print("chunks_response from Qdrant:", chunks_response)
        
        # Validate chunks_response
        if not chunks_response:
            return {
                'status': 'ok',
                'status_code': 200,
                'objective_list': [],
                'chunks_response': chunks_response,
                'message': 'No chunks found in database for the given query'
            }
    
        # Step 2: Filter and order chunks based on relevance score
        filtered_chunks = []
        if chunks_response and chunks_response.get("results"):
            try:
                for result in chunks_response["results"]:
                    if not isinstance(result, dict):
                        print(f"Skipping invalid result: {result}")
                        continue
                    
                    relevance_score = result.get('field_scores', {}).get('text', 0)
                    print(f"relevance_score: {relevance_score}, filter_score: {company_bot.filter_score}")
                    
                    # Filter based on filter_score - only include chunks with score >= filter_score
                    if relevance_score >= company_bot.filter_score:
                        chunk_text = None
                        if "text" in result and result["text"] is not None and len(result["text"]) > 20:
                            chunk_text = result["text"]
                        elif "translated_text" in result and result["translated_text"] is not None and len(result["translated_text"]) > 20:
                            chunk_text = result["translated_text"]
                        
                        if chunk_text:
                            # Extract source_id from metadata as per JSON structure
                            source_id = result.get('metadata', {}).get('source_id', '') or str(result.get('id', ''))
                            filtered_chunks.append({
                                'chunk_text': chunk_text,
                                'source_id': source_id,
                                'relevance_score': relevance_score,
                                'full_result': result  # Store full result for later use
                            })
            except Exception as filter_error:
                print(f"Error filtering chunks: {str(filter_error)}")
                return {
                    'status': 'error',
                    'status_code': 500,
                    'objective_list': [],
                    'chunks_response': chunks_response,
                    'message': f'Error processing chunks: {str(filter_error)}'
                }
    
        # Sort chunks by relevance_score in descending order
        try:
            filtered_chunks.sort(key=lambda x: x['relevance_score'], reverse=True)
        except Exception as sort_error:
            print(f"Error sorting chunks: {str(sort_error)}")
            # Continue with unsorted chunks
        
        print(f"\nFiltered and sorted chunks count: {len(filtered_chunks)}")
        
        # Step 3: Generate one objective per chunk
        objective_list = []
        
        if not filtered_chunks:
            # If no chunks found, provide detailed message
            total_chunks = len(chunks_response.get("results", []))
            max_score = max([r.get('field_scores', {}).get('text', 0) for r in chunks_response.get("results", [])], default=0)
            
            warning_message = (
                f'No chunks met the filter criteria. '
                f'Found {total_chunks} chunks but all had relevance scores below the threshold. '
                f'Filter threshold: {company_bot.filter_score}, Highest chunk score: {max_score:.4f}. '
                f'Consider lowering the filter_score in company_bot settings.'
            )
            print(f"\n⚠️  WARNING: {warning_message}")
            
            return {
                'status': 'ok',
                'status_code': 200,
                'objective_list': [],
                'chunks_response': chunks_response,
                'message': warning_message
            }
    
        for chunk_data in filtered_chunks:
            try:
                # Validate chunk_data
                if not chunk_data or not isinstance(chunk_data, dict):
                    print(f"Skipping invalid chunk_data: {chunk_data}")
                    continue
                
                if 'chunk_text' not in chunk_data or 'source_id' not in chunk_data:
                    print(f"Skipping chunk_data missing required fields: {chunk_data.keys()}")
                    continue
                
                # Prepare prompt with the chunk
                prompt = company_bot.context if hasattr(company_bot, 'context') else ''
                
                if not prompt:
                    print("Warning: company_bot.context is empty, using default prompt")
                    prompt = "Generate objectives based on the following information:"
                
                # Add chunk to the prompt - each chunk generates ONE objective
                prompt_with_chunk = f"""{prompt}

Use the following chunk to generate ONE objective:

Chunk: {chunk_data['chunk_text']}

User Question: {user_problem_statement}

Generate exactly ONE objective based on this chunk. The objective should be relevant to the user's question and the chunk content."""
                
                messages = [{
                    'role': 'user',
                    'content': [{'text': prompt_with_chunk}]
                }]
                
                system_prompt = [{'text': prompt_with_chunk}]
                
                # Call LLM to generate objective for this chunk
                try:
                    response = handle_bedrock_model(
                        system_prompt=system_prompt, 
                        messages=messages, 
                        model_name=company_bot.llm_model,
                        temperature=company_bot.bot_temperature, 
                        max_token=company_bot.max_token, 
                        company_bot=company_bot
                    )
                except Exception as llm_error:
                    print(f"LLM error for chunk {chunk_data['source_id']}: {str(llm_error)}")
                    # Continue with next chunk instead of failing completely
                    continue
                
                # Validate LLM response
                if not response or not isinstance(response, dict):
                    print(f"Invalid LLM response for chunk {chunk_data['source_id']}: {response}")
                    continue
                
                # Extract objective text from response
                # The LLM returns {'objective_list': ['obj1', 'obj2', ...]}
                # We need to extract the list and create separate entries for each objective
                objectives_from_response = response.get('objective_list', [])
                
                # If objective_list is not present, try other fields
                if not objectives_from_response:
                    objectives_from_response = response.get('objective', [])
                if not objectives_from_response:
                    objectives_from_response = response.get('text', [])
                
                # Ensure it's a list
                if not isinstance(objectives_from_response, list):
                    objectives_from_response = [objectives_from_response] if objectives_from_response else []
                
                # Create objective entries for each objective in the response
                # All objectives from this chunk share the same source_id
                for objective_text in objectives_from_response:
                    if objective_text and isinstance(objective_text, str) and objective_text.strip():
                        objective_entry = {
                            'text': objective_text.strip(),
                            'source_id': chunk_data['source_id']
                        }
                        objective_list.append(objective_entry)
            
            except Exception as chunk_error:
                print(f"Error processing chunk {chunk_data.get('source_id', 'unknown')}: {str(chunk_error)}")
                # Continue with next chunk
                continue
    
        # Step 4: Return objective_list with source_ids
        # Post-processing step (Step 5 from image) should:
        # - Map each source_id with the chunk
        # - Fetch appropriate description and title from the database
        # - Transform to final format with source object containing:
        #   {source_id, chunk, description, title, url, organization}
        
        return {
            'status': 'ok',
            'status_code': 200,
            'objective_list': objective_list,
            'chunks_response': chunks_response,
            'message': f'Successfully generated {len(objective_list)} objectives from {len(filtered_chunks)} chunks'
        }
    
    except Exception as e:
        print(f"Unexpected error in generate_objective_utils: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'status_code': 500,
            'objective_list': [],
            'chunks_response': None,
            'message': f'Internal server error: {str(e)}'
        }


def post_process_objectives_with_source(objective_list, chunks_response):
    """
    Post-processing step (Step 5 from requirements):
    - Map each source_id with the chunk
    - Fetch appropriate description and title from the database
    - Transform to final format with source object
    
    Args:
        objective_list: List of objectives with source_id
        chunks_response: Response from Qdrant containing chunk details
    
    Returns:
        dict: {
            'status': 'ok' | 'error',
            'status_code': 200 | 400 | 500,
            'objective_list': [...],
            'message': 'Success message or error description'
        }
    """
    try:
        # Validate inputs
        if not objective_list:
            return {
                'status': 'ok',
                'status_code': 200,
                'objective_list': [],
                'message': 'No objectives to process'
            }
        
        if not isinstance(objective_list, list):
            return {
                'status': 'error',
                'status_code': 400,
                'objective_list': [],
                'message': 'Invalid objective_list: must be a list'
            }
        
        if not chunks_response:
            # Return objectives without source enrichment
            return {
                'status': 'ok',
                'status_code': 200,
                'objective_list': objective_list,
                'message': 'No chunks_response provided, returning objectives without source enrichment'
            }
    
        # Create a mapping of source_id to chunk details
        source_map = {}
        if chunks_response.get("results"):
            try:
                for result in chunks_response["results"]:
                    if not isinstance(result, dict):
                        print(f"Skipping invalid result in post_process: {result}")
                        continue
                    
                    # Extract source_id from metadata as per JSON structure
                    source_id = result.get('metadata', {}).get('source_id', '') or str(result.get('id', ''))
                    
                    if not source_id:
                        print(f"Skipping result without source_id: {result}")
                        continue
                    
                    # Get chunk text
                    chunk_text = ''
                    if "text" in result and result["text"]:
                        chunk_text = result["text"]
                    elif "translated_text" in result and result["translated_text"]:
                        chunk_text = result["translated_text"]
                    
                    # Get description (from summary field), title, url, and organization from the result
                    # These fields should be present in the Qdrant response
                    metadata = result.get('metadata', {})
                    # Note: description comes from 'summary' field in the response
                    description = result.get('summary', '') or metadata.get('summary', '')
                    title = result.get('title', '') or metadata.get('title', '')
                    url = result.get('url', '') or metadata.get('url', '')
                    organization_slug = result.get('organization', '') or metadata.get('organization', '') or metadata.get('company', '')
                    
                    # Fetch Company object to get name and slug
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
                                # Fallback if company not found
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
                    'objective_list': [],
                    'message': f'Error mapping source data: {str(map_error)}'
                }
    
        # Update objectives with source information
        processed_objectives = []
        for objective in objective_list:
            try:
                if not isinstance(objective, dict):
                    print(f"Skipping invalid objective: {objective}")
                    continue
                
                source_id = objective.get('source_id', '')
                source_info = source_map.get(source_id, {
                    'source_id': source_id,
                    'chunk': '',
                    'description': '',
                    'title': '',
                    'url': '',
                    'organization': {}
                })
                
                processed_objective = {
                    'text': objective.get('text', ''),
                    'source': source_info
                }
                processed_objectives.append(processed_objective)
            
            except Exception as obj_error:
                print(f"Error processing objective: {str(obj_error)}")
                # Continue with next objective
                continue
        
        return {
            'status': 'ok',
            'status_code': 200,
            'objective_list': processed_objectives,
            'message': f'Successfully processed {len(processed_objectives)} objectives with source information'
        }
    
    except Exception as e:
        print(f"Unexpected error in post_process_objectives_with_source: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'status_code': 500,
            'objective_list': [],
            'message': f'Internal server error: {str(e)}'
        }


def generate_action_list_utils(query, objective_text, company_bot):
    """
    Generate action list from query and objective with proper error handling.
    
    Args:
        query: User's problem statement/question
        objective_text: The objective for which to generate actions
        company_bot: CompanyBot instance with configuration
    
    Returns:
        dict: {
            'status': 'ok' | 'error',
            'status_code': 200 | 400 | 500,
            'action_list': [...],
            'chunks_response': {...},
            'message': 'Success message or error description'
        }
    """
    try:
        from chatbot.utils.chat_query_handler import query_database
        
        # Validate inputs
        if not query or not isinstance(query, str):
            return {
                'status': 'error',
                'status_code': 400,
                'action_list': [],
                'chunks_response': None,
                'message': 'Invalid query: must be a non-empty string'
            }
        
        if not objective_text or not isinstance(objective_text, str):
            return {
                'status': 'error',
                'status_code': 400,
                'action_list': [],
                'chunks_response': None,
                'message': 'Invalid objective_text: must be a non-empty string'
            }
        
        if not company_bot:
            return {
                'status': 'error',
                'status_code': 400,
                'action_list': [],
                'chunks_response': None,
                'message': 'Invalid company_bot: company_bot object is required'
            }
        
        # Validate company_bot attributes
        if not hasattr(company_bot, 'top_k') or not hasattr(company_bot, 'filter_score'):
            return {
                'status': 'error',
                'status_code': 400,
                'action_list': [],
                'chunks_response': None,
                'message': 'Invalid company_bot: missing required attributes (top_k, filter_score)'
            }
        
        # Step 1: Search Qdrant for relevant chunks based on objective_text
        try:
            chunks_response = query_database(
                query_prompt=objective_text,  # Search using objective_text
                priority_filter="p1", 
                limit=company_bot.top_k
            )
        except Exception as db_error:
            print(f"Database query error: {str(db_error)}")
            return {
                'status': 'error',
                'status_code': 500,
                'action_list': [],
                'chunks_response': None,
                'message': f'Database query failed: {str(db_error)}'
            }
        
        print("chunks_response from Qdrant for action_list:", chunks_response)
        
        # Validate chunks_response
        if not chunks_response:
            return {
                'status': 'ok',
                'status_code': 200,
                'action_list': [],
                'chunks_response': chunks_response,
                'message': 'No chunks found in database for the given objective'
            }
        
        # Step 2: Filter and order chunks based on relevance score
        filtered_chunks = []
        if chunks_response and chunks_response.get("results"):
            try:
                for result in chunks_response["results"]:
                    if not isinstance(result, dict):
                        print(f"Skipping invalid result: {result}")
                        continue
                    
                    relevance_score = result.get('field_scores', {}).get('text', 0)
                    print(f"relevance_score: {relevance_score}, filter_score: {company_bot.filter_score}")
                    
                    # Filter based on filter_score
                    if relevance_score >= company_bot.filter_score:
                        chunk_text = None
                        if "text" in result and result["text"] is not None and len(result["text"]) > 20:
                            chunk_text = result["text"]
                        elif "translated_text" in result and result["translated_text"] is not None and len(result["translated_text"]) > 20:
                            chunk_text = result["translated_text"]
                        
                        if chunk_text:
                            # Extract source_id from metadata
                            source_id = result.get('metadata', {}).get('source_id', '') or str(result.get('id', ''))
                            filtered_chunks.append({
                                'chunk_text': chunk_text,
                                'source_id': source_id,
                                'relevance_score': relevance_score,
                                'full_result': result
                            })
            except Exception as filter_error:
                print(f"Error filtering chunks: {str(filter_error)}")
                return {
                    'status': 'error',
                    'status_code': 500,
                    'action_list': [],
                    'chunks_response': chunks_response,
                    'message': f'Error processing chunks: {str(filter_error)}'
                }
        
        # Sort chunks by relevance_score
        try:
            filtered_chunks.sort(key=lambda x: x['relevance_score'], reverse=True)
        except Exception as sort_error:
            print(f"Error sorting chunks: {str(sort_error)}")
        
        print(f"\nFiltered and sorted chunks count for actions: {len(filtered_chunks)}")
        
        # Step 3: Generate action list
        action_list = []
        
        if not filtered_chunks:
            # If no chunks found, provide detailed message
            total_chunks = len(chunks_response.get("results", []))
            max_score = max([r.get('field_scores', {}).get('text', 0) for r in chunks_response.get("results", [])], default=0)
            
            warning_message = (
                f'No chunks met the filter criteria. '
                f'Found {total_chunks} chunks but all had relevance scores below the threshold. '
                f'Filter threshold: {company_bot.filter_score}, Highest chunk score: {max_score:.4f}. '
                f'Consider lowering the filter_score in company_bot settings.'
            )
            print(f"\n⚠️  WARNING: {warning_message}")
            
            return {
                'status': 'ok',
                'status_code': 200,
                'action_list': [],
                'chunks_response': chunks_response,
                'message': warning_message
            }
        
        # Process each chunk to generate actions
        for chunk_data in filtered_chunks:
            try:
                # Validate chunk_data
                if not chunk_data or not isinstance(chunk_data, dict):
                    print(f"Skipping invalid chunk_data: {chunk_data}")
                    continue
                
                if 'chunk_text' not in chunk_data or 'source_id' not in chunk_data:
                    print(f"Skipping chunk_data missing required fields: {chunk_data.keys()}")
                    continue
                
                # Prepare prompt with the chunk
                prompt = company_bot.context if hasattr(company_bot, 'context') else ''
                
                if not prompt:
                    print("Warning: company_bot.context is empty, using default prompt")
                    prompt = """You are an expert action planner. Generate a detailed action plan with specific, actionable steps."""
                
                # Create comprehensive prompt with query, objective, and chunk
                prompt_with_context = f"""{prompt}

Context Information:
- User Query: {query}
- Objective: {objective_text}
- Reference Material: {chunk_data['chunk_text']}

Based on the above information, generate a detailed action plan that includes:
1. A realistic duration (in days) to complete all actions
2. A list of 5-7 specific, actionable steps

The action steps should be:
- Clear and specific
- Actionable and measurable
- Relevant to the objective
- Sequential and logical
- Between 3-7 words each

Generate the action plan now."""
                
                messages = [{
                    'role': 'user',
                    'content': [{'text': prompt_with_context}]
                }]
                
                system_prompt = [{'text': prompt_with_context}]
                
                # Call LLM to generate action plan for this chunk
                try:
                    response = handle_bedrock_model(
                        system_prompt=system_prompt, 
                        messages=messages, 
                        model_name=company_bot.llm_model,
                        temperature=company_bot.bot_temperature, 
                        max_token=company_bot.max_token, 
                        company_bot=company_bot
                    )
                except Exception as llm_error:
                    print(f"LLM error for chunk {chunk_data['source_id']}: {str(llm_error)}")
                    continue
                
                # Validate LLM response
                if not response or not isinstance(response, dict):
                    print(f"Invalid LLM response for chunk {chunk_data['source_id']}: {response}")
                    continue
                
                # Debug: Print the full response to see what we're getting
                print(f"\n🔍 DEBUG - LLM Response for chunk {chunk_data['source_id']}:")
                print(f"Response keys: {response.keys()}")
                print(f"Full response: {response}")
                
                # Extract action plan from response
                # The LLM can return in multiple formats:
                # Format 1: {'duration': '3', 'actionSteps': ['step1', 'step2', ...]}
                # Format 2: {'action_plan': [{'duration': '3', 'actionSteps': [...]}, ...]}
                # Format 3: {'action_plan': {'duration': '3', 'actionSteps': [...]}}
                
                print(f"Extracted duration: {response.get('duration', '3')}")
                print(f"Extracted action_steps: {response.get('actionSteps', [])}")
                
                # Check if action_plan field exists (Format 2 or 3)
                if 'action_plan' in response:
                    action_plan = response.get('action_plan')
                    print(f"Found action_plan field: {type(action_plan)}")
                    
                    # If action_plan is a list of action plan objects
                    if isinstance(action_plan, list):
                        print(f"action_plan is a list with {len(action_plan)} items")
                        # Process each action plan in the list
                        for idx, plan_item in enumerate(action_plan):
                            if isinstance(plan_item, dict):
                                duration = plan_item.get('duration', '3')
                                action_steps = plan_item.get('actionSteps', []) or plan_item.get('action_steps', []) or plan_item.get('steps', [])
                                
                                # Ensure action_steps is a list of strings
                                if isinstance(action_steps, list):
                                    action_steps = [step.strip() for step in action_steps if step and isinstance(step, str) and step.strip()]
                                    
                                    if action_steps:
                                        action_entry = {
                                            'duration': str(duration),
                                            'actionSteps': action_steps,
                                            'source_id': chunk_data['source_id']
                                        }
                                        action_list.append(action_entry)
                                        print(f"✅ Added action plan {idx+1} for chunk {chunk_data['source_id']}: {len(action_steps)} steps")
                    
                    # If action_plan is a single dict object
                    elif isinstance(action_plan, dict):
                        duration = action_plan.get('duration', '3')
                        action_steps = action_plan.get('actionSteps', []) or action_plan.get('action_steps', []) or action_plan.get('steps', [])
                        
                        if isinstance(action_steps, list):
                            action_steps = [step.strip() for step in action_steps if step and isinstance(step, str) and step.strip()]
                            
                            if action_steps:
                                action_entry = {
                                    'duration': str(duration),
                                    'actionSteps': action_steps,
                                    'source_id': chunk_data['source_id']
                                }
                                action_list.append(action_entry)
                                print(f"✅ Added action plan for chunk {chunk_data['source_id']}: {len(action_steps)} steps")
                
                # Format 1: Direct fields in response
                elif 'actionSteps' in response or 'action_steps' in response or 'steps' in response:
                    duration = response.get('duration', '3')
                    action_steps = response.get('actionSteps', []) or response.get('action_steps', []) or response.get('steps', [])
                    
                    if isinstance(action_steps, list):
                        action_steps = [step.strip() for step in action_steps if step and isinstance(step, str) and step.strip()]
                        
                        if action_steps:
                            action_entry = {
                                'duration': str(duration),
                                'actionSteps': action_steps,
                                'source_id': chunk_data['source_id']
                            }
                            action_list.append(action_entry)
                            print(f"✅ Added action plan for chunk {chunk_data['source_id']}: {len(action_steps)} steps")
                
                else:
                    print(f"⚠️  No valid action plan format found for chunk {chunk_data['source_id']}")
                    print(f"Available keys: {response.keys()}")
            
            except Exception as chunk_error:
                print(f"Error processing chunk {chunk_data.get('source_id', 'unknown')}: {str(chunk_error)}")
                continue
        
        # Step 4: Return action_list with source_ids
        return {
            'status': 'ok',
            'status_code': 200,
            'action_list': action_list,
            'chunks_response': chunks_response,
            'message': f'Successfully generated {len(action_list)} action plans from {len(filtered_chunks)} chunks'
        }
    
    except Exception as e:
        print(f"Unexpected error in generate_action_list_utils: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'status': 'error',
            'status_code': 500,
            'action_list': [],
            'chunks_response': None,
            'message': f'Internal server error: {str(e)}'
        }


def post_process_actions_with_source(action_list, chunks_response):
    """
    Post-processing step for action list:
    - Map each source_id with the chunk
    - Fetch appropriate description, title, url, and organization from the database
    - Transform to final format with source object
    
    Args:
        action_list: List of actions with source_id
        chunks_response: Response from Qdrant containing chunk details
    
    Returns:
        dict: {
            'status': 'ok' | 'error',
            'status_code': 200 | 400 | 500,
            'action_list': [...],
            'message': 'Success message or error description'
        }
    """
    try:
        # Validate inputs
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
        
        if not chunks_response:
            # Return actions without source enrichment
            return {
                'status': 'ok',
                'status_code': 200,
                'action_list': action_list,
                'message': 'No chunks_response provided, returning actions without source enrichment'
            }
        
        # Create a mapping of source_id to chunk details
        source_map = {}
        if chunks_response.get("results"):
            try:
                for result in chunks_response["results"]:
                    if not isinstance(result, dict):
                        print(f"Skipping invalid result in post_process: {result}")
                        continue
                    
                    # Extract source_id from metadata
                    source_id = result.get('metadata', {}).get('source_id', '') or str(result.get('id', ''))
                    
                    if not source_id:
                        print(f"Skipping result without source_id: {result}")
                        continue
                    
                    # Get chunk text
                    chunk_text = ''
                    if "text" in result and result["text"]:
                        chunk_text = result["text"]
                    elif "translated_text" in result and result["translated_text"]:
                        chunk_text = result["translated_text"]
                    
                    # Get description (from summary field), title, url, and organization
                    metadata = result.get('metadata', {})
                    description = result.get('summary', '') or metadata.get('summary', '')
                    title = result.get('title', '') or metadata.get('title', '')
                    url = result.get('url', '') or metadata.get('url', '')
                    organization_slug = result.get('organization', '') or metadata.get('organization', '') or metadata.get('company', '')
                    
                    # Fetch Company object to get name and slug
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
                                # Fallback if company not found
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
        
        # Update actions with source information
        processed_actions = []
        for action in action_list:
            try:
                if not isinstance(action, dict):
                    print(f"Skipping invalid action: {action}")
                    continue
                
                source_id = action.get('source_id', '')
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


def generate_title_utils(input_data, company_bot):
    prompt = company_bot.context
    messages = [{
        'role': 'user',
        'content': [{'text': f"{input_data}"}]
    }]

    prompt = [{'text': prompt}]

    response = handle_bedrock_model(
        system_prompt=prompt, messages=messages, model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token,
        company_bot=company_bot
    )
    response = response.get('title')
    return response


def validate_objective_utils(user_input, company_bot):
    try:
        prompt = company_bot.end_context
        messages = [{
            'role': 'user',
            'content': [{'text': f"{user_input}"}]
        }]

        prompt = [{'text': prompt}]

        response = handle_bedrock_model(
            system_prompt=prompt, messages=messages, model_name = company_bot.llm_model,
            temperature = company_bot.bot_temperature, max_token = company_bot.max_token,
            company_bot=company_bot
        )

        response = response.get('within_scope')
        return response
    except Exception as e:
        print("Got error : ", e)
        return False


def validate_actions_utils(user_input, user_objective, problem_statement, company_bot):
    try:
        print('user_input: ', user_input)
        prompt = company_bot.end_context

        context_data = {
            "actionList": user_input,
            "objective": user_objective,
            "problem_statement": problem_statement
        }
        template = Template(company_bot.tag_context)
        tag_context = template.render(context_data)


        messages = [{
            'role': 'user',
            'content': [{'text': f"{tag_context}"}]
        }]

        prompt = [{'text': prompt}]

        response = handle_bedrock_model(
            system_prompt=prompt, messages=messages, model_name = company_bot.llm_model,
            temperature = company_bot.bot_temperature, max_token = company_bot.max_token,
            company_bot=company_bot
        )

        response = response.get('within_scope')
        return response
    except Exception as e:
        print("Got error : ", e)
        return False


def validate_title_utils(user_input, user_objective, problem_statement, user_actions, company_bot):
    try:
        print('user_input: ', user_input)
        prompt = company_bot.end_context

        context_data = {
            "title": user_input,
            "actionList": user_actions,
            "objective": user_objective,
            "problem_statement": problem_statement
        }
        template = Template(company_bot.tag_context)
        tag_context = template.render(context_data)

        messages = [{
            'role': 'user',
            'content': [{'text': f"{tag_context}"}]
        }]

        prompt = [{'text': prompt}]

        response = handle_bedrock_model(
            system_prompt=prompt, messages=messages, model_name = company_bot.llm_model,
            temperature = company_bot.bot_temperature, max_token = company_bot.max_token,
            company_bot=company_bot
        )

        response = response.get('within_scope')
        return response
    except Exception as e:
        print("Got error : ", e)
        return False

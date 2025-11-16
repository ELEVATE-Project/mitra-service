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
    from chatbot.utils.chat_query_handler import query_database
    
    # Step 1: Search Qdrant for relevant chunks based on user question
    chunks_response = query_database(
        query_prompt=user_problem_statement, 
        priority_filter="p1", 
        limit=company_bot.top_k
    )
    
    print("chunks_response from Qdrant:", chunks_response)
    
    # Step 2: Filter and order chunks based on relevance score
    filtered_chunks = []
    if chunks_response and chunks_response.get("results"):
        for result in chunks_response["results"]:
            relevance_score = result.get('field_scores',{}).get('text',0)
            print(f"relevance_score: {relevance_score}, filter_score: {company_bot.filter_score}")
            
            # Filter based on filter_score - only include chunks with score >= filter_score
            if relevance_score >= company_bot.filter_score:
                chunk_text = None
                if "text" in result and result["text"] is not None and len(result["text"]) > 20:
                    chunk_text = result["text"]
                elif "translated_text" in result and result["translated_text"] is not None and len(result["translated_text"]) > 20:
                    chunk_text = result["translated_text"]
                
                if chunk_text:
                    filtered_chunks.append({
                        'chunk_text': chunk_text,
                        'source_id': str(result.get('id', '')),
                        'relevance_score': relevance_score,
                        'full_result': result  # Store full result for later use
                    })
    
    # Sort chunks by relevance_score in descending order
    filtered_chunks.sort(key=lambda x: x['relevance_score'], reverse=True)
    
    print(f"\nFiltered and sorted chunks count: {len(filtered_chunks)}")
    
    # Step 3: Generate one objective per chunk
    objective_list = []
    
    if not filtered_chunks:
        # If no chunks found, return empty list with null chunks
        return [], chunks_response
    
    for chunk_data in filtered_chunks:
        # Prepare prompt with the chunk
        prompt = company_bot.context
        
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
        response = handle_bedrock_model(
            system_prompt=system_prompt, 
            messages=messages, 
            model_name=company_bot.llm_model,
            temperature=company_bot.bot_temperature, 
            max_token=company_bot.max_token, 
            company_bot=company_bot
        )
        
        # Extract objective text from response
        # The LLM should return the objective in a specific field based on the prompt
        objective_text = response.get('objective', '') or response.get('text', '') or str(response)
        
        # Create objective entry with source_id
        # Note: source object fields (chunk, description, title) will be populated
        # in post-processing by mapping source_id to fetch from database
        objective_entry = {
            'text': objective_text,
            'source_id': chunk_data['source_id']
        }
        
        objective_list.append(objective_entry)
    
    # Step 4: Return objective_list with source_ids
    # Post-processing step (Step 5 from image) should:
    # - Map each source_id with the chunk
    # - Fetch appropriate description and title from the database
    # - Transform to final format with source object containing:
    #   {source_id, chunk, description, title}
    
    return objective_list, chunks_response


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
        List of objectives with complete source information
    """
    if not objective_list or not chunks_response:
        return objective_list
    
    # Create a mapping of source_id to chunk details
    source_map = {}
    if chunks_response.get("text"):
        for result in chunks_response["text"]:
            source_id = str(result.get('id', ''))
            
            # Get chunk text
            chunk_text = ''
            if "text" in result and result["text"]:
                chunk_text = result["text"]
            elif "translated_text" in result and result["translated_text"]:
                chunk_text = result["translated_text"]
            
            # Get description and title from the result
            # These fields should be present in the Qdrant response
            description = result.get('description', '') or result.get('metadata', {}).get('description', '')
            title = result.get('title', '') or result.get('metadata', {}).get('title', '')
            
            source_map[source_id] = {
                'source_id': source_id,
                'chunk': chunk_text,
                'description': description,
                'title': title
            }
    
    # Update objectives with source information
    processed_objectives = []
    for objective in objective_list:
        source_id = objective.get('source_id', '')
        source_info = source_map.get(source_id, {
            'source_id': source_id,
            'chunk': '',
            'description': '',
            'title': ''
        })
        
        processed_objective = {
            'text': objective.get('text', ''),
            'source_id': source_id,
            'source': source_info
        }
        processed_objectives.append(processed_objective)
    
    return processed_objectives


def generate_action_list_utils(input_data, company_bot):
    prompt = company_bot.context
    messages = [{
        'role': 'user',
        'content': [{'text': f"{input_data}"}]
    }]
    prompt = [{'text': prompt}]

    response = handle_bedrock_model(
        system_prompt=prompt, messages=messages, model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token, company_bot=company_bot
    )

    response = response.get('action_plan')
    return response


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

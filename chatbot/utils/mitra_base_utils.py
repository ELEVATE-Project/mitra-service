from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import CompanyBot
from chatbot.utils.chat_query_handler import ask
from jinja2 import Template


def get_mitra_paraphrase_utils(paraphrase_problem, should_paraphrase_text):
    company_bot = CompanyBot.objects.get(route='/paraphrase')
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
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token,
    )
    print("validation_response: ", validation_response)
    is_validated = validation_response.get('is_validated')
    if is_validated.lower() == 'no' or not should_paraphrase_text:
        return validation_response
    print('paraphrase_prompt: ', paraphrase_prompt)
    paraphrase_response = handle_bedrock_model(
        system_prompt=paraphrase_prompt, messages=messages, model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token,
    )
    print("paraphrase_response: ", paraphrase_response)
    paraphrase_response = paraphrase_response.get('paraphrased_challenge')
    return paraphrase_response


def generate_objective_utils(user_problem_statement):
    company_bot = CompanyBot.objects.get(route='/objective')
    prompt = company_bot.context
    messages = [{
        'role': 'user',
        'content': [{'text': f"""
                Based on the above data (if applicable) please answer to following question/greeting: 
                {user_problem_statement}
        
                REMEMBER STRICTLY DO NOT PROVIDE ANY INFORMATION WHICH IS OUTSIDE OF CONTEXT AVAILABLE TO YOU.
            """
        }]
    }]
    prompt = [{'text': prompt}]

    response, chunks, chunks_response = ask(
        messages=messages, user_question=user_problem_statement, temperature=company_bot.bot_temperature,
        priority_filter="p1", top_k=company_bot.top_k, prompt=prompt, filter_score=company_bot.filter_score
    )

    response = response.get('objective_list')
    return response, chunks_response


def generate_action_list_utils(input_data):
    company_bot = CompanyBot.objects.get(route='/action_list')
    prompt = company_bot.context
    messages = [{
        'role': 'user',
        'content': [{'text': f"{input_data}"}]
    }]
    prompt = [{'text': prompt}]

    response = handle_bedrock_model(
        system_prompt=prompt, messages=messages, model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token,
    )

    response = response.get('action_plan')
    return response


def generate_title_utils(input_data):
    company_bot = CompanyBot.objects.get(route='/title')
    prompt = company_bot.context
    messages = [{
        'role': 'user',
        'content': [{'text': f"{input_data}"}]
    }]

    prompt = [{'text': prompt}]

    response = handle_bedrock_model(
        system_prompt=prompt, messages=messages, model_name = company_bot.llm_model,
        temperature = company_bot.bot_temperature, max_token = company_bot.max_token,
    )
    response = response.get('title')
    return response


def validate_objective_utils(user_input):
    try:
        company_bot = CompanyBot.objects.get(route='/objective')
        prompt = company_bot.end_context
        messages = [{
            'role': 'user',
            'content': [{'text': f"{user_input}"}]
        }]

        prompt = [{'text': prompt}]

        response = handle_bedrock_model(
            system_prompt=prompt, messages=messages, model_name = company_bot.llm_model,
            temperature = company_bot.bot_temperature, max_token = company_bot.max_token,
        )

        response = response.get('within_scope')
        return response
    except Exception as e:
        print("Got error : ", e)
        return False


def validate_actions_utils(user_input, user_objective, problem_statement):
    try:
        print('user_input: ', user_input)
        company_bot = CompanyBot.objects.get(route='/action_list')
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
        )

        response = response.get('within_scope')
        return response
    except Exception as e:
        print("Got error : ", e)
        return False


def validate_title_utils(user_input, user_objective, problem_statement, user_actions):
    try:
        print('user_input: ', user_input)
        company_bot = CompanyBot.objects.get(route='/title')
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
        )

        response = response.get('within_scope')
        return response
    except Exception as e:
        print("Got error : ", e)
        return False


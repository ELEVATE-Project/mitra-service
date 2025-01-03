import json

from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.models import CompanyBot
from chatbot.utils.chat_query_handler import ask


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
        system_prompt=validation_prompt, messages=messages, max_token=2048,
        temperature=0.0
    )
    print("validation_response: ", validation_response)
    validation_response = validation_response.get('is_validated')
    if validation_response.lower() == 'no':
        return validation_response
    if not should_paraphrase_text:
        return "NO"
    print('paraphrase_prompt: ', paraphrase_prompt)
    paraphrase_response = handle_bedrock_model(
        system_prompt=paraphrase_prompt, messages=messages, max_token=2048,
        temperature=0.0
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
        priority_filter="p1", top_k=company_bot.top_k, prompt=prompt
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
        system_prompt=prompt, messages=messages, max_token=2048,
        temperature=0.0
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
        system_prompt=prompt, messages=messages, max_token=2048,
        temperature=0.0
    )
    response = response.get('title')
    return response

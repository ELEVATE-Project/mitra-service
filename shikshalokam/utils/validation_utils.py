from chatbot.llm_models.llm_script import handle_bedrock_model
import json_repair
import json
from jinja2 import Template


def validate_objective_utils(user_input, user_problem_statement, company_bot):
    try:
        prompt = company_bot.context
        context_data = {
            "objectives": user_input,
            "problem_statement": user_problem_statement
        }
        template = Template(company_bot.tag_context)
        tag_context = template.render(context_data)

        messages = [{
            'role': 'user',
            'content': [{'text': f"{tag_context}"}]
        }]

        prompt = [{'text': prompt}]

        tool_context = company_bot.tool_context
        tool_context = json_repair.repair_json(tool_context, return_objects=True)
        response = handle_bedrock_model(
            system_prompt=prompt, messages=messages, model_name=company_bot.llm_model,
            temperature=company_bot.bot_temperature, max_token=company_bot.max_token, company_bot=company_bot,
            tools=tool_context, top_p=company_bot.filter_score,
        )
        parsed_response = parse_llm_response(response)

        response = parsed_response.get('within_scope')
        return response
    except Exception as e:
        print("Got error : ", e)
        return False


def validate_actions_utils(user_input, user_objective, problem_statement, company_bot):
    try:
        print('user_input: ', user_input)
        prompt = company_bot.context

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

        tool_context = company_bot.tool_context
        tool_context = json_repair.repair_json(tool_context, return_objects=True)
        response = handle_bedrock_model(
            system_prompt=prompt, messages=messages, model_name=company_bot.llm_model,
            temperature=company_bot.bot_temperature, max_token=company_bot.max_token, company_bot=company_bot,
            tools=tool_context, top_p=company_bot.filter_score,
        )
        parsed_response = parse_llm_response(response)

        response = parsed_response.get('within_scope')
        return response
    except Exception as e:
        print("Got error : ", e)
        return False


def validate_title_utils(user_input, user_objective, problem_statement, user_actions, company_bot):
    try:
        print('user_input: ', user_input)
        prompt = company_bot.context

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

        import json_repair
        tool_context = company_bot.tool_context
        tool_context = json_repair.repair_json(tool_context, return_objects=True)
        response = handle_bedrock_model(
            system_prompt=prompt, messages=messages, model_name=company_bot.llm_model,
            temperature=company_bot.bot_temperature, max_token=company_bot.max_token, company_bot=company_bot,
            tools=tool_context, top_p=company_bot.filter_score,
        )

        parsed_response = parse_llm_response(response)
        response = parsed_response.get('within_scope')
        return response
    except Exception as e:
        print("Got error : ", e)
        return False


def parse_llm_response(response):
    if not response or not isinstance(response, dict):
        return {}

    extracted_data = response.pop("parameters", response.pop("input", None))
    if extracted_data and isinstance(extracted_data, dict):
        return extracted_data

    if isinstance(response, str):
        try:
            return json_repair.repair_json(response, return_objects=True)
        except:
            try:
                return json.loads(response)
            except:
                return {}

    return response

import asyncio
import functools
import json_repair
from chatbot.llm_models.llm_script import handle_bedrock_model, handle_openai_model
from chatbot.models import LLMProvider, SessionFlowName
import logging


logger = logging.getLogger('django')


async def generate_story_llm(formatted_content_prompt, formatted_story_prompt, messages, tool_content, tool_story,
                             company_bot, flow):
    async def func1():
        if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
            return await asyncio.to_thread(
                functools.partial(
                    handle_bedrock_model,
                    system_prompt=formatted_content_prompt,
                    messages=messages,
                    tools=tool_content,
                    temperature=company_bot.bot_temperature,
                    max_token=company_bot.max_token,
                    top_p=company_bot.filter_score,
                    model_name=company_bot.llm_model,
                    company_bot=company_bot
                )
            )
        elif company_bot.provider == LLMProvider.OPENAI:
            return await asyncio.to_thread(
                functools.partial(
                    handle_openai_model,
                    system_prompt=formatted_content_prompt,
                    messages=messages,
                    temperature=company_bot.bot_temperature,
                    max_token=company_bot.max_token,
                    top_p=company_bot.filter_score,
                    model_name=company_bot.llm_model
                )
            )

    async def func2():
        if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
            return await asyncio.to_thread(
                functools.partial(
                    handle_bedrock_model,
                    system_prompt=formatted_story_prompt,
                    messages=messages,
                    tools=tool_story,
                    temperature=company_bot.bot_temperature,
                    max_token=company_bot.max_token,
                    top_p=company_bot.filter_score,
                    model_name=company_bot.llm_model,
                    company_bot=company_bot
                )
            )
        elif company_bot.provider == LLMProvider.OPENAI:
            return await asyncio.to_thread(
                functools.partial(
                    handle_openai_model,
                    system_prompt=formatted_story_prompt,
                    messages=messages,
                    temperature=company_bot.bot_temperature,
                    max_token=company_bot.max_token,
                    top_p=company_bot.filter_score,
                    model_name=company_bot.llm_model
                )
            )

    if flow in [SessionFlowName.LoginMiStory, SessionFlowName.GuestMiStory, SessionFlowName.Reflection,
        SessionFlowName.megaPTM
    ]:
        response_json_content, response_json_story = await asyncio.gather(func1(), func2())
    else:
        response_json_content = await func1()
        response_json_story = None
    logger.info(f"response_json_content: %s", response_json_content)
    logger.info(f"response_json_story: %s", response_json_story)

    if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
        for response in [response_json_content, response_json_story]:
            if response and isinstance(response, dict):
                extracted_data = response.pop("parameters", response.pop("input", None))
                if extracted_data and isinstance(extracted_data, dict):
                    response.clear()
                    response.update(extracted_data)

    elif company_bot.provider == LLMProvider.OPENAI:
        pass

    logger.info(f"Final response_json_content: %s", response_json_content)
    logger.info(f"Final response_json_story: %s", response_json_story)


    return response_json_content, response_json_story


async def validate_story_llm(formatted_content_prompt, formatted_story_prompt, messages, tool_content, tool_story,
                             company_bot, flow):
    async def func1():
        if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
            return await asyncio.to_thread(
                functools.partial(
                    handle_bedrock_model,
                    system_prompt=formatted_content_prompt,
                    messages=messages,
                    tools=tool_content,
                    temperature=company_bot.bot_temperature,
                    max_token=company_bot.max_token,
                    top_p=company_bot.filter_score,
                    model_name=company_bot.llm_model,
                    company_bot=company_bot
                )
            )
        elif company_bot.provider == LLMProvider.OPENAI:
            return await asyncio.to_thread(
                functools.partial(
                    handle_openai_model,
                    system_prompt=formatted_content_prompt,
                    messages=messages,
                    temperature=company_bot.bot_temperature,
                    max_token=company_bot.max_token,
                    top_p=company_bot.filter_score,
                    model_name=company_bot.llm_model
                )
            )

    async def func2():
        if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
            return await asyncio.to_thread(
                functools.partial(
                    handle_bedrock_model,
                    system_prompt=formatted_story_prompt,
                    messages=messages,
                    tools=tool_story,
                    temperature=company_bot.bot_temperature,
                    max_token=company_bot.max_token,
                    top_p=company_bot.filter_score,
                    model_name=company_bot.llm_model,
                    company_bot=company_bot
                )
            )
        elif company_bot.provider == LLMProvider.OPENAI:
            return await asyncio.to_thread(
                functools.partial(
                    handle_openai_model,
                    system_prompt=formatted_story_prompt,
                    messages=messages,
                    temperature=company_bot.bot_temperature,
                    max_token=company_bot.max_token,
                    top_p=company_bot.filter_score,
                    model_name=company_bot.llm_model
                )
            )

    if flow in [SessionFlowName.LoginMiStory, SessionFlowName.GuestMiStory, SessionFlowName.Reflection,
                SessionFlowName.megaPTM
    ]:
        response_json_content, response_json_story = await asyncio.gather(func1(), func2())
    else:
        response_json_content = await func1()
        response_json_story = None
    logger.info(f"Validation: response_json_content: %s", response_json_content)
    logger.info(f"Validation: response_json_story: %s", response_json_story)
    if company_bot.provider == LLMProvider.BEDROCK_CONVERSE:
        for response in [response_json_content, response_json_story]:
            if response and isinstance(response, dict):
                extracted_data = response.pop("parameters", response.pop("input", None))
                if extracted_data and isinstance(extracted_data, dict):
                    response.clear()
                    response.update(extracted_data)

    elif company_bot.provider == LLMProvider.OPENAI:
        pass
    reason_content=""
    reason_content = response_json_content.get('reason')
    response_json_content = response_json_content.get('final_answer')
    if response_json_content and isinstance(response_json_content, str):
        response_json_content = json_repair.repair_json(response_json_content, return_objects=True)

    reason_story=""
    if response_json_story:
        reason_story = response_json_story.get('reason')
        response_json_story = response_json_story.get('final_answer')
    if response_json_story and isinstance(response_json_story, str):
        response_json_story = json_repair.repair_json(response_json_story, return_objects=True)

    logger.info(f"Final Validation: response_json_content: %s", response_json_content)
    logger.info(f"Final Validation: response_json_story: %s", response_json_story)

    if (isinstance(response_json_story, dict) and response_json_story.get("type") and
            "value" in response_json_story):
        value = response_json_story.get("value")
        if isinstance(value, str) and value.strip():
            value = json_repair.repair_json(value, return_objects=True)
        response_json_story = value

    if (isinstance(response_json_content, dict) and response_json_content.get("type") and
            "value" in response_json_content):
        value = response_json_content.get("value")
        if isinstance(value, str) and value.strip():
            value = json_repair.repair_json(value, return_objects=True)
        response_json_content = value

    combined_result = {**(response_json_content or {}), **(response_json_story or {})}

    combined_reason = {
        "reason_content": reason_content,
        "reason_story": reason_story
    }

    return combined_result, combined_reason

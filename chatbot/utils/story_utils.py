import json
import traceback
import random
import string
from chatbot.llm_models.story_tools import get_end_story_tools, get_story_content_tools
from chatbot.models import (Profile, CompanyChat, CompanyBot, StoryLanguageChoices,
                            StoryStatusChoices, ChatSession, ChatStatus, Voice, VoiceType)
from chatbot.models.geo_models import ProfileAddress
from chatbot.models.story_models import Story
from chatbot.utils.shikshalokam_story_utils import save_shikshalokam_story
from chatbot.utils.story_llama_utils import create_project, translate_field
from chatbot.llm_models.llm_script import handle_bedrock_model
from jinja2 import Template


def create_story_object(profile_id, session, language='en'):
    try:
        profile = Profile.objects.get(id=profile_id)
        company_chats = CompanyChat.objects.filter(session=session).order_by('created_at')
        ai_user = Profile.objects.get(id=1)
        company_bot = CompanyBot.objects.get(route='/story')
        context = company_bot.context
        address = ProfileAddress.objects.filter(profile=profile)
        context_data = {
            "profile": profile,
            "address": address if address else [{}]
        }
        template = Template(company_bot.tag_context)

        tag_context = template.render(context_data)

        end_context = company_bot.end_context

        chat_session = ChatSession.objects.get(session=session)

        project_data = ''

        content_prompt = f"""
            {context}
            {tag_context}
            {project_data}
        """
        story_prompt = f"""
            {end_context}
            {tag_context}
            {project_data}
        """
        print('-------------------------------')
        print(story_prompt)

        messages=[]
        formatted_content_prompt = [
            {
                'text': content_prompt
            },
        ]
        formatted_story_prompt = [
            {
                'text': story_prompt
            },
        ]
        if company_chats and company_chats[0].receiver != ai_user:
            company_chats.pop(0)
        for chat in company_chats:
            user_message = chat.message
            if chat.receiver == ai_user:
                if chat.translated_message is not None and chat.translated_message != '':
                    user_message = chat.translated_message
                messages.append({
                    'role': 'user',
                    'content': [{'text': user_message}]
                })
            else:
                messages.append({
                    'role': 'assistant',
                    'content': [{'text': user_message}]
                })

        # print("Message: ", messages)
        tool_story = get_end_story_tools()
        tool_content = get_story_content_tools()
        print("\n----------")
        response_json_content = handle_bedrock_model(
            system_prompt = formatted_content_prompt, messages = messages, tools=tool_content,
            temperature=company_bot.bot_temperature, max_token=company_bot.max_token, top_p=company_bot.filter_score,
            model_name=company_bot.llm_model
        )
        if response_json_content:
            if response_json_content.get('parameters'):
                response_json_content = response_json_content.get('parameters')
            elif response_json_content.get('input'):
                response_json_content = response_json_content.get('input')
        print("\n\nresponse_json_content: ", response_json_content)
        response_json_story = handle_bedrock_model(
            system_prompt = formatted_story_prompt, messages = messages, tools=tool_story,
            temperature=company_bot.bot_temperature, max_token=company_bot.max_token, top_p=company_bot.filter_score,
            model_name=company_bot.llm_model
        )
        if response_json_content:
            if response_json_story.get('parameters'):
                response_json_story = response_json_story.get('parameters')
            elif response_json_story.get('input'):
                response_json_story = response_json_story.get('input')
        print("\n\nresponse_json_story: ", response_json_story)

        print("\n----------")

        title = response_json_story.get('title', '')
        print('title: ', title)
        tweet = response_json_story.get('tweet', '')
        print('tweet: ', tweet)
        objective = response_json_story.get('objective', '')
        print('objective: ', objective)
        action_steps = response_json_story.get('action_steps', '')
        print('action_steps: ', action_steps)
        impact = response_json_story.get('impact', '')
        print('impact: ', impact)
        micro_improvement = response_json_story.get('micro_improvement', '')
        print('micro_improvement: ', micro_improvement)
        problem_statement = response_json_story.get('problem_statement', '')
        print('problem_statement: ', problem_statement)

        duration = response_json_story.get('duration', '')
        other_params = {
            'duration': duration
        }

        content = response_json_content.get('content', '')
        print('content: ', content)
        blurb = response_json_content.get('blurb', '')
        print('blurb: ', blurb)

        voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()

        if language != 'en':
            title = translate_field(
                voice_provider=voice_provider, message_body=title, target_language=language
            )

            tweet = translate_field(
                voice_provider=voice_provider, message_body=tweet, target_language=language
            )
            objective = translate_field(
                voice_provider=voice_provider, message_body=objective, target_language=language
            )
            action_steps = translate_field(
                voice_provider=voice_provider, message_body=action_steps, target_language=language
            )
            impact = translate_field(
                voice_provider=voice_provider, message_body=impact, target_language=language
            )
            micro_improvement = translate_field(
                voice_provider=voice_provider, message_body=micro_improvement, target_language=language
            )
            problem_statement = translate_field(
                voice_provider=voice_provider, message_body=problem_statement, target_language=language
            )
            content = translate_field(
                voice_provider=voice_provider, message_body=content, target_language=language
            )
            blurb = translate_field(
                voice_provider=voice_provider, message_body=blurb, target_language=language
            )

        if profile:
            address = ProfileAddress.objects.filter(profile=profile).first()
            if address:
                location_parts = filter(None, [address.block, address.district, address.state])
                location = ", ".join(location_parts)
            else:
                location = ""
        else:
            location = ""

        story = Story(
            title=title,
            content=content,
            tweet=tweet,
            author=profile,
            session=session,
            objective=objective,
            action_steps=action_steps,
            impact=impact,
            micro_improvement=micro_improvement,
            language=StoryLanguageChoices.ENGLISH,
            stage=StoryStatusChoices.COMPLETED,
            other_params=other_params,
            location=location,
            blurb=blurb
        )

        story.save()
        formatted_content = get_formatted_story(story)
        story.formatted_content = formatted_content
        story.save(update_fields=['formatted_content'])

        create_project(
            response_json=response_json_story,title=title, objective=objective, story=story,
            profile=profile, problem_statement=problem_statement, language=language, voice_provider=voice_provider
        )

        chat_session.session_status = ChatStatus.COMPLETED
        chat_session.save(update_fields=['session_status'])
        save_shikshalokam_story(
            story=story, profile=profile
        )

        return story.id, story.content

    except Exception as e:
        traceback.print_exc()
        return "", ""


def format_response_json(response):
    response_json = response.replace('\n', '').replace('\t', '').replace(
        '\r', '').replace('\\n', '').replace('\\t', '').replace('\\r', '')
    if '{' in response_json:
        response_json = response_json[response_json.index('{'):]
    last_char = response_json[-1]
    if last_char != '}':
        response_json += '}'
    print("\nBEFORE LOADS: ", response_json)
    if isinstance(response_json, str):
        response_json = json.loads(response_json)
    print("AFTER LOADS: ", response_json)
    print("TYPE response_json: ", type(response_json))

    return response_json


def get_formatted_story(story):
    res = [
        {
            'id': generate_random_string(10),
            'type': 'paragraph',
            'data':
                {
                    'text': story.title,
                }
        },
        {
            'id': generate_random_string(10),
            'type': 'paragraph',
            'data':
                {
                    'text': story.content,
                }
        }
    ]
    return json.dumps(res)


def generate_random_string(length):
    characters = string.ascii_letters + string.digits
    rs = ''.join(random.choice(characters) for _ in range(length))
    return rs

import json
import traceback
import random
import string
from chatbot.llm_models.llm_script import handle_openai_model, handle_llama_model
from chatbot.models import (Profile, CompanyChat, CompanyBot, StoryLanguageChoices,
                                                StoryStatusChoices, ChatSession, ChatStatus, LLMModel)
from chatbot.models.story_models import Story
from chatbot.utils.story_llama_utils import (get_company_end_context, create_project,
                                                                 get_company_context)

from chatbot.llm_models.llm_script import handle_bedrock_model

DEFAULT_PROMPT = """
            Based on the detailed interview you've conducted with a field staff member, 
            craft a SIMPLE STORY OF MORE THAN 600 TOKENS AT A HIGH SCHOOL ENGLISH LEVEL IN HUMANS OF NEW YORK STYLE that captures the
            journey of the highlighted beneficiary. The story should flow naturally. 
            THINGS TO INCORPORATE:
            1. USE PRESENT TENSE
            2. DO NOT USE CLICHE BEGINNINGS
            3. DO NOT ADD FLUFF DO NOT USE FLOWERY LANGUAGE.
            4. DO NOT ADD ANY INFORMATION FROM YOUR END IF NOT PROVIDED.
"""


def create_story_object(profile_id, session, model=None):
    try:
        profile = Profile.objects.get(id=profile_id)
        company = profile.company
        company_slug = company.slug
        company_context = get_company_context(profile, company)
        company_chats = CompanyChat.objects.filter(session=session).order_by('created_at')
        if len(company_chats) <= 10:
            return "", ""
        ai_user = Profile.objects.get(id=1)
        company_bot = CompanyBot.objects.filter(company=profile.company)
        if company_bot.count() > 0:
            company_bot = company_bot[0]
            end_context = company_bot.end_context
            if end_context is None or end_context == "":
                end_context = DEFAULT_PROMPT
        else:
            end_context = DEFAULT_PROMPT
        end_context += company_context
        extra_context = get_company_end_context(company_slug)
        end_context += extra_context
        print('-------------------------------')
        print(end_context)
        messages = []
        prompt_to_use = [
            {
                'text':  end_context
            }
        ]
        for chat in company_chats:
            if chat.receiver == ai_user:
                user_message = chat.message
                if chat.translated_message is not None and chat.translated_message != '':
                    user_message = chat.translated_message
                messages.append({
                    'role': 'user',
                    'content': [{'text': user_message}]
                })
            else:
                messages.append({
                    'role': 'assistant',
                    "content": [{'text': chat.message}]
                })

        response_json = handle_bedrock_model(
            system_prompt = prompt_to_use, messages = messages, max_token = 2048,
            temperature = 0.7, top_p = 0.9
        )

        title = response_json.get('title', '')
        print('title: ', title)
        content = response_json.get('content', '')
        print('content: ', content)
        tweet = response_json.get('tweet', '')
        print('tweet: ', tweet)
        objective = response_json.get('objective', '')
        print('objective: ', objective)
        action_steps =  response_json.get('action_steps', '')
        print('action_steps: ', action_steps)
        impact =  response_json.get('impact', '')
        print('impact: ', impact)
        micro_improvement =  response_json.get('micro_improvement', '')
        print('micro_improvement: ', micro_improvement)

        if company_slug == 'shikshalokamstaging':
            duration = response_json.get('duration', '')
            other_params = {
                'duration': duration
            }
        else:
            other_params = {}

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
            other_params=other_params
        )

        story.save()
        formatted_content = get_formatted_story(story)
        story.formatted_content = formatted_content
        story.save(update_fields=['formatted_content'])
        if company_slug == 'shikshalokamstaging':
            create_project(response_json, story, profile)

        chat_session = ChatSession.objects.get(session=session)
        chat_session.session_status = ChatStatus.COMPLETED
        chat_session.save(update_fields=['session_status'])

        return story.id, story.content
    except Exception as e:
        traceback.print_exc()
        return "", ""


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


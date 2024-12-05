import json
import traceback
import random
import string
from chatbot.models import (Profile, CompanyChat, CompanyBot, StoryLanguageChoices,
                                                StoryStatusChoices, ChatSession, ChatStatus, LLMModel)
from chatbot.models.geo_models import ProfileAddress
from chatbot.models.story_models import Story
from chatbot.utils.shikshalokam_story_utils import save_shikshalokam_story
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


def create_story_object(profile_id, session, access_token, problem_statement, project_id, model=None):
    try:
        profile = Profile.objects.get(id=profile_id)
        company = profile.company
        company_slug = company.slug
        company_context = get_company_context(profile, company)
        company_chats = CompanyChat.objects.filter(session=session).order_by('created_at')
        # if len(company_chats) <= 10:
        #     return "", ""
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
        # content_prompt = get_company_content_prompt()
        end_context += extra_context
        # end_context += content_prompt
        print('-------------------------------')
        print(end_context)

        messages=[]
        chat_history=[]
        prompt_to_use = [
            {
                'text': end_context
            },
        ]
        for chat in company_chats:
            user_message = chat.message
            if chat.receiver == ai_user:
                if chat.translated_message is not None and chat.translated_message != '':
                    user_message = chat.translated_message
                messages.append({
                    'role': 'user',
                    'content': [{'text': user_message}]
                })
                chat_history.append({
                    'role': 'user',
                    'content': [{'text': user_message, 'created_at': chat.created_at}]
                })
            else:
                messages.append({
                    'role': 'assistant',
                    'content': [{'text': user_message}]
                })
                chat_history.append({
                    'role': 'assistant',
                    'content': [{'text': user_message, 'created_at': chat.created_at}]
                })

        if messages and messages[0].get('role') == 'bot':
            messages.pop(0)
        tool_to_use = get_end_story_tools()

        response_json = handle_bedrock_model(
            system_prompt = prompt_to_use, messages = messages, tools=tool_to_use,
            temperature=0.0, max_token=2048
        )
        response_json = response_json.replace('\n', '').replace('\t', '').replace(
            '\r', '').replace('\\n', '').replace('\\t', '').replace('\\r', '')
        if '{' in response_json:
            response_json = response_json[response_json.index('{'):]
        print("\nBEFORE LOADS: ", response_json)
        if isinstance(response_json, str):
            response_json = json.loads(response_json)
        print("response_json: ", response_json)
        print("TYPE response_json: ", type(response_json))

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
            location=location
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

        if access_token and problem_statement and project_id:
            save_shikshalokam_story(
                story=story, chat_history=chat_history, access_token=access_token,
                problem_statement=problem_statement, project_id=project_id, session=session
            )
        else:
            save_shikshalokam_story(
                story=story, chat_history=chat_history, access_token=access_token,
                problem_statement=problem_statement, project_id=project_id, session=session
            )

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


def get_end_story_tools():
    tool = {
        "toolConfig": {
            "tools": [
                {
                    "toolSpec": {
                        "name": "get_story_output",
                        "description": "Generate a detailed narrative output in a valid JSON format containing specific fields.",
                        "inputSchema": {
                            "json": {
                                "type": "object",
                                "properties": {
                                    "author_name": {
                                        "type": "string",
                                        "description": "Name of the author."
                                    },
                                    "state": {
                                        "type": "string",
                                        "description": "The user's state."
                                    },
                                    "district": {
                                        "type": "string",
                                        "description": "The user's district."
                                    },
                                    "block": {
                                        "type": "string",
                                        "description": "The user's block."
                                    },
                                    "conversation_data": {
                                        "type": "string",
                                        "description": "Text of the conversation to create the narrative from."
                                    },
                                    "start_date": {
                                        "type": "string",
                                        "description": "Starting date of the project if any.",
                                        "format": "date"
                                    },
                                    "end_date": {
                                        "type": "string",
                                        "description": "Completion date of the project if any.",
                                        "format": "date"
                                    }
                                },
                                "required": ["author_name", "state", "district", "block", "conversation_data"]
                            }
                        }
                    }
                }
            ]
        }
    }

    return tool

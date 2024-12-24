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
from jinja2 import Template


def create_story_object(profile_id, session, access_token, flow, model=None):
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
        story_prompt = f"""
            {context}
            
            {tag_context}
            
            {end_context}
        """
        print('-------------------------------')
        print(story_prompt)

        messages=[]
        chat_history=[]
        conversation=[]
        prompt_to_use = [
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
                conversation.append({
                    "botResponse": "",
                    "timestamp": chat.created_at.isoformat(),
                    "userMessage": user_message
                })
                chat_history.append({
                    "details": "",
                    "event": chat.status,
                    "timestamp": chat.created_at.isoformat()
                })
            else:
                messages.append({
                    'role': 'assistant',
                    'content': [{'text': user_message}]
                })
                if conversation and len(conversation)>0:
                    conversation[-1]["botResponse"] = user_message
                chat_history.append({
                    "details": "",
                    "event": chat.status,
                    "timestamp": chat.created_at.isoformat()
                })

        # print("\n\nchat_history: ", chat_history)
        # print("\n\nconversation: ", conversation)
        tool_to_use = get_end_story_tools()

        response_json = handle_bedrock_model(
            system_prompt = prompt_to_use, messages = messages, tools=tool_to_use,
            temperature=0.5, max_token=2048, top_p=0.9
        )

        response_json = response_json.replace('\n', '').replace('\t', '').replace(
            '\r', '').replace('\\n', '').replace('\\t', '').replace('\\r', '')
        if '{' in response_json:
            response_json = response_json[response_json.index('{'):]
        print("\nBEFORE LOADS: ", response_json)
        if isinstance(response_json, str):
            response_json = json.loads(response_json)
        print("AFTER LOADS: ", response_json)
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

        problem_statement = response_json.get('problem_statement', '')
        print('problem_statement: ', problem_statement)


        duration = response_json.get('duration', '')
        other_params = {
            'duration': duration
        }

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

        chat_session = ChatSession.objects.get(session=session)
        project_id = chat_session.project_id

        create_project(response_json, story, profile, problem_statement, project_id)

        chat_session.session_status = ChatStatus.COMPLETED
        chat_session.save(update_fields=['session_status'])

        save_shikshalokam_story(
            story=story, chat_history=chat_history, access_token=access_token,
            problem_statement=problem_statement, project_id=project_id, session=session,
            profile=profile, conversation=conversation, flow=flow
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
                                    "title": {
                                        "type": "string",
                                        "description": "Title of the story"
                                    },
                                    "objective": {
                                        "type": "string",
                                        "description": "Objective of the micro improvement"
                                    },
                                    "action_steps": {
                                        "type": "string",
                                        "description": "5 Action steps taken by the user to implement the micro improvement"
                                    },
                                    "impact": {
                                        "type": "string",
                                        "description": "Impact created from this micro improvement"
                                    },
                                    "micro_improvement": {
                                        "type": "string",
                                        "description": "Why is this micro-improvement important"
                                    },
                                    "resource_name": {
                                        "type": "string",
                                        "description": "Learning resources name that you want the stakeholders to see while doing the project"
                                    },
                                    "resource_link": {
                                        "type": "string",
                                        "description": "Learning resources link that you want the stakeholders to see while doing the project"
                                    },
                                    "duration": {
                                        "type": "string",
                                        "description": "Total time span of the project, from start to end"
                                    },
                                    "keywords": {
                                        "type": "string",
                                        "description": "Keywords improve search ability, tag this Improvement project with appropriate keywords"
                                    },
                                    "status": {
                                        "type": "string",
                                        "description": "The current state of the project, such as 'STARTED,' 'inPROGRESS,' or 'SUBMITTED'"
                                    },
                                    "project_start_date": {
                                        "type": "string",
                                        "description": "Starting date of the project if any"
                                    },
                                    "project_end_date": {
                                        "type": "string",
                                        "description": "Completion date of project if any"
                                    },
                                    "content": {
                                        "type": "string",
                                        "description": "Content of the story. MAKE SURE CONTENT GENERATED IS AROUND 600 WORDS"
                                    },
                                    "problem_statement": {
                                        "type": "string",
                                        "description": "The challenge faced by the user and what they wanted to solve"
                                    }
                                },
                                "required": ["title", "objective", "action_steps", "impact", "micro_improvement",
                                             "duration", "status", "content", "problem_statement"]
                            }
                        }
                    }
                }
            ]
        }
    }

    return tool

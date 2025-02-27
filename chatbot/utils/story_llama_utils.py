import json
import secrets
import traceback
from datetime import datetime
from chatbot.models.geo_models import ProfileAddress
from chatbot.utils.audio_provider_utils import text_translate_provider
from shikshalokam.models import Project, ProjectStatus


def get_company_context(profile, company):
    address = ProfileAddress.objects.filter(profile=profile)
    if len(address) > 0 and company.slug == 'shikshalokam':
        return """
        Use following personal information as well:
        Name of Author: {},
        School Name: {},
        State: {},
        District: {},
        Block: {},
        Designation of Author: {} 
        """.format(profile.first_name, profile.org_associated, address[0].state, address[0].district,
                   address[0].block, profile.designation)
    elif len(address) > 0 and company.slug == 'shikshalokamstaging':
        return """
        Use following personal information as well:
        Name of Author: {},
        State: {},
        District: {},
        Block: {},
        """.format(profile.first_name, address[0].state, address[0].district, address[0].block)
    else:
        return ''


def get_company_end_context(slug):
    if slug == 'shikshalokamstaging':
        return """
            Make sure to use SIMPLE AT A HIGH SCHOOL LEVEL ENGLISH.
            OUTPUT SHOULD BE A VALID JSON FORMAT WITHOUT ANY EXTRA INFORMATION OUTSIDE THE JSON.:
            {
                "title": "Title of the story",
                "tweet": "Tweet for the story in less than 200 characters with minimum 5 hashtags",
                "objective": "Objective of the micro improvement",
                "action_steps": "5 Action steps taken by the user to implement the micro improvement",
                "impact": "Impact created from this micro improvement",
                "micro_improvement": "Why is this micro-improvement important",
                "resource_name": "Learning resources name that you want the stakeholders to see while doing the project",
                "resource_link": "Learning resources link that you want the stakeholders to see while doing the project",
                "duration": "Total time span of the project, from start to end",
                "keywords": "Keywords improve search ability, tag this Improvement project with appropriate keywords",
                "status": "The current state of the project, such as 'STARTED,' 'inPROGRESS,' or 'SUBMITTED'.",
                "project_start_date": "Starting date of the project if any.",
                "project_end_date": "Completion date of project if any.",
                "content": "Content of the story. Make sure content generated is around 600 words.",
                "problem_statement": "The challenge faced by the user and what they wanted to solve."
            }


            Ensure all JSON fields are properly formatted. If certain information is not explicitly provided in 
            the conversation, use reasonable inferences or leave the field empty.

            Respond only with valid JSON. Do not write an introduction or summary.

        """
    else:
        return """
            OUTPUT JSON FORMAT:
            {
                "title": "Title of the story",
                "content": "Content of the story in 600 words",
                "tweet": "Tweet for the story in less than 200 characters with minimum 5 hashtags",
                "objective": "Objective of the micro improvement",
                "action_steps": "5 Action steps taken by the user to implement the micro improvement",
                "impact": "Impact created from this micro improvement",
                "micro_improvement": "Why is this micro-improvement important"
            }
            Respond only with valid JSON. Do not write an introduction or summary.
        """


def get_company_content_prompt():
    return """
        Make sure to use SIMPLE AT A HIGH SCHOOL LEVEL ENGLISH.
        OUTPUT SHOULD BE A VALID JSON FORMAT WITHOUT ANY EXTRA INFORMATION OUTSIDE THE JSON.:
        {
            "story": "Content of the story. Make sure content generated of 600 words. This filed needs to be the story of user experience."
        }

        Ensure the story is around 600 words AND NOT LESS, capturing all details provided without adding additional information.
        Expand on each step of the journey, describing actions, emotions, challenges, and the eventual resolution in detail. 
        Include vivid but straightforward details on each point, capturing what the protagonist saw, felt, and thought.
        Respond only with valid JSON CONTAINING "story" FIELD. Do not write an introduction or summary.
    """


def create_project(response_json, title, objective, story, profile, problem_statement, project_id, language,
                   voice_provider):
    try:
        resource_name = response_json.get('resource_name', '')
        resource_link = response_json.get('resource_link', '')
        duration = response_json.get('duration', '')
        keywords = response_json.get('keywords', '')
        project_start_date = parse_datetime(response_json.get('project_start_date', ''))
        project_end_date = parse_datetime(response_json.get('project_end_date', ''))
        if language != 'en':
            keywords = translate_field(
                voice_provider=voice_provider, message_body=keywords, target_language=language
            )

            resource_name = translate_field(
                voice_provider=voice_provider, message_body=resource_name, target_language=language
            )
        if not project_id:
            project_id = generate_random_hex()

        project, created = Project.objects.update_or_create(
            project_id=project_id,
            defaults={
                "story": story,
                "author": profile,
                "actual_title": title,
                "actual_objective": objective,
                "actual_duration": duration,
                "project_status": ProjectStatus.SUBMITTED,
                "actual_problem_statement": problem_statement,
                "keywords": keywords,
                "resource_name": resource_name,
                "resource_link": resource_link,
                "project_start_date": project_start_date,
                "project_end_date": project_end_date,
                "project_language": language
            }
        )

        if created:
            print("A new project was created.")
        else:
            print("The existing project was updated.")

        project.save()
        return story.id, story.content

    except Exception as e:
        traceback.print_exc()
        return "", ""


def generate_random_hex(length=16):
    return secrets.token_hex(length)


def parse_datetime(date_str):
    try:
        if date_str:
            return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    return None


def validate_json(response_content):
    if isinstance(response_content, dict):
        return response_content
    try:
        return json.loads(response_content)
    except json.JSONDecodeError:
        print('Invalid JSON response:', response_content)
        return response_content


def translate_field(voice_provider, message_body, target_language, source_language="en"):
    if message_body == '' or not message_body:
        return message_body
    response = text_translate_provider(
        voice_provider=voice_provider, message_body=message_body, target_language=target_language,
        source_language=source_language
    )
    if response.get('status') == 200:
        return response.get('content')
    else:
        return message_body

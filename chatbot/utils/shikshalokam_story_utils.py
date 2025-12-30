from chatbot.models import StoryMedia, MediaTypeChoices, CompanyChat, Profile, Story, ChatSession, SessionFlowName
from chatbot.models.base_models import Flow
from chatbot.models.company_models import PDFTemplates
from chatbot.models.enums import UserTypeChoices
from chatbot.serializer.profile_serializer import ProfileSerializer
from chatbot.serializer.story_serializer import StoryCreateSerializer
from chatbot.utils.elevate.project_detail import fetch_existing_project_attachments
from chatbot.utils.gotenberg_utils import generate_pdf_with_gotenberg
from chatbot.utils.media_utils import upload_to_cloud
from chatbot.utils.shikshalokam_mitra_utils import get_stored_conversation, get_stored_chathistory
from django.core.files.base import ContentFile
from jinja2 import Template
from shikshalokam.models import Project
from shikshalokam.serializer import ProjectSerializer
import json
import os
import re
import requests
import traceback

base_url = os.getenv("SHIKSHALOKAM_BASE_URL")


def save_shikshalokam_story( story, problem_statement, chat_history, access_token, project_id, session, profile, conversation, flow, language="en"):
    try:
        html_content = get_story_html(story=story, profile=profile, flow=flow, auth=access_token is not None)

        pdf_generated = generate_pdf_with_gotenberg(html_content)
        pdf_file_name = story.title
        if not pdf_file_name or pdf_file_name == '':
            pdf_file_name = 'Improvement_story'
        pdf_file_name = f"{pdf_file_name}.pdf"
        pdf_content = ContentFile(pdf_generated, name=pdf_file_name)
        print("pdf_content: ", pdf_content)
        print("pdf_content type: ", type(pdf_content))
        # StoryMedia.objects.create(
        #     name=pdf_file_name,
        #     file=pdf_content,
        #     story=story,
        #     include_in_story=False,
        #     media_type=MediaTypeChoices.PDF
        # )

        story_media, created = StoryMedia.objects.update_or_create(
            story=story,
            media_type=MediaTypeChoices.PDF,
            defaults={
                "name": pdf_file_name,
                "file": pdf_content,
                "include_in_story": False
            }
        )

        if created:
            print("New PDF created")
        else:
            print("Existing PDF updated")

        if access_token in [None, "", "null"] or not session or not project_id or flow != SessionFlowName.Reflection:
            print("Not calling shikshalokam api as access_tokne or session or project_id is missing")
            return
        upload_response_json = upload_to_cloud(session_value=session, access_token=access_token, story=story)
        attachments = upload_response_json.get('attachments')
        print("attachments: ", attachments)

        pdf_information = upload_response_json.get('pdfInformation')
        print("pdf_information: ", pdf_information)


        request_body = {
            "story": {
                "title": story.title,
                "problemStatement": problem_statement,
                "objective": story.objective,
                "timeline": "",
                "actionSteps": story.action_steps or [],
                "resources": [],
                "impact": story.impact,
                "summary": story.content,
                "authorName": story.author.first_name if story.author else "",
                "location": story.location or "",
                "conversation": conversation,
                "chatHistory": chat_history,
                "attachments": attachments,
                "pdfInformation": pdf_information,
            }
        }
        print("request_body: ", request_body)
        print("type: ", type(request_body))
        print("type: ", type(request_body.get("story")))

        url = f"https://{base_url}/userProjects/addStory/{project_id}"
        print("Using url: ", url)

        headers = {
            "X-auth-token": access_token,
        }

        response = requests.put(url, headers=headers, json=request_body)
        print("Res:", response)
        print("response: ", response.json())
        response.raise_for_status()

        print(f"Story successfully saved to Shikshalokam: {response.status_code}")
    except Exception as e:
        traceback.print_exc()
        print(f"Failed to save story to Shikshalokam: {str(e)}")
        raise e


def get_story_html(story, profile, flow, auth=False, language=None):
    project = Project.objects.filter(story=story).first()
    flow_obj = Flow.objects.get(flow_route=flow)

    language_used = language

    if language_used is None:
        chat_session = ChatSession.objects.filter(session=story.session).first()
        translation_languages = list(story.translations.values_list('language', flat=True))
        language_used = (
            chat_session.language or
            translation_languages[0] if translation_languages else
            (project.project_language if project else None) or
            story.language or
            'en'
        )

    story_serialized = StoryCreateSerializer(story)
    project_serialized = ProjectSerializer(project)
    profile_serialized = profile

    pdf_template: PDFTemplates | None = None
    if auth:
        pdf_template = PDFTemplates.objects.filter(
            flow=flow_obj, 
            user_type__in=[UserTypeChoices.AUTH, UserTypeChoices.ALL]
        ).first()
    else:
        pdf_template = PDFTemplates.objects.filter(flow=flow_obj,
            user_type__in=[UserTypeChoices.GUEST, UserTypeChoices.ALL]
        ).first()

    if pdf_template is None:
        return ""

    jinja_template = pdf_template.template
    constants = pdf_template.constants_json

    render_params = {
        "constants": constants.get(language_used, {}),
        "story": story_serialized.data,
        "project": project_serialized.data,
        "profile": profile_serialized
    }

    print(json.dumps(render_params, indent=2))

    template = Template(jinja_template)
    html_content = template.render(**render_params)
    return html_content

def update_story_pdf(access_token, session, flow, is_edit_story=False):

    try:
        story = Story.objects.get(session=session)
        if story and story.content and story.formatted_content:
            update_story_content(story)
        profile = story.author
        print("profile: ", profile)
        print("story: ", story.title)
        print("story format: ", story.formatted_content)
        html_content = get_story_html(story=story, profile=profile, flow=flow)

        pdf_generated = generate_pdf_with_gotenberg(html_content)
        # print("pdf_generated: ", pdf_generated)
        pdf_file_name = story.title
        if not pdf_file_name or pdf_file_name == '':
            pdf_file_name = 'Improvement_story'
        pdf_file_name = f"{pdf_file_name}.pdf"
        print("pdf_file_name: ", pdf_file_name)
        pdf_content = ContentFile(pdf_generated, name=pdf_file_name)
        print("pdf_content: ", pdf_content)
        print("pdf_content type: ", type(pdf_content))

        story_media = StoryMedia.objects.filter(story=story, media_type=MediaTypeChoices.PDF).first()

        story_media.name = pdf_file_name
        story_media.file.save(pdf_file_name, pdf_content)
        story_media.include_in_story = False
        story_media.save()
        print("StoryMedia updated and saved successfully.")
        print(f"Updated name: {story_media.name}")
        print(f"Updated file path: {story_media.file}")
        print(f"Include in story: {story_media.include_in_story}")
        print(f"Public url: {story_media.get_public_url()}")
        chat_session = ChatSession.objects.get(session=session)
        project_id = chat_session.project_id

        if (access_token in [None, "", "null"] or not session or not project_id or
                flow not in[SessionFlowName.Reflection, SessionFlowName.GuestMiStory]):
            print("Not calling shikshalokam api as access_tokne or session or project_id is missing")
            return

        upload_response_json = upload_to_cloud(
            session_value=session, access_token=access_token, story=story
        )

        print("upload_response_json: ", upload_response_json)
        story_media_objects = StoryMedia.objects.filter(
            story=story, include_in_story=True
        ).exclude(media_type=MediaTypeChoices.PDF)
        attachments=[]
        if is_edit_story:
            existing_attachments = fetch_existing_project_attachments(project_id, access_token)
            print("existing_attachments: ", existing_attachments)
            if existing_attachments:
                attachments.extend(existing_attachments)

            attachments.extend([
                {
                    "name": media.name,
                    "sourcePath": media.source_path,
                    "type": media.media_type,
                    "page": "story"

                }
                for media in story_media_objects
            ])
        print("attachments: ", attachments)

        pdf_information = upload_response_json.get('pdfInformation')
        print("pdf_information: ", pdf_information)

        company_chats = CompanyChat.objects.filter(session=session).order_by('created_at')
        ai_user = Profile.objects.get(id=1)

        if company_chats and company_chats[0].receiver != ai_user:
            company_chats.pop(0)
        conversation = get_stored_conversation(company_chats=company_chats)
        chat_history = get_stored_chathistory(company_chats=company_chats)

        request_body = {
            "story": {
                "title": story.title,
                "objective": story.objective,
                "timeline": "",
                "actionSteps": story.action_steps or [],
                "resources": [],
                "impact": story.impact,
                "summary": story.content,
                "authorName": story.author.first_name if story.author else "",
                "location": story.location or "",
                "conversation": conversation,
                "chatHistory": chat_history,
                "attachments": attachments,
                "pdfInformation": pdf_information,
            },
            "tasks": [
                {
                    "_id": chat_session.other_params.get('task_id'),
                    "status": "completed"
                }
            ]
        }

        headers = {
            "X-auth-token": access_token,
        }
        print("Req body: ", request_body)
        if flow in [SessionFlowName.GuestMiStory]:
            url = f"https://{base_url}/userProjects/update/{project_id}"
            response = requests.post(url, headers=headers, json=request_body)
        else:
            url = f"https://{base_url}/userProjects/addStory/{project_id}"
            response = requests.put(url, headers=headers, json=request_body)

        print("Response: ", response.text)
        response.raise_for_status()

        print(f"Story successfully updated to Shikshalokam: {response.status_code}")

    except requests.exceptions.RequestException as e:
        print("Failed to save story to Shikshalokam: %s", e)
        raise
    except Exception as e:
        print("An unexpected error occurred: %s", e)
        traceback.print_exc()
        raise


def update_story_content(story):
    try:
        formatted_data = json.loads(story.formatted_content)
    except (json.JSONDecodeError, TypeError):
        print("Invalid or missing formatted_content")
        return

    accumulated_text = ""
    for block in formatted_data:
        if block.get("type") == "paragraph" and "data" in block and "text" in block["data"]:
            # accumulated_text += block["data"]["text"] + "\n"
            plain_text = re.sub(r'<[^>]+>', '', block["data"]["text"])
            accumulated_text += plain_text + "\n"

    print("\nold content: ", story.content)
    print("\naccumulated_text: ", accumulated_text)
    story.content = accumulated_text.strip()
    story.save()

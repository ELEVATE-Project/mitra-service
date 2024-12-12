import os
import traceback
import requests

from chatbot.models import StoryMedia, MediaTypeChoices
from chatbot.pdf.story_first_page import get_first_page_html
from chatbot.pdf.story_images_page import get_story_images_page_html
from chatbot.pdf.story_secondpage import get_story_secondpage_html
from chatbot.pdf.story_thirdpage import get_thirdpage_html
from chatbot.utils.gotenberg_utils import generate_pdf_with_gotenberg
from chatbot.utils.media_utils import upload_to_cloud

base_url = os.getenv("SHIKSHALOKAM_BASE_URL")


def save_shikshalokam_story(story, problem_statement, chat_history, access_token, project_id, session, profile):
    try:
        html_content = get_story_html(story=story, profile=profile)

        pdf_generated = generate_pdf_with_gotenberg(html_content)
        pdf_file_name = story.get("title")
        pdf_file_name = f"{pdf_file_name}.pdf"
        StoryMedia.objects.create(
            name=pdf_file_name,
            file=pdf_generated,
            story=story,
            include_in_story=False,
            media_type=MediaTypeChoices.PDF
        )

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
                "conversation": [],
                "chatHistory": chat_history,
                "attachments": attachments,
                "pdfInformation": pdf_information,
            }
        }
        print("request_body: ", request_body)

        url = f"https://{base_url}/project/userProjects/addStory/{project_id}"

        headers = {
            "X-auth-token": access_token,
        }

        response = requests.post(url, headers=headers, json=request_body)
        response.raise_for_status()

        print(f"Story successfully saved to Shikshalokam: {response.status_code}")
    except Exception as e:
        traceback.print_exc()
        print(f"Failed to save story to Shikshalokam: {str(e)}")


def get_story_html(story, profile):
    css_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../pdf/story_pdf.css"))

    with open(css_path, 'r') as css_file:
        inline_css = css_file.read()
    html_content = f"""
            <!DOCTYPE html>
            <html>
                <head>
                    <meta charset="utf-8" />
                    <link rel="preconnect" href="https://fonts.googleapis.com">
                    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
                    <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@200..800&family=Open+Sans:ital,wght@0,300..800;1,300..800&family=Urbanist:ital,wght@0,100..900;1,100..900&display=swap" rel="stylesheet">
                    <style>
                    #header, #footer {{ padding: 0 !important; }}
                    {inline_css}
                    </style>
                </head>
             <body>

        """
    html_content += get_first_page_html(story=story, profile=profile)
    html_content += get_story_images_page_html(story=story)
    html_content += get_story_secondpage_html(story=story)
    html_content += get_thirdpage_html(story=story, profile=profile)
    html_content += f"""

            </body>
        </html>
        """

    return html_content

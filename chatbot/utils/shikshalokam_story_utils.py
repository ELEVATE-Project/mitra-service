import json
import os
import re
import traceback
from django.core.files.base import ContentFile
from chatbot.models import StoryMedia, MediaTypeChoices, CompanyChat, Profile, Story, ChatSession
from chatbot.pdf.story_first_page import get_first_page_html
from chatbot.pdf.story_images_page import get_story_images_page_html
from chatbot.pdf.story_secondpage import get_story_secondpage_html
from chatbot.pdf.story_thirdpage import get_thirdpage_html
from chatbot.utils.gotenberg_utils import generate_pdf_with_gotenberg


base_url = os.getenv("SHIKSHALOKAM_BASE_URL")


def save_shikshalokam_story(
        story, profile
):
    try:
        html_content = get_story_html(story=story, profile=profile)

        pdf_generated = generate_pdf_with_gotenberg(html_content)
        pdf_file_name = story.title
        if not pdf_file_name or pdf_file_name == '':
            pdf_file_name = 'mi_story'
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

    except Exception as e:
        traceback.print_exc()
        print(f"Failed to save story to Shikshalokam: {str(e)}")


def get_story_html(story, profile):
    css_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../pdf/story_pdf.css"))
    pdf_file_name = story.title

    with open(css_path, 'r') as css_file:
        inline_css = css_file.read()
    html_content = f"""
            <!DOCTYPE html>
            <html>
                <head>
                    <meta charset="utf-8" />
                    <title>{pdf_file_name}</title>
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
    html_content += get_story_secondpage_html(story=story)
    html_content += get_story_images_page_html(story=story)
    html_content += get_thirdpage_html(story=story, profile=profile)
    html_content += f"""

            </body>
        </html>
        """

    return html_content


def update_story_pdf(session):

    try:
        story = Story.objects.get(session=session)
        update_story_content(story)
        profile = story.author
        print("profile: ", profile)
        print("story: ", story.title)
        print("story format: ", story.formatted_content)
        html_content = get_story_html(story=story, profile=profile)

        pdf_generated = generate_pdf_with_gotenberg(html_content)
        pdf_file_name = story.title
        if not pdf_file_name or pdf_file_name == '':
            pdf_file_name = 'mi_story'
        pdf_file_name = f"{pdf_file_name}.pdf"
        pdf_content = ContentFile(pdf_generated, name=pdf_file_name)
        print("pdf_content: ", pdf_content)
        print("pdf_content type: ", type(pdf_content))

        story_media = StoryMedia.objects.get(story=story, media_type=MediaTypeChoices.PDF)

        story_media.name = pdf_file_name
        story_media.file.save(pdf_file_name, pdf_content)
        story_media.include_in_story = False
        story_media.save()
        print("StoryMedia updated and saved successfully.")

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

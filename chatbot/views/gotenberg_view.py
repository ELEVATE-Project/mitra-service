from rest_framework.decorators import api_view
import os
from django.http import HttpResponse
from chatbot.models import Profile, Story
from chatbot.pdf.story_first_page import get_first_page_html
from chatbot.pdf.story_images_page import get_story_images_page_html
from chatbot.pdf.story_secondpage import get_story_secondpage_html
from chatbot.pdf.story_thirdpage import get_thirdpage_html
from chatbot.utils.gotenberg_utils import generate_pdf_with_gotenberg


@api_view(['GET'])
def generate_pdf_view(request):
    profile = Profile.objects.get(id=4)
    story = Story.objects.get(session="z0ou6sjf102601ngzu8q5oeqptxuqu0a")
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

    return generate_pdf_with_gotenberg(html_content)

    # return HttpResponse(html_content, content_type="text/html", status=200)

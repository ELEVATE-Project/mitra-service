from rest_framework.decorators import api_view
import os
from django.http import HttpResponse
from chatbot.models import Profile, Story
from chatbot.pdf.story_first_page import get_first_page_html
from chatbot.pdf.story_images_page import get_story_images_page_html
from chatbot.pdf.story_secondpage import get_story_secondpage_html
from chatbot.pdf.story_thirdpage import get_thirdpage_html
from chatbot.utils.gotenberg_utils import generate_pdf_with_gotenberg
from chatbot.utils.shikshalokam_story_utils import get_story_html
from django.core.files.base import ContentFile


@api_view(['GET'])
def generate_pdf_view(request):
    body = request.data
    session = body.get("session")

    story = Story.objects.get(session=session)
    profile = story.author

    html_content = get_story_html(story=story, profile=profile)

    pdf_generated =  generate_pdf_with_gotenberg(html_content)
    pdf_file_name = f"Sample.pdf"
    pdf_content = ContentFile(pdf_generated, name=pdf_file_name)
    print("pdf_content: ", pdf_content)
    print("pdf_content type: ", type(pdf_content))
    if pdf_generated:
        http_response = HttpResponse(pdf_generated, content_type="application/pdf")
        http_response["Content-Disposition"] = 'inline; filename="output.pdf"'
        return http_response
    else:
        return HttpResponse("Error generating pdf!", status=500)

    # return HttpResponse(html_content, content_type="text/html", status=200)

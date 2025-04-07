from chatbot.models import StoryMedia


def get_report_images_page_html(story):

    story_media = StoryMedia.objects.filter(story=story, include_in_story=True).exclude(media_type="pdf")
    images = [media.get_public_url() for media in story_media]
    image_elements = ""
    page_html = ""

    for image in images:
        image_elements += f"""
        <div class="story-image-page-image-box" style="page-break-inside: avoid;">
          <img src="{image}" alt="Story Image" style="width:100%; height:100%; border-radius: 10px;" />
        </div>
        """

    page_html += f"""
    <div class="story-image-page-container">
      <div class="story-image-page-grid">
        {image_elements}
      </div>
    </div>
    """

    return page_html

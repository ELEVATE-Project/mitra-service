from chatbot.models import StoryMedia


def get_story_images_page_html(story):

    story_media = StoryMedia.objects.filter(story=story, include_in_story=True).exclude(media_type="pdf")
    images = [media.get_public_url() for media in story_media]
    image_elements = ""

    for image in images:
        image_elements += f"""
        <div class="story-image-page-image-box">
          <img src="{image}" alt="Story Image" style="width:100%; height:100%; border-radius: 10px;" />
        </div>
        """

    page_html = f"""
              <div class="story-image-page-container page-break">
                <h1 class="story-image-page-title">Story</h1>
                <div class="story-image-page-grid">
                  {image_elements}
                </div>
              </div>
        """
    return page_html

from chatbot.models import StoryMedia


def get_story_images_page_html_kannada(story):

    story_media = StoryMedia.objects.filter(story=story, include_in_story=True).exclude(media_type="pdf")
    images = [media.get_public_url() for media in story_media]
    image_elements = ""
    image_batches = [images[i : i+6] for i in range(0, len(images), 6)]
    page_html = ""
    should_show_story_heading = True

    for batch in image_batches:
        image_elements = ""
        for image in batch:
            image_elements += f"""
            <div class="story-image-page-image-box">
              <img src="{image}" alt="Story Image" style="width:100%; height:100%; border-radius: 10px;" />
            </div>
            """

        page_html += f"""
        <div class="story-image-page-container page-break">
          {'<h1 class="story-image-page-title">ಕಥೆ</h1>' if should_show_story_heading 
            else '<div class="image-nohead"></div>'}
          <div class="story-image-page-grid">
            {image_elements}
          </div>
        </div>
        """
        should_show_story_heading = False

    return page_html

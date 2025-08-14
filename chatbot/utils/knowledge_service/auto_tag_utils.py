import os
from chatbot.models import Tag, TagChoices
from chatbot.scripts.knowledge_service.docs.ai_document_tag_extractor import get_doc_tags_from_ai
from chatbot.scripts.knowledge_service.docs.document_tag_extractor import get_tag_from_doc

S3_BASE_URL = os.getenv('S3_MEDIA_URL')


def auto_tag(media):
    file_url = str(media.url) if media.url is not None else S3_BASE_URL + media.file.name
    # auto_tags = get_tag_from_doc(file_url=file_url)
    auto_tags = get_doc_tags_from_ai(file_url=file_url, company_bot=media.company_bot)
    return auto_tags if auto_tags else []


def save_auto_tags(media):
    """
    Generate and save auto tags for the given media.
    """
    auto_tag_names = auto_tag(media)  # currently returns []
    tag_objs = []
    company = getattr(media.company_bot, 'company', None)

    for name in auto_tag_names:
        tag_obj, created = Tag.objects.get_or_create(
            name=name,
            company=company,
            defaults = {
                'created_by_id': 1,
                'status': TagChoices.APPROVED
            }
        )
        if not created and not tag_obj.status:
            tag_obj.status = TagChoices.APPROVED
            tag_obj.save()

        tag_objs.append(tag_obj)

    if tag_objs:
        # Add auto tags to the media, keeping existing tags
        media.tags.add(*tag_objs)
        print(f"Saved auto tags for media {media.id}: {[t.name for t in tag_objs]}")
    else:
        print(f"No auto tags generated for media {media.id}")

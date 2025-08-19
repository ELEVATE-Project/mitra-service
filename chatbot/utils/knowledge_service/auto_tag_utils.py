import os
from chatbot.celery_tasks.knowledge_service.tag_tasks import get_auto_tags
from chatbot.models import Tag, TagChoices

S3_BASE_URL = os.getenv('S3_MEDIA_URL')


def save_auto_tags(media):
    """
    Generate and save auto tags for the given media.
    """
    auto_tag_names = get_auto_tags(media)  # currently returns []
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

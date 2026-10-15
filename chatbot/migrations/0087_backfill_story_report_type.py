from django.db import migrations


# Values are spelled out rather than imported from chatbot.models.enums: a migration must
# keep behaving the same way even if the choices class is edited later.
VALID_REPORT_TYPES = {'mi-story', 'discussion-report'}


def backfill_report_type(apps, schema_editor):
    """
    Populate report_type on stories created before the column existed.

    Mirrors Story.get_report_type(): the story's flow (other_params['flow']) is matched
    against Flow.flow_route to find the PDF template whose tag carries the classification.
    Rows are updated in place - the historical model has no custom save(), and .update()
    avoids touching any other field.
    """
    Story = apps.get_model('chatbot', 'Story')
    PDFTemplates = apps.get_model('chatbot', 'PDFTemplates')

    # Ordered so the template kept for each flow route is the one
    # Story.get_report_type() would pick at runtime, which also orders by id. Without it
    # a flow carrying two templates could be backfilled with a different tag than the
    # value derived later.
    tag_by_flow_route = {}
    for template in (
        PDFTemplates.objects.exclude(tag__isnull=True).exclude(tag='')
        .select_related('flow').order_by('id')
    ):
        if template.flow and template.flow.flow_route not in tag_by_flow_route:
            tag_by_flow_route[template.flow.flow_route] = template.tag

    if not tag_by_flow_route:
        return

    # Collected per tag and written with one UPDATE each. Issuing an UPDATE per row would
    # make this slow on a large Story table and hold the transaction open for the whole
    # deploy; .iterator() keeps the result set from being loaded all at once.
    ids_by_tag = {}
    for story in Story.objects.filter(report_type__isnull=True).only('id', 'other_params').iterator():
        flow_route = (story.other_params or {}).get('flow')
        if not flow_route:
            continue
        tag = tag_by_flow_route.get(flow_route)
        if tag in VALID_REPORT_TYPES:
            ids_by_tag.setdefault(tag, []).append(story.pk)

    for tag, story_ids in ids_by_tag.items():
        Story.objects.filter(pk__in=story_ids).update(report_type=tag)


def clear_report_type(apps, schema_editor):
    """Reverse cleanly; the column itself is dropped by the preceding migration."""
    Story = apps.get_model('chatbot', 'Story')
    Story.objects.exclude(report_type__isnull=True).update(report_type=None)


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0086_story_report_type'),
    ]

    operations = [
        migrations.RunPython(backfill_report_type, clear_report_type),
    ]

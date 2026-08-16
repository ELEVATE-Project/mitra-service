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

    tag_by_flow_route = {}
    for template in PDFTemplates.objects.exclude(tag__isnull=True).exclude(tag='').select_related('flow'):
        if template.flow and template.flow.flow_route not in tag_by_flow_route:
            tag_by_flow_route[template.flow.flow_route] = template.tag

    if not tag_by_flow_route:
        return

    for story in Story.objects.filter(report_type__isnull=True).only('id', 'other_params'):
        flow_route = (story.other_params or {}).get('flow')
        if not flow_route:
            continue
        tag = tag_by_flow_route.get(flow_route)
        if tag in VALID_REPORT_TYPES:
            Story.objects.filter(pk=story.pk).update(report_type=tag)


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

from django.db import migrations


CHAUPAL_STORY_ROUTE = '/chaupal-story'
WOMAN_LEADER_CODE = 'woman_leader'


def set_default_role(apps, schema_editor):
    """
    Discussion reports carry an implicit role: every one of them is a Woman Leader
    report until the discussion bot is opened up to other personas.

    Seeded here rather than left to manual admin setup so the tag works on a fresh
    deployment. Only fills bots that have no default yet, so re-running never
    overwrites a choice someone made in the admin.
    """
    CompanyBot = apps.get_model('chatbot', 'CompanyBot')
    Role = apps.get_model('chatbot', 'Role')

    role = Role.objects.filter(code=WOMAN_LEADER_CODE).first()
    if not role:
        # Role master data is loaded separately; nothing to seed on an empty database.
        return

    CompanyBot.objects.filter(
        route=CHAUPAL_STORY_ROUTE, default_role__isnull=True
    ).update(default_role=role)


def unset_default_role(apps, schema_editor):
    """Reverse only what this migration set, leaving any other role untouched."""
    CompanyBot = apps.get_model('chatbot', 'CompanyBot')
    Role = apps.get_model('chatbot', 'Role')

    role = Role.objects.filter(code=WOMAN_LEADER_CODE).first()
    if not role:
        return

    CompanyBot.objects.filter(
        route=CHAUPAL_STORY_ROUTE, default_role=role
    ).update(default_role=None)


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0084_companybot_default_role_and_more'),
    ]

    operations = [
        migrations.RunPython(set_default_role, unset_default_role),
    ]

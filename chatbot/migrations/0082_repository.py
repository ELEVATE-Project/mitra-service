import uuid6

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0081_alter_chatsession_session_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='Repository',
            fields=[
                ('id', models.UUIDField(default=uuid6.uuid7, editable=False, primary_key=True, serialize=False)),
                ('repository_name', models.CharField(max_length=255)),
                ('provider_type', models.CharField(max_length=50)),
                ('root_link', models.TextField()),
                ('status', models.CharField(default='ACTIVE', max_length=50)),
                ('sync_enabled', models.BooleanField(default=True)),
                ('last_sync_cursor', models.TextField(blank=True, null=True)),
                ('last_sync_time', models.DateTimeField(blank=True, null=True)),
                ('last_successful_sync', models.DateTimeField(blank=True, null=True)),
                ('last_failed_sync', models.DateTimeField(blank=True, null=True)),
                ('last_error_message', models.TextField(blank=True, null=True)),
                ('total_resources', models.BigIntegerField(default=0)),
                ('org_id', models.UUIDField()),
                ('org_name', models.CharField(max_length=255)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_repositories', to='chatbot.profile')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_repositories', to='chatbot.profile')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'repositories',
            },
        ),
    ]

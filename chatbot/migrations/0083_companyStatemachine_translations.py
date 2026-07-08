from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0082_alter_chatsession_language_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='companystatemachine',
            name='translations',
            field=models.JSONField(
                blank=True,
                null=True,
                help_text='Cached translations keyed by language code. e.g. {"hi": {"text": "...", "audio_s3": "https://..."}}',
            ),
        ),
        migrations.AddField(
            model_name='historicalcompanystatemachine',
            name='translations',
            field=models.JSONField(
                blank=True,
                null=True,
                help_text='Cached translations keyed by language code. e.g. {"hi": {"text": "...", "audio_s3": "https://..."}}',
            ),
        ),
    ]

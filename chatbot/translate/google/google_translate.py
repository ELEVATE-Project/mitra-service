import traceback
from google.cloud import translate
import logging
from google.oauth2 import service_account
from django.conf import settings

logger = logging.getLogger('django')


def translate_text(
    text: str,
    project_id: str,
    source_language_code: str,
    target_language_code: str
):
    """Translating Text."""
    try:

        credentials = service_account.Credentials.from_service_account_file(settings.SECRETS_JSON_PATH)
        client = translate.TranslationServiceClient(credentials=credentials)
        location = "global"

        parent = f"projects/{project_id}/locations/{location}"

        response = client.translate_text(
            request={
                "parent": parent,
                "contents": [text],
                "mime_type": "text/plain",
                "source_language_code": source_language_code,
                "target_language_code": target_language_code,
            }
        )

        logger.info(f"Response from Google Text Translate: {response}")

        for translation in response.translations:
            return {
                'status': 200,
                'content': translation.translated_text
            }

    except Exception as e:
        logger.error(f'Error processing Google Text Translate:{e}')
        print(f"Error during translation API call: {str(e)}")
        traceback.print_exc()
        return {
            'status': 500,
            'content': f"Error during translation API call: {str(e)}"
        }

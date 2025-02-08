from google.cloud import translate


def translate_text(
    text: str,
    project_id: str,
    source_language_code: str,
    target_language_code: str
):
    """Translating Text."""
    try:

        client = translate.TranslationServiceClient()

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

        for translation in response.translations:
            return {
                'status': 200,
                'content': translation.translated_text
            }

    except Exception as e:
        print(f"Error during translation API call: {str(e)}")
        return {
            'status': 500,
            'content': f"Error during translation API call: {str(e)}"
        }

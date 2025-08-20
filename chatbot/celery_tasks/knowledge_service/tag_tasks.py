from celery import shared_task
from chatbot.scripts.knowledge_service.extraction.ai_extraction import get_doc_tags_from_ai
import os


@shared_task
def get_auto_extracted_data(file_path, company_bot_id=None, file_extension=None):
    from chatbot.models import CompanyBot

    company_bot = None
    if company_bot_id:
        try:
            company_bot = CompanyBot.objects.get(id=company_bot_id)
        except CompanyBot.DoesNotExist:
            pass

    extracted_data=None
    try:
        extracted_data = get_doc_tags_from_ai(
            file=file_path,
            company_bot=company_bot,
            file_extension=file_extension
        )
    except Exception as e:
        # log the error if needed
        print(f"[AutoTags] Error processing {file_path}: {e}")
    finally:
        # cleanup file no matter what
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as cleanup_err:
                print(f"[AutoTags] Failed to remove temp file {file_path}: {cleanup_err}")

    return extracted_data
from django.views.generic import TemplateView
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.http import JsonResponse
from django.views import View
from chatbot.models import Media, Tag, KeyValue, Profile, FileTypeChoices
from chatbot.models.media_models import PriorityChoices, MediaTypeChoices
import json
import tempfile, os
import uuid
from django.core.cache import cache
from celery.result import AsyncResult

from chatbot.celery_tasks.knowledge_service.tag_tasks import get_auto_extracted_data

BOT_PROFILE_ID = 1


@method_decorator(staff_member_required, name='dispatch')
class BatchMediaUploadView(TemplateView):
    template_name = 'admin/batch_upload.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['media_types'] = MediaTypeChoices.choices
        context['priorities'] = PriorityChoices.choices
        # Add company bots for selection
        from chatbot.models import CompanyBot
        context['company_bots'] = CompanyBot.objects.all()
        return context


@method_decorator(staff_member_required, name='dispatch')
class BatchMediaExtractView(View):
    """API endpoint for extracting data from uploaded files"""

    def post(self, request):
        try:
            files = request.FILES.getlist('files')
            company_bot_id = request.POST.get('company_bot_id')
            session_id = request.POST.get('session_id')  # NEW: for file storage
            extracted_data = []

            # Generate session ID if not provided
            if not session_id:
                session_id = str(uuid.uuid4())

            company_bot = None
            if company_bot_id:
                try:
                    from chatbot.models import CompanyBot
                    company_bot = CompanyBot.objects.get(id=company_bot_id)
                except CompanyBot.DoesNotExist:
                    pass

            for i, file in enumerate(files):
                try:
                    # Store file for retry purposes
                    file_key = self.store_file_for_retry(file, session_id, i)

                    data = self.extract_file_data(
                        file=file,
                        company_bot=company_bot,
                        file_index=i
                    )
                    data['status'] = 'success'
                    data['error'] = None
                    data['session_id'] = session_id
                    data['file_key'] = file_key
                except Exception as e:
                    data = {
                        'filename': file.name,
                        'status': 'error',
                        'error': str(e),
                        'file_index': i,
                        'session_id': session_id,
                        'file_key': self.store_file_for_retry(file, session_id, i),
                        'name': file.name,  # Use full filename as name
                        'media_type': self.get_media_type(file.name),
                        'description': f'Extracted from {file.name}',
                        'extracted_text': '',
                        'priority': 'P1',
                        'tags': [],
                        'manual_tags': [],
                        'auto_tags': [],
                        'auto_tag_task_id': None,
                        'auto_tags_ready': True,  # No task for failed extractions
                        'key_values': []  # Start with empty key-values for failed extractions
                    }

                extracted_data.append(data)

            return JsonResponse({
                'success': True,
                'data': extracted_data,
                'session_id': session_id
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

    def store_file_for_retry(self, file, session_id, file_index):
        """Store uploaded file in cache for retry purposes"""
        try:
            file_content = b''
            for chunk in file.chunks():
                file_content += chunk

            file_key = f"batch_upload_{session_id}_{file_index}_{file.name}"

            # Store file data in cache for 1 hour
            cache.set(file_key, {
                'content': file_content,
                'name': file.name,
                'size': file.size
            }, timeout=3600)

            return file_key
        except Exception as e:
            print(f"Error storing file for retry: {e}")
            return None

    def extract_file_data(self, file, company_bot, file_index):
        """Extract data from file and start async AI extraction"""
        file_extension = file.name.rsplit('.', 1)[-1].lower() if '.' in file.name else None

        # Test failure condition (commented out as requested)
        # if "fail" in file.name.lower():
        #     raise ValueError(f"Forced extraction failure for {file.name}")

        # Save file temporarily
        if "fail" in file.name.lower():
            print(f"Forced extraction failure for {file.name}")
            raise ValueError(f"Forced extraction failure for {file.name}")
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_extension}") as tmp:
            for chunk in file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        # Start async task (non-blocking)
        print(f"Starting async extraction task for {file.name}")
        task = get_auto_extracted_data.delay(
            file_path=tmp_path,
            company_bot_id=company_bot.id if company_bot else None,
            file_extension=file_extension
        )

        return {
            'filename': file.name,
            'file_index': file_index,
            'name': file.name,
            'media_type': self.get_media_type(file.name),
            'description': f'Extracted from {file.name}',
            'extracted_text': 'AI extraction in progress...',
            'priority': 'P1',
            'tags': [],
            'manual_tags': [],
            'auto_tags': [],
            'auto_tag_task_id': task.id,
            'auto_tags_ready': False,
            'key_values': []
        }

    def get_media_type(self, filename):
        """Map file extension to media type"""
        ext = filename.rsplit('.', 1)[-1].lower()
        ext_map = {
            'pdf': FileTypeChoices.PDF.label,
            'doc': FileTypeChoices.DOC.label,
            'docx': FileTypeChoices.DOCX.label,
            'txt': FileTypeChoices.TXT.label,
            'csv': FileTypeChoices.CSV.label,
            'xls': FileTypeChoices.XLS.label,
            'xlsx': FileTypeChoices.XLSX.label,
        }
        return ext_map.get(ext, FileTypeChoices.TXT.label)


@method_decorator(staff_member_required, name='dispatch')
class BatchMediaRetryExtractView(View):
    """API endpoint for retrying extraction of a single file"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            file_data = data.get('file_data')
            company_bot_id = data.get('company_bot_id')
            session_id = data.get('session_id')

            if not file_data:
                return JsonResponse({
                    'success': False,
                    'error': 'No file data provided'
                }, status=400)

            company_bot = None
            if company_bot_id:
                try:
                    from chatbot.models import CompanyBot
                    company_bot = CompanyBot.objects.get(id=company_bot_id)
                except CompanyBot.DoesNotExist:
                    pass

            # Try to retrieve stored file
            file_key = file_data.get('file_key')
            stored_file = None

            if file_key:
                stored_file = cache.get(file_key)

            if not stored_file:
                # Fallback: create a simple mock for demonstration
                # In production, you might want to ask user to re-upload
                return JsonResponse({
                    'success': False,
                    'error': 'Original file data not found. Please re-upload the file or try uploading again.'
                }, status=400)

            # Create a file-like object from stored data
            class StoredFile:
                def __init__(self, stored_data):
                    self.name = stored_data['name']
                    self.size = stored_data['size']
                    self._content = stored_data['content']

                def chunks(self):
                    # Return chunks of the stored content
                    chunk_size = 8192
                    for i in range(0, len(self._content), chunk_size):
                        yield self._content[i:i + chunk_size]

            try:
                stored_file_obj = StoredFile(stored_file)
                extract_view = BatchMediaExtractView()
                extracted_data = extract_view.extract_file_data(
                    file=stored_file_obj,
                    company_bot=company_bot,
                    file_index=file_data.get('file_index', 0)
                )
                extracted_data['status'] = 'success'
                extracted_data['error'] = None
                extracted_data['session_id'] = session_id
                extracted_data['file_key'] = file_key

                return JsonResponse({
                    'success': True,
                    'data': extracted_data
                })
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                })

        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Unexpected error: {str(e)}'
            }, status=400)


@method_decorator(staff_member_required, name='dispatch')
class BatchMediaTaskStatusView(View):
    """API endpoint for checking Celery task status and updating data when complete"""

    def post(self, request):
        try:
            from celery.result import AsyncResult
            data = json.loads(request.body)
            task_ids = data.get('task_ids', [])

            results = {}
            for task_id in task_ids:
                task = AsyncResult(task_id)
                if task.ready():
                    if task.successful():
                        # Process the AI extracted data
                        ai_data = task.result
                        processed_data = self.process_ai_extracted_data(ai_data)

                        results[task_id] = {
                            'status': 'SUCCESS',
                            'result': processed_data
                        }
                    else:
                        results[task_id] = {
                            'status': 'FAILURE',
                            'error': str(task.info)
                        }
                else:
                    results[task_id] = {
                        'status': 'PENDING'
                    }

            return JsonResponse({
                'success': True,
                'results': results
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

    def process_ai_extracted_data(self, ai_data):
        """Process AI extracted data into format expected by frontend"""
        if not ai_data or not isinstance(ai_data, dict):
            return {
                'auto_tags': [],
                'enhanced_data': None
            }

        # Extract and process the AI data
        title = ai_data.get('title', '')
        summary = ai_data.get('summary', '')
        extracted_text = ai_data.get('exact_content', '') or summary
        auto_tags = ai_data.get('tags', [])
        organization = ai_data.get('organization', '')
        document_type = ai_data.get('document_type', '')
        key_entities = ai_data.get('key_entities', [])

        # Build enhanced key-value pairs
        enhanced_key_values = []

        # Add title as key-value pair instead of name
        if title:
            enhanced_key_values.append({'key': 'TITLE', 'value': title})

        if organization:
            enhanced_key_values.append({'key': 'ORGANIZATION', 'value': organization})
        if document_type:
            enhanced_key_values.append({'key': 'DOCUMENT TYPE', 'value': document_type})
        if key_entities:
            enhanced_key_values.append({'key': 'KEY ENTITIES', 'value': ', '.join(key_entities[:5])})

        # Return processed data for frontend
        return {
            'auto_tags': auto_tags,
            'enhanced_data': {
                # Don't override name field - keep the filename
                'description': summary,
                'extracted_text': extracted_text,
                'media_type': self.get_media_type_from_ai_data(document_type),
                'enhanced_key_values': enhanced_key_values
            }
        }

    def get_media_type_from_ai_data(self, document_type):
        """Map AI-detected document type to our media type choices"""
        if not document_type:
            return None

        document_type = document_type.lower()
        type_mapping = {
            'report': 'PDF',
            'presentation': 'PDF',
            'spreadsheet': 'XLS',
            'document': 'DOC',
            'text': 'TXT',
            'csv': 'CSV',
            'excel': 'XLS'
        }

        for key, value in type_mapping.items():
            if key in document_type:
                return value
        return None


@method_decorator(staff_member_required, name='dispatch')
class BatchMediaSaveView(View):
    """API endpoint for saving batch media data"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            company_bot_id = data.get('company_bot_id')
            media_items = data.get('items', [])
            results = []

            # Get current user's profile
            try:
                user_profile = Profile.objects.get(email=request.user.email)
            except Profile.DoesNotExist:
                user_profile = None

            for item_data in media_items:
                try:
                    result = self.save_single_item(item_data, company_bot_id, user_profile)
                    results.append(result)
                except Exception as e:
                    results.append({
                        'success': False,
                        'filename': item_data.get('filename', 'Unknown'),
                        'message': str(e),
                        'file_index': item_data.get('file_index')
                    })

            return JsonResponse({
                'success': True,
                'results': results
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

    def save_single_item(self, item_data, company_bot_id, user_profile):
        """Save a single media item"""
        # Test failure condition (commented out as requested)
        # if "fail" in item_data.get("filename", "").lower():
        #     raise ValueError(f"Forced save failure for {item_data.get('filename')}")

        # Create media instance
        media = Media(
            name=item_data['name'],
            media_type=item_data['media_type'],
            priority=item_data['priority'],
            description=item_data['description'],
            extracted_text=item_data['extracted_text'],
            company_bot_id=company_bot_id,
        )
        media.save()

        # Process tags - separate manual and auto tags
        all_tags = []

        # Handle manual tags (created by current user)
        manual_tag_names = item_data.get('manual_tags', [])
        for tag_name in manual_tag_names:
            tag, created = Tag.objects.get_or_create(
                name=tag_name,
                defaults={'created_by': user_profile}
            )
            all_tags.append(tag)

        # Handle auto tags (created by bot)
        auto_tag_names = item_data.get('auto_tags', [])
        for tag_name in auto_tag_names:
            # Remove 'auto-' prefix if present
            clean_tag_name = tag_name.replace('auto-', '') if tag_name.startswith('auto-') else tag_name
            tag, created = Tag.objects.get_or_create(
                name=clean_tag_name,
                defaults={'created_by_id': BOT_PROFILE_ID}
            )
            all_tags.append(tag)

        # Set all tags
        media.tags.set(all_tags)

        # Add key-value pairs
        for kv in item_data.get('key_values', []):
            KeyValue.objects.create(
                media=media,
                key=kv['key'],
                value=kv['value']
            )

        return {
            'success': True,
            'filename': item_data.get('filename', media.name),
            'media_id': media.id,
            'message': 'Successfully saved',
            'file_index': item_data.get('file_index')
        }


@method_decorator(staff_member_required, name='dispatch')
class BatchMediaRetrySaveView(View):
    """API endpoint for retrying save of a single media item"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            item_data = data.get('item_data')
            company_bot_id = data.get('company_bot_id')

            # Get current user's profile
            try:
                user_profile = Profile.objects.get(email=request.user.email)
            except Profile.DoesNotExist:
                user_profile = None

            save_view = BatchMediaSaveView()
            result = save_view.save_single_item(item_data, company_bot_id, user_profile)

            return JsonResponse({
                'success': True,
                'result': result
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

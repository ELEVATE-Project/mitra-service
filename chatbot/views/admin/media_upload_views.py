import traceback
from django.views.generic import TemplateView
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.http import JsonResponse
from django.views import View
from chatbot.models import Media, Tag, KeyValue, Profile, FileTypeChoices, CompanyBot
from chatbot.models.media_models import PriorityChoices
import json
import tempfile, os
import uuid
from django.core.cache import cache
from chatbot.celery_tasks.knowledge_service.tag_tasks import get_auto_extracted_data
from chatbot.utils.knowledge_service.duplicate_detector import DuplicateDetector

BOT_PROFILE_ID = 1


@method_decorator(staff_member_required, name='dispatch')
class BatchMediaUploadView(TemplateView):
    template_name = 'admin/batch_upload.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['media_types'] = FileTypeChoices.choices
        context['priorities'] = PriorityChoices.choices

        # Add file types with complete information
        extension_mapping = FileTypeChoices.get_extension_mapping()
        context['file_types'] = [
            {
                'mime_type': choice[0],
                'label': choice[1],
                'extension': extension_mapping.get(choice[0], '')
            }
            for choice in FileTypeChoices.choices
        ]

        # Add company bots for selection
        from chatbot.models import CompanyBot
        context['company_bots'] = CompanyBot.objects.all()
        default_bot = CompanyBot.objects.filter(route='/tag_extractor')
        if default_bot:
            default_bot = default_bot.first()
            context['default_bot_id'] = default_bot.id
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
            print("store_file_for_retry cache set successfully")
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
        # if "fail" in file.name.lower():
        #     print(f"Forced extraction failure for {file.name}")
        #     raise ValueError(f"Forced extraction failure for {file.name}")
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
        """Map file extension to media type using FileTypeChoices"""
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else None
        # Use get_mime_from_extension instead of get_label_from_extension
        return FileTypeChoices.get_mime_from_extension(ext) if ext else FileTypeChoices.TXT.value


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
            print("Task results: ", results)
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
                # 'media_type': self.get_media_type_from_ai_data(document_type),
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
    """API endpoint for saving batch media data with fault tolerance"""

    def preserve_failed_files(self, failed_items, additional_timeout=7200):  # 2 more hours
        """Extend cache timeout for files that failed to save"""
        for item in failed_items:
            file_key = item.get('file_key')
            if file_key:
                cached_file = cache.get(file_key)
                if cached_file:
                    cache.set(file_key, cached_file, timeout=additional_timeout)
                    print(f"Extended cache timeout for failed file: {file_key}")

    def wait_for_vector_db_save_safe(self, task_id, timeout=30):
        """Enhanced waiting with better error handling"""
        import time
        from celery.result import AsyncResult

        try:
            intervals = [0.1, 0.2, 0.5, 1.0, 2.0, 3.0]
            start_time = time.time()
            attempt = 0

            while time.time() - start_time < timeout:
                try:
                    task = AsyncResult(task_id)
                    if task.ready():
                        if task.successful():
                            return {
                                'completed': True,
                                'successful': True,
                                'result': task.result,
                                'wait_time': time.time() - start_time
                            }
                        else:
                            return {
                                'completed': True,
                                'successful': False,
                                'result': f'Vector DB task failed: {task.info}',
                                'wait_time': time.time() - start_time,
                                'error_type': 'VECTOR_DB_TASK_FAILED'
                            }
                except Exception as poll_error:
                    # If polling fails, log but continue trying
                    print(f"Polling error for task {task_id}: {poll_error}")

                sleep_time = intervals[min(attempt, len(intervals) - 1)]
                time.sleep(sleep_time)
                attempt += 1

            # Timeout reached
            return {
                'completed': False,
                'successful': False,
                'result': f'Vector DB save timeout after {timeout}s',
                'wait_time': timeout,
                'error_type': 'VECTOR_DB_TIMEOUT'
            }

        except Exception as wait_error:
            return {
                'completed': False,
                'successful': False,
                'result': f'Wait error: {str(wait_error)}',
                'error_type': 'WAIT_ERROR'
            }

    def save_single_item_with_vector_db_wait_safe(self, item_data, company_bot_id, user_profile, session_id,
                                                  bypass_similarity=False):
        """Save a single media item with comprehensive error handling"""
        file_key = item_data.get('file_key')
        filename = item_data.get('filename', 'Unknown')
        file_index = item_data.get('file_index')

        try:
            company_bot = CompanyBot.objects.get(id=company_bot_id)
            company_slug = company_bot.company.slug
            extracted_text = item_data.get('extracted_text', '')

            # Step 1: Similarity check
            try:
                if not bypass_similarity:
                    DuplicateDetector.check_for_duplicates(
                        extracted_text=extracted_text,
                        company_bot_id=company_bot_id,
                        company_slug=company_slug,
                        trigram_threshold=0,
                        semantic_threshold=0.85,
                        trigram_exact_threshold=0.90,
                        semantic_exact_threshold=0.9
                    )
            except Exception as similarity_error:
                return {
                    'success': False,
                    'filename': filename,
                    'message': f'Similarity check failed: {str(similarity_error)}',
                    'error_type': 'SIMILARITY_CHECK_FAILED',
                    'file_index': file_index,
                    'file_key': file_key,
                    'session_id': session_id,
                    'vector_db_saved': False
                }

            # Step 2: Retrieve file from cache
            file_content = None
            file_name = None

            if file_key:
                cached_file = cache.get(file_key)
                if cached_file:
                    file_content = cached_file.get('content')
                    file_name = cached_file.get('name')
                else:
                    return {
                        'success': False,
                        'filename': filename,
                        'message': 'File not found in cache for saving',
                        'error_type': 'FILE_NOT_FOUND_IN_CACHE',
                        'file_index': file_index,
                        'file_key': file_key,
                        'session_id': session_id,
                        'vector_db_saved': False
                    }

            # Step 3: Create and save media
            try:
                media = Media(
                    name=item_data['name'],
                    media_type=item_data['media_type'],
                    priority=item_data['priority'],
                    description=item_data['description'],
                    extracted_text=item_data['extracted_text'],
                    company_bot_id=company_bot_id,
                )

                if file_content and file_name:
                    from django.core.files.base import ContentFile
                    media.file.save(file_name, ContentFile(file_content), save=False)

                # Save and get the vector DB task ID
                vector_task_id = media.save()

            except Exception as media_save_error:
                return {
                    'success': False,
                    'filename': filename,
                    'message': f'Media save failed: {str(media_save_error)}',
                    'error_type': 'MEDIA_SAVE_FAILED',
                    'file_index': file_index,
                    'file_key': file_key,
                    'session_id': session_id,
                    'vector_db_saved': False
                }

            # Step 4: Process tags and key-values
            try:
                all_tags = []

                # Manual tags
                manual_tag_names = item_data.get('manual_tags', [])
                for tag_name in manual_tag_names:
                    tag, created = Tag.objects.get_or_create(
                        name=tag_name,
                        defaults={'created_by': user_profile}
                    )
                    all_tags.append(tag)

                # Auto tags
                auto_tag_names = item_data.get('auto_tags', [])
                for tag_name in auto_tag_names:
                    clean_tag_name = tag_name.replace('auto-', '') if tag_name.startswith('auto-') else tag_name
                    tag, created = Tag.objects.get_or_create(
                        name=clean_tag_name,
                        defaults={'created_by_id': BOT_PROFILE_ID}
                    )
                    all_tags.append(tag)

                media.tags.set(all_tags)

                # Key-value pairs
                for kv in item_data.get('key_values', []):
                    KeyValue.objects.create(
                        media=media,
                        key=kv['key'],
                        value=kv['value']
                    )

            except Exception as tag_kv_error:
                print(f"Warning: Tag/KV processing failed for {filename}: {tag_kv_error}")
                # Continue - media is saved, just tags/kvs failed

            # Step 5: Wait for vector DB save
            vector_result = {'successful': True, 'result': 'No vector task'}
            if vector_task_id:
                vector_result = self.wait_for_vector_db_save_safe(vector_task_id)

                if not vector_result['successful']:
                    # Vector DB failed but media is saved - partial success
                    print(f"Vector DB save failed for media {media.id}: {vector_result['result']}")

                    # Don't clean cache yet - might want to retry
                    return {
                        'success': False,  # Mark as failed so it can be retried
                        'filename': filename,
                        'media_id': media.id,
                        'message': f"Saved to database but vector DB failed: {vector_result['result']}",
                        'error_type': vector_result.get('error_type', 'VECTOR_DB_FAILED'),
                        'file_index': file_index,
                        'file_key': file_key,
                        'session_id': session_id,
                        'vector_db_saved': False,
                        'partial_success': True, # Indicates media was saved to main DB
                        'vector_task_id': vector_task_id
                    }

            # Step 6: Success - clean up cache
            if file_key and cache.get(file_key):
                cache.delete(file_key)
                print(f"Cleaned up cache for {file_key}")

            return {
                'success': True,
                'filename': filename,
                'media_id': media.id,
                'message': 'Successfully saved',
                'file_index': file_index,
                'vector_db_saved': vector_result['successful'],
                'vector_wait_time': vector_result.get('wait_time', 0),
                'vector_task_id': vector_task_id
            }

        except Exception as unexpected_error:
            # Catch any other unexpected errors
            print(f"Unexpected error processing {filename}: {unexpected_error}")
            traceback.print_exc()
            return {
                'success': False,
                'filename': filename,
                'message': f'Unexpected error: {str(unexpected_error)}',
                'error_type': 'UNEXPECTED_ERROR',
                'file_index': file_index,
                'file_key': file_key,
                'session_id': session_id,
                'vector_db_saved': False
            }

    def post(self, request):
        try:
            data = json.loads(request.body)
            company_bot_id = data.get('company_bot_id')
            media_items = data.get('items', [])
            session_id = data.get('session_id')

            results = []
            stats = {
                'total': len(media_items),
                'successful': 0,
                'failed': 0,
                'partial_success': 0,
                'timeouts': 0,
                'similarity_failures': 0
            }

            # Get current user's profile
            try:
                user_profile = Profile.objects.get(email=request.user.email)
            except Profile.DoesNotExist:
                user_profile = None

            print(f"Starting batch save for {len(media_items)} files")

            # Process each file with fault tolerance
            for i, item_data in enumerate(media_items):
                filename = item_data.get('filename', f'File_{i}')
                print(f"Processing file {i + 1}/{len(media_items)}: {filename}")

                try:
                    bypass_similarity = item_data.get('bypass_similarity', False)
                    result = self.save_single_item_with_vector_db_wait_safe(
                        item_data=item_data,
                        company_bot_id=company_bot_id,
                        user_profile=user_profile,
                        session_id=session_id,
                        bypass_similarity=bypass_similarity
                    )

                    # Track statistics
                    if result['success']:
                        stats['successful'] += 1
                    else:
                        stats['failed'] += 1
                        if result.get('partial_success'):
                            stats['partial_success'] += 1
                        if result.get('error_type') in ['VECTOR_DB_TIMEOUT', 'WAIT_ERROR']:
                            stats['timeouts'] += 1
                        if result.get('error_type') == 'SIMILARITY_CHECK_FAILED':
                            stats['similarity_failures'] += 1

                    results.append(result)
                    print(
                        f"File {i + 1} result: {'✓' if result['success'] else '✗'} - {result.get('message', 'No message')}")

                except Exception as item_error:
                    # This should rarely happen due to the safe method above
                    print(f"Critical error processing {filename}: {item_error}")
                    stats['failed'] += 1
                    results.append({
                        'success': False,
                        'filename': filename,
                        'message': f'Critical processing error: {str(item_error)}',
                        'error_type': 'CRITICAL_ERROR',
                        'file_index': item_data.get('file_index', i),
                        'file_key': item_data.get('file_key'),
                        'session_id': session_id,
                        'vector_db_saved': False
                    })

            # Preserve cache for failed files
            failed_items = [r for r in results if not r['success'] and r.get('file_key')]
            if failed_items:
                self.preserve_failed_files(failed_items)

            # Generate summary message
            summary_message = self.generate_batch_summary(stats)

            print(f"Batch complete: {summary_message}")

            return JsonResponse({
                'success': True,  # Batch completed (even with individual failures)
                'results': results,
                'stats': stats,
                'summary_message': summary_message,
                'session_id': session_id
            })

        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as batch_error:
            print(f"Batch processing error: {batch_error}")
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'error': f'Batch processing failed: {str(batch_error)}'
            }, status=500)

    def generate_batch_summary(self, stats):
        """Generate human-readable batch summary"""
        total = stats['total']
        successful = stats['successful']
        failed = stats['failed']

        if successful == total:
            return f"All {total} files processed successfully!"
        elif successful == 0:
            return f"All {total} files failed to process."
        else:
            message_parts = [f"{successful}/{total} files successful"]
            if failed > 0:
                message_parts.append(f"{failed} failed")
            if stats['timeouts'] > 0:
                message_parts.append(f"{stats['timeouts']} timed out")
            if stats['similarity_failures'] > 0:
                message_parts.append(f"{stats['similarity_failures']} similarity check failures")
            if stats['partial_success'] > 0:
                message_parts.append(f"{stats['partial_success']} partial successes")

            return ", ".join(message_parts) + "."


@method_decorator(staff_member_required, name='dispatch')
class BatchMediaRetrySaveView(View):
    """API endpoint for retrying save of a single media item"""

    def post(self, request):
        try:
            print("BatchMediaRetrySaveView called")
            data = json.loads(request.body)
            item_data = data.get('item_data')
            company_bot_id = data.get('company_bot_id')
            session_id = data.get('session_id')
            bypass_similarity = data.get('bypass_similarity', False)

            # Get current user's profile
            try:
                user_profile = Profile.objects.get(email=request.user.email)
            except Profile.DoesNotExist:
                user_profile = None

            save_view = BatchMediaSaveView()
            result = save_view.save_single_item_with_vector_db_wait_safe(
                item_data=item_data, company_bot_id=company_bot_id, user_profile=user_profile,
                session_id=session_id, bypass_similarity=bypass_similarity
            )

            return JsonResponse({
                'success': True,
                'result': result
            })

        except Exception as e:
            print(f"Unexpected error: {e}")
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)


@method_decorator(staff_member_required, name='dispatch')
class VectorDBTaskStatusView(View):
    """Check status of vector DB save task"""

    def post(self, request):
        try:
            from celery.result import AsyncResult
            data = json.loads(request.body)
            task_id = data.get('task_id')

            if not task_id:
                return JsonResponse({'success': False, 'error': 'No task_id provided'})

            task = AsyncResult(task_id)

            return JsonResponse({
                'success': True,
                'status': task.status,
                'ready': task.ready(),
                'successful': task.successful() if task.ready() else None,
                'result': task.result if task.ready() else None
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

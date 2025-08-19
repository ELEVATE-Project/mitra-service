from django.views.generic import TemplateView
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.http import JsonResponse
from django.views import View
from chatbot.models import Media, Tag, KeyValue, Profile
from chatbot.models.media_models import PriorityChoices, MediaTypeChoices
import json
import tempfile, os

from chatbot.utils.knowledge_service.auto_tag_utils import get_auto_tags

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
            print("request.FILES:", request.FILES)
            print("request.POST:", request.POST)
            files = request.FILES.getlist('files')
            company_bot_id = request.POST.get('company_bot_id')
            extracted_data = []

            company_bot = None
            if company_bot_id:
                try:
                    from chatbot.models import CompanyBot
                    company_bot = CompanyBot.objects.get(id=company_bot_id)
                except CompanyBot.DoesNotExist:
                    pass

            for file in files:
                data = self.extract_file_data(file=file, company_bot=company_bot)
                extracted_data.append(data)

            return JsonResponse({
                'success': True,
                'data': extracted_data
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

    def extract_file_data(self, file, company_bot):
        """Extract data from file and start async tag extraction"""
        file_extension = file.name.rsplit('.', 1)[-1].lower() if '.' in file.name else None

        # Save file temporarily and start Celery task
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_extension}") as tmp:
            for chunk in file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        # Start async task
        task = get_auto_tags.delay(
            file_path=tmp_path,
            company_bot_id=company_bot.id if company_bot else None,
            file_extension=file_extension
        )

        return {
            'filename': file.name,
            'name': file.name.rsplit('.', 1)[0],
            'media_type': self.get_media_type(file.name),
            'description': f'Extracted from {file.name}',
            'extracted_text': 'Sample extracted text...',
            'priority': 'P1',
            'tags': [],  # Start with empty tags
            'auto_tag_task_id': task.id,  # Store task ID for polling
            'auto_tags_ready': False,  # Flag to track completion
            'key_values': [
                {'key': 'TITLE OF THE PROJECT', 'value': 'Sample Project'},
                {'key': 'TARGET STAKEHOLDER', 'value': 'Students'},
            ]
        }

    def get_media_type(self, filename):
        ext = filename.rsplit('.', 1)[-1].lower()
        print("Extracted media type: ", ext)
        type_map = {
            'pdf': 'PDF',
            'doc': 'DOC',
            'docx': 'DOC',
            'txt': 'TXT',
            'csv': 'CSV',
            'xls': 'XLS',
            'xlsx': 'XLS'
        }
        return type_map.get(ext, 'TXT')


@method_decorator(staff_member_required, name='dispatch')
class BatchMediaTaskStatusView(View):
    """API endpoint for checking Celery task status"""

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
                        results[task_id] = {
                            'status': 'SUCCESS',
                            'result': task.result
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
                    # Create media instance
                    media = Media(
                        name=item_data['name'],
                        media_type=item_data['media_type'],
                        priority=item_data['priority'],
                        description=item_data['description'],
                        extracted_text=item_data['extracted_text'],
                        company_bot_id=company_bot_id,
                        # Handle file upload separately
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

                    results.append({
                        'success': True,
                        'filename': item_data.get('filename', media.name),
                        'media_id': media.id,
                        'message': 'Successfully saved'
                    })

                except Exception as e:
                    results.append({
                        'success': False,
                        'filename': item_data.get('filename', 'Unknown'),
                        'message': str(e)
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
    
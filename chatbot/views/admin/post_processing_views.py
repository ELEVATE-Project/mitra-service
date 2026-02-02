from django.views.generic import TemplateView
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.http import JsonResponse


@method_decorator(staff_member_required, name='dispatch')
class PostProcessingView(TemplateView):
    """Post Processing view for Story model admin"""
    template_name = 'admin/post_processing/post_processing.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['model_name'] = 'Story'
        context['processing_types'] = [
            {'value': 'unique_challenges', 'label': 'Unique Challenges'},
        ]
        return context

    def post(self, request, *args, **kwargs):
        """Handle POST request for running the processing script"""
        try:
            processing_type = request.POST.get('processing_type', '')
            max_workers = request.POST.get('max_workers', 4)
            batch_size = request.POST.get('batch_size', 100)
            date_from = request.POST.get('date_from', '').strip()
            date_till = request.POST.get('date_till', '').strip()
            input_file = request.FILES.get('input_file', None)

            # Validate at least one input source
            has_file = input_file is not None
            has_date_range = bool(date_from and date_till)
            
            if not has_file and not has_date_range:
                return JsonResponse({
                    'success': False,
                    'error': 'Either input file or date range is required'
                })

            # Validate numeric inputs
            try:
                max_workers = int(max_workers)
                batch_size = int(batch_size)
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid numeric values for max_workers or batch_size'
                })

            # Build configuration
            config = {
                'processing_type': processing_type,
                'max_workers': max_workers,
                'batch_size': batch_size,
                'date_from': date_from,
                'date_till': date_till,
                'input_file': input_file.name if input_file else None,
                'has_file': has_file,
                'has_date_range': has_date_range
            }

            self._print_processing_output(config)

            return JsonResponse({
                'success': True,
                'message': 'Processing initiated! Check the backend terminal for output.'
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })


    def _print_processing_output(self, config):
        processing_type = config.get('processing_type', '')
        
        print("\n" + "=" * 60)
        print("🚀 POST PROCESSING")
        print("=" * 60)
        
        if processing_type == 'unique_challenges':
            print(f"\n📋 Configuration:")
            print(f"   Type: {processing_type}")
            print(f"   MAX_WORKERS: {config.get('max_workers')}")
            print(f"   BATCH_SIZE: {config.get('batch_size')}")
            
            if config.get('has_file'):
                print(f"   Input File: {config.get('input_file')}")
            
            if config.get('has_date_range'):
                print(f"   Date Range: {config.get('date_from')} to {config.get('date_till')}")
           
            print(f"\n✅ Processing complete!")
        else:
            print(f"❓ Unknown processing type: {processing_type}")
        
        print("=" * 60 + "\n")

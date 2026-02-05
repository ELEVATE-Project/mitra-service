from django.views.generic import TemplateView
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.http import JsonResponse
import json
import os
from chatbot.utils.shiksha_chaupal.iterative_challenge_processor import run_iterative_challenge_filtering


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
            max_iterations = request.POST.get('max_iterations', 10)
            filter_threshold = request.POST.get('filter_threshold', 10)
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
                max_iterations = int(max_iterations)
                filter_threshold = float(filter_threshold)
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid numeric values for configuration parameters'
                })

            # Build configuration
            config = {
                'processing_type': processing_type,
                'max_workers': max_workers,
                'batch_size': batch_size,
                'max_iterations': max_iterations,
                'filter_threshold': filter_threshold,
                'date_from': date_from,
                'date_till': date_till,
                'input_file': input_file.name if input_file else None,
                'has_file': has_file,
                'has_date_range': has_date_range
            }

            # Run the appropriate processing
            if processing_type == 'unique_challenges':
                result = self._run_unique_challenges_processing(config, input_file)
                return JsonResponse(result)
            else:
                self._print_processing_output(config)
                return JsonResponse({
                    'success': True,
                    'message': 'Processing initiated!'
                })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'error': str(e)
            })

    def _run_unique_challenges_processing(self, config, input_file):
        """Run the iterative unique challenges processing."""
        
        # Prepare input data
        input_data = None
        input_file_path = None
        
        if config.get('has_file') and input_file:
            # Read the uploaded file
            try:
                content = input_file.read().decode('utf-8')
                input_data = json.loads(content)
                
                # Normalize the data
                if isinstance(input_data, list):
                    normalized = []
                    for item in input_data:
                        if isinstance(item, str) and item.strip():
                            normalized.append(item.strip())
                        elif isinstance(item, dict) and 'challenge' in item:
                            val = item.get('challenge')
                            if isinstance(val, str) and val.strip():
                                normalized.append(val.strip())
                    input_data = normalized
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Error reading input file: {str(e)}'
                }
        
        # Run iterative processing
        result = run_iterative_challenge_filtering(
            input_data=input_data,
            input_file=input_file_path,
            date_from=config.get('date_from') if config.get('has_date_range') else None,
            date_till=config.get('date_till') if config.get('has_date_range') else None,
            max_iterations=config.get('max_iterations', 10),
            filter_threshold=config.get('filter_threshold', 10.0),
            batch_size=config.get('batch_size', 100),
            max_workers=config.get('max_workers', 4)
        )
        
        if result.get('success'):
            return {
                'success': True,
                'message': result.get('message', 'Processing completed successfully'),
                'output_file': result.get('output_file'),
                'iterations': result.get('iterations_completed'),
                'final_count': len(result.get('final_challenges', [])),
                'stats': result.get('stats', [])
            }
        else:
            return {
                'success': False,
                'error': result.get('message', 'Processing failed')
            }

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
            print(f"   MAX_ITERATIONS: {config.get('max_iterations')}")
            print(f"   FILTER_THRESHOLD: {config.get('filter_threshold')}%")
            
            if config.get('has_file'):
                print(f"   Input File: {config.get('input_file')}")
            
            if config.get('has_date_range'):
                print(f"   Date Range: {config.get('date_from')} to {config.get('date_till')}")
           
            print(f"\n✅ Processing complete!")
        else:
            print(f"❓ Unknown processing type: {processing_type}")
        
        print("=" * 60 + "\n")

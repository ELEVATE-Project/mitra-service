from django.views.generic import TemplateView
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.http import JsonResponse
import json
import os
from chatbot.utils.shiksha_chaupal.iterative_challenge_processor import run_iterative_challenge_filtering
from chatbot.utils.admin_config.config import (
    get_all_processing_types,
    get_processing_type_by_value,
    ProcessingType
)


@method_decorator(staff_member_required, name='dispatch')
class PostProcessingView(TemplateView):
    """Post Processing view for Story model admin"""
    template_name = 'admin/post_processing/post_processing.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['model_name'] = 'Story'
        # Dynamically get all processing types from config
        context['processing_types'] = get_all_processing_types()
        return context

    def post(self, request, *args, **kwargs):
        """Handle POST request for running the processing script"""
        try:
            processing_type = request.POST.get('processing_type', '')
            
            # Get processing type enum and validate
            processing_type_enum = get_processing_type_by_value(processing_type)
            if not processing_type_enum:
                return JsonResponse({
                    'success': False,
                    'error': f'Unknown processing type: {processing_type}'
                })
            
            # Dynamically extract and validate fields based on config
            config = self._extract_form_data(request, processing_type_enum)
            
            # Check for validation errors
            if 'error' in config:
                return JsonResponse({
                    'success': False,
                    'error': config['error']
                })
            
            # Common fields: file upload and date range
            input_file = request.FILES.get('input_file', None)
            date_from = request.POST.get('date_from', '').strip()
            date_till = request.POST.get('date_till', '').strip()
            
            # Validate at least one input source
            has_file = input_file is not None
            has_date_range = bool(date_from and date_till)
            
            if not has_file and not has_date_range:
                return JsonResponse({
                    'success': False,
                    'error': 'Please provide either an input file or a date range to begin processing.'
                })
            
            # Add common fields to config
            config.update({
                'processing_type': processing_type,
                'date_from': date_from,
                'date_till': date_till,
                'input_file': input_file.name if input_file else None,
                'has_file': has_file,
                'has_date_range': has_date_range
            })

            # Run the appropriate processing using dynamic routing
            # Get the handler method name from config
            handler_method_name = processing_type_enum.handler_method
            handler_method = getattr(self, handler_method_name, None)
            
            if handler_method:
                result = handler_method(config, input_file)
                return JsonResponse(result)
            else:
                return JsonResponse({
                    'success': False,
                    'error': f'Handler method {handler_method_name} not found for {processing_type}'
                })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    def _extract_form_data(self, request, processing_type_enum):
        """
        Dynamically extract and validate form fields based on processing type config.
        """
        from chatbot.utils.admin_config.config import get_processing_type_config
        
        config_data = get_processing_type_config(processing_type_enum)
        field_definitions = config_data.get('fields', [])
        
        extracted_data = {}
        
        for field_def in field_definitions:
            field_name = field_def['name']
            field_type = field_def['type']
            default_value = field_def.get('default')
            
            # Get value from request
            raw_value = request.POST.get(field_name)
            
            # Use default if not provided
            if raw_value is None or raw_value == '':
                extracted_data[field_name] = default_value
                continue
            
            # Type conversion and validation
            try:
                if field_type == 'number':
                    # Check if it has step (float) or is integer
                    if 'step' in field_def and field_def['step'] != 1:
                        converted_value = float(raw_value)
                    else:
                        converted_value = int(raw_value)
                    
                    # Validate min/max
                    if 'min' in field_def and converted_value < field_def['min']:
                        return {'error': f"{field_def['label']} must be at least {field_def['min']}"}
                    if 'max' in field_def and converted_value > field_def['max']:
                        return {'error': f"{field_def['label']} must be at most {field_def['max']}"}
                    
                    extracted_data[field_name] = converted_value
                
                elif field_type == 'select':
                    # Validate choice is in allowed choices
                    valid_choices = [choice['value'] for choice in field_def.get('choices', [])]
                    if valid_choices and raw_value not in valid_choices:
                        return {'error': f"Invalid value for {field_def['label']}"}
                    extracted_data[field_name] = raw_value
                
                elif field_type == 'text':
                    extracted_data[field_name] = raw_value.strip()
                
                else:
                    # Default: store as-is
                    extracted_data[field_name] = raw_value
                    
            except (ValueError, TypeError) as e:
                return {'error': f"Invalid value for {field_def['label']}: {str(e)}"}
        
        return extracted_data

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
                    'error': f'Unable to read the uploaded file. Please ensure it is a valid JSON format.'
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
                'error': result.get('message', 'Processing could not be completed. Please check the logs or try again.')
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

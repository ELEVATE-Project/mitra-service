"""
Celery Tasks for Post Processing

This module contains Celery tasks for running post-processing operations asynchronously.
"""
import json
import traceback
from celery import shared_task
from typing import Dict, Any, Optional


@shared_task(bind=True)
def run_unique_challenges_task(self, config: Dict[str, Any], input_file_content: Optional[str] = None):
    """
    Celery task to run unique challenges processing asynchronously.
    
    Args:
        self: Task instance (automatically passed due to bind=True)
        config: Configuration dictionary with all processing parameters
        input_file_content: Optional JSON string content of uploaded file
    
    Returns:
        Dictionary with processing results
    """
    try:
        print(f"\n{'='*60}")
        print(f"🚀 CELERY TASK STARTED: run_unique_challenges_task")
        print(f"📋 Config received: {config}")
        
        # Update task state to show it has started
        self.update_state(
            state='PROCESSING',
            meta={'status': 'Starting unique challenges processing...', 'progress': 0}
        )
        
        from chatbot.utils.shiksha_chaupal.iterative_challenge_processor import run_iterative_challenge_filtering
        
        # Prepare input data
        input_data = None
        
        if input_file_content:
            try:
                # Parse the JSON content
                parsed_data = json.loads(input_file_content)
                
                # Normalize the data
                if isinstance(parsed_data, list):
                    if all(isinstance(item, dict) and 'challenge' in item for item in parsed_data):
                        input_data = [item['challenge'] for item in parsed_data]
                    else:
                        input_data = parsed_data
                else:
                    input_data = [parsed_data]
                    
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Unable to parse uploaded file content: {str(e)}'
                }
        
        # Update state before starting main processing
        self.update_state(
            state='PROCESSING',
            meta={'status': 'Running iterative challenge filtering...', 'progress': 10}
        )
        
        # Run iterative processing
        result = run_iterative_challenge_filtering(
            input_data=input_data,
            input_file=None,
            date_from=config.get('date_from') if config.get('has_date_range') else None,
            date_till=config.get('date_till') if config.get('has_date_range') else None,
            max_iterations=config.get('max_iterations', 10),
            filter_threshold=config.get('filter_threshold', 10.0),
            batch_size=config.get('batch_size', 100),
            max_workers=config.get('max_workers', 4)
        )
        
        # Format and return result
        if result.get('success'):
            return {
                'success': True,
                'status': 'completed',
                'message': result.get('message', 'Processing completed successfully'),
                'output_file': result.get('output_file'),
                'iterations': result.get('iterations_completed'),
                'final_count': len(result.get('final_challenges', [])),
                'stats': result.get('stats', [])
            }
        else:
            return {
                'success': False,
                'status': 'failed',
                'error': result.get('message', 'Processing failed')
            }
            
    except Exception as e:
        # Log error and return failure result
        print(f"❌ Error in run_unique_challenges_task: {str(e)}")
        traceback.print_exc()
        
        return {
            'success': False,
            'status': 'failed',
            'error': f'Task execution error: {str(e)}'
        }

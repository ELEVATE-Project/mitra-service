"""
Iterative Challenge Processor Utility

This utility runs the unique challenges filtering script iteratively until
the filtering threshold is met or maximum iterations are reached.
"""
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from chatbot.scripts.guest_discussion.post_processing.challenges_script import (
    run_unique_challenge_processing,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_WORKERS
)


# -------------- CONFIG ------------------
DEFAULT_MAX_ITERATIONS = 10
DEFAULT_FILTER_THRESHOLD = 10.0  # Stop if less than 10% items were removed
OUTPUT_DIR = 'chatbot/scripts/challenges/iterative_output'


class IterativeChallengeProcessor:
    """
    Processor that runs unique challenge filtering iteratively until
    the output stabilizes.
    """
    
    def __init__(
        self,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        filter_threshold: float = DEFAULT_FILTER_THRESHOLD,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_workers: int = DEFAULT_MAX_WORKERS,
        output_dir: str = OUTPUT_DIR
    ):
        self.max_iterations = max_iterations
        self.filter_threshold = filter_threshold
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.output_dir = output_dir
        
        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)
        
    def calculate_removal_percentage(self, input_count: int, output_count: int) -> float:
        """
        Calculate the percentage of items removed.
        """
        if input_count == 0:
            return 0.0
        
        removed = input_count - output_count
        percentage = (removed / input_count) * 100
        return round(percentage, 2)
    
    def should_continue_filtering(self, input_count: int, output_count: int) -> bool:
        """
        Determine if filtering should continue based on removal percentage.
        """
        removal_percentage = self.calculate_removal_percentage(input_count, output_count)
        
        # If removal percentage is greater than or equal to threshold, continue filtering
        # If it's less than threshold, we've reached satisfactory uniqueness
        return removal_percentage >= self.filter_threshold
    
    def run_iterative_processing(
        self,
        input_data: Optional[List[str]] = None,
        input_file: Optional[str] = None,
        date_from: Optional[str] = None,
        date_till: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run iterative challenge processing until threshold is met or max iterations reached.
        """
        result = {
            'success': False,
            'final_challenges': [],
            'iterations_completed': 0,
            'stats': [],
            'output_file': None,
            'message': ''
        }
        
        try:
            # Load initial data
            current_data = self._load_initial_data(input_data, input_file, date_from, date_till)
            
            if not current_data:
                result['message'] = 'No input data provided or loaded'
                return result
            
            initial_count = len(current_data)
            print(f"\n{'='*60}")
            print(f"🚀 ITERATIVE CHALLENGE PROCESSOR")
            print(f"{'='*60}")
            print(f"📊 Initial challenges count: {initial_count}")
            print(f"⚙️  Max iterations: {self.max_iterations}")
            print(f"⚙️  Filter threshold: {self.filter_threshold}%")
            print(f"⚙️  Batch size: {self.batch_size}")
            print(f"⚙️  Max workers: {self.max_workers}")
            print(f"{'='*60}\n")
            
            iteration = 0
            
            while iteration < self.max_iterations:
                iteration += 1
                input_count = len(current_data)
                
                print(f"\n{'─'*50}")
                print(f"🔄 ITERATION {iteration}/{self.max_iterations}")
                print(f"{'─'*50}")
                print(f"   Input count: {input_count}")
                
                # Skip if too few items
                if input_count < 2:
                    print(f"   ⚠️ Too few items to process, stopping.")
                    break
                
                # Run the challenge processing
                _, flat_challenges = run_unique_challenge_processing(
                    input_data=current_data,
                    batch_size=self.batch_size,
                    max_workers=self.max_workers,
                    save_to_file=False
                )
                
                output_count = len(flat_challenges)
                removal_percentage = self.calculate_removal_percentage(input_count, output_count)
                
                # Record stats
                iteration_stats = {
                    'iteration': iteration,
                    'input_count': input_count,
                    'output_count': output_count,
                    'removed_count': input_count - output_count,
                    'removal_percentage': removal_percentage
                }
                result['stats'].append(iteration_stats)
                
                print(f"   Output count: {output_count}")
                print(f"   Removed: {input_count - output_count} ({removal_percentage}%)")
                
                # Check if we should stop
                if not self.should_continue_filtering(input_count, output_count):
                    print(f"\n   ✅ Threshold reached! Removal ({removal_percentage}%) < threshold ({self.filter_threshold}%)")
                    current_data = flat_challenges
                    break
                
                # Prepare for next iteration
                current_data = flat_challenges
                print(f"   ➡️ Continuing to next iteration...")
            
            # Save final output
            result['final_challenges'] = current_data
            result['iterations_completed'] = iteration
            result['success'] = True
            
            # Generate output file
            output_file = self._save_output(current_data, initial_count)
            result['output_file'] = output_file
            
            # Generate summary
            total_removed = initial_count - len(current_data)
            total_removal_pct = self.calculate_removal_percentage(initial_count, len(current_data))
            
            print(f"\n{'='*60}")
            print(f"✅ PROCESSING COMPLETE")
            print(f"{'='*60}")
            print(f"📊 Initial count: {initial_count}")
            print(f"📊 Final count: {len(current_data)}")
            print(f"📊 Total removed: {total_removed} ({total_removal_pct}%)")
            print(f"📊 Iterations: {iteration}")
            print(f"📁 Output file: {output_file}")
            print(f"{'='*60}\n")
            
            result['message'] = f'Processing complete. {total_removed} duplicates removed ({total_removal_pct}%) in {iteration} iterations.'
            
        except Exception as e:
            result['message'] = f'Error during processing: {str(e)}'
            print(f"\n❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()
        
        return result
    
    def _load_initial_data(
        self,
        input_data: Optional[List[str]],
        input_file: Optional[str],
        date_from: Optional[str],
        date_till: Optional[str]
    ) -> List[str]:
        """
        Load initial data from provided source.
        """
        if input_data:
            return self._normalize_challenges(input_data)
        
        if input_file:
            with open(input_file, 'r') as f:
                data = json.load(f)
            return self._normalize_challenges(data)
        
        if date_from and date_till:
            return self._fetch_challenges_from_db(date_from, date_till)
        
        return []
    
    def _normalize_challenges(self, data: Any) -> List[str]:
        """
        Normalize challenge data to a flat list of strings.
        """
        if not isinstance(data, list):
            return []
        
        challenges = []
        for item in data:
            if isinstance(item, str) and item.strip():
                challenges.append(item.strip())
            elif isinstance(item, dict) and 'challenge' in item:
                val = item.get('challenge')
                if isinstance(val, str) and val.strip():
                    challenges.append(val.strip())
        
        return challenges
    
    def _fetch_challenges_from_db(self, date_from: str, date_till: str) -> List[str]:
        """
        Fetch challenges from database based on date range.
        """
        from datetime import datetime
        from chatbot.models import Story
        
        try:
            # Parse dates (DD-MM-YYYY format)
            start_date = datetime.strptime(date_from, '%d-%m-%Y')
            end_date = datetime.strptime(date_till, '%d-%m-%Y')
            
            # Make end_date inclusive by setting to end of day
            end_date = end_date.replace(hour=23, minute=59, second=59)
            
            # Query stories in date range
            stories = Story.objects.filter(
                created_at__gte=start_date,
                created_at__lte=end_date
            ).values_list('other_params', flat=True)
            
            challenges = []
            for other_params in stories:
                if other_params and isinstance(other_params, dict):
                    # Extract challenge from other_params
                    challenge = other_params.get('challenge') or other_params.get('challenges')
                    if challenge:
                        if isinstance(challenge, str):
                            challenges.append(challenge.strip())
                        elif isinstance(challenge, list):
                            for c in challenge:
                                if isinstance(c, str) and c.strip():
                                    challenges.append(c.strip())
            
            print(f"📥 Fetched {len(challenges)} challenges from database")
            return challenges
            
        except Exception as e:
            print(f"❌ Error fetching from database: {e}")
            return []
    
    def _save_output(self, challenges: List[str], initial_count: int) -> str:
        """
        Save the final output to a file.
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'unique_challenges_{timestamp}.json'
        filepath = os.path.join(self.output_dir, filename)
        
        output_data = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'initial_count': initial_count,
                'final_count': len(challenges),
                'removed_count': initial_count - len(challenges),
                'filter_threshold': self.filter_threshold,
                'max_iterations': self.max_iterations
            },
            'challenges': challenges
        }
        
        with open(filepath, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        return filepath


def run_iterative_challenge_filtering(
    input_data: Optional[List[str]] = None,
    input_file: Optional[str] = None,
    date_from: Optional[str] = None,
    date_till: Optional[str] = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    filter_threshold: float = DEFAULT_FILTER_THRESHOLD,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_workers: int = DEFAULT_MAX_WORKERS,
    output_dir: str = OUTPUT_DIR
) -> Dict[str, Any]:
    
    processor = IterativeChallengeProcessor(
        max_iterations=max_iterations,
        filter_threshold=filter_threshold,
        batch_size=batch_size,
        max_workers=max_workers,
        output_dir=output_dir
    )
    
    return processor.run_iterative_processing(
        input_data=input_data,
        input_file=input_file,
        date_from=date_from,
        date_till=date_till
    )

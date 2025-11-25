"""
Sync Media to Vector DB Script

This script processes all media files from the database and upserts them into the vector database.
It can process all media or filter by company/bot.

Usage:
    # Process all media
    python manage.py shell < chatbot/scripts/sync_media_to_vector_db.py
    
    # Or run directly with filters
    python chatbot/scripts/sync_media_to_vector_db.py --company-slug your-company --bot-id 1
    
    # Dry run to test
    python chatbot/scripts/sync_media_to_vector_db.py --dry-run
    
    # Process specific media IDs
    python chatbot/scripts/sync_media_to_vector_db.py --media-ids 1,2,3
"""

import os
import sys
import argparse
import traceback
from pathlib import Path
from typing import List, Dict, Any, Optional
import time

# Django setup
import django
if __name__ == '__main__':
    project_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(project_root))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shikshalokam_mohini.settings')
    django.setup()

from django.db.models import Q
from chatbot.models import Media, Company, CompanyBot
from chatbot.celery_tasks.knowledge_service.media_tasks import prepare_vector_db_data
from chatbot.utils.database_util import upsert_single_file


class MediaVectorDBSync:
    """Sync media files from database to vector database"""
    
    def __init__(
        self,
        company_slug: Optional[str] = None,
        company_bot_id: Optional[int] = None,
        media_ids: Optional[List[int]] = None,
        batch_size: int = 10,
        dry_run: bool = False,
        skip_errors: bool = True
    ):
        """
        Initialize sync manager
        
        Args:
            company_slug: Filter by company slug
            company_bot_id: Filter by company bot ID
            media_ids: Specific media IDs to process
            batch_size: Number of media to process in each batch
            dry_run: Test mode (don't actually upsert)
            skip_errors: Continue processing if errors occur
        """
        self.company_slug = company_slug
        self.company_bot_id = company_bot_id
        self.media_ids = media_ids
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.skip_errors = skip_errors
        
        self.stats = {
            'total_media': 0,
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'skipped': 0
        }
        
        self.results = []
        self._validate_filters()
    
    def _validate_filters(self):
        """Validate company and bot filters"""
        if self.company_slug:
            try:
                self.company = Company.objects.get(slug=self.company_slug)
                print(f"✅ Found company: {self.company.name} ({self.company_slug})")
            except Company.DoesNotExist:
                raise ValueError(f"Company with slug '{self.company_slug}' not found")
        
        if self.company_bot_id:
            try:
                self.company_bot = CompanyBot.objects.get(id=self.company_bot_id)
                print(f"✅ Found bot: {self.company_bot.name} (ID: {self.company_bot_id})")
            except CompanyBot.DoesNotExist:
                raise ValueError(f"CompanyBot with ID {self.company_bot_id} not found")
    
    def get_media_queryset(self):
        """Get filtered media queryset"""
        queryset = Media.objects.all()
        
        # Apply filters
        if self.media_ids:
            queryset = queryset.filter(id__in=self.media_ids)
            print(f"🔍 Filter: Specific media IDs: {self.media_ids}")
        
        if self.company_slug:
            queryset = queryset.filter(
                Q(company_bot__company__slug=self.company_slug) |
                Q(organization__slug=self.company_slug)
            )
            print(f"🔍 Filter: Company slug = {self.company_slug}")
        
        if self.company_bot_id:
            queryset = queryset.filter(company_bot_id=self.company_bot_id)
            print(f"🔍 Filter: Bot ID = {self.company_bot_id}")
        
        # Order by ID for consistent processing
        queryset = queryset.order_by('id')
        
        self.stats['total_media'] = queryset.count()
        print(f"📊 Total media to process: {self.stats['total_media']}\n")
        
        return queryset
    
    def sync_single_media(self, media_id: int) -> Dict[str, Any]:
        """
        Sync a single media file to vector DB
        
        Args:
            media_id: Media ID to process
            
        Returns:
            Result dictionary with success status and details
        """
        try:
            # Prepare vector DB data using existing function
            media, file_name, file_content, metadata = prepare_vector_db_data(
                media_id=media_id,
                include_updated_at=False,
                company_slug=self.company_slug
            )
            
            if self.dry_run:
                print(f"  🔍 DRY RUN: Would upsert media ID {media_id}")
                print(f"     File: {file_name}")
                print(f"     Company: {metadata.get('company', 'N/A')}")
                print(f"     Tags: {len(metadata.get('tags', []))} tags")
                
                return {
                    'success': True,
                    'media_id': media_id,
                    'file_name': file_name,
                    'message': 'Dry run - not saved',
                    'dry_run': True
                }
            
            # Upsert to vector DB
            status_code, response_text = upsert_single_file(
                filename=file_name,
                file=file_content,
                metadata=metadata,
                media=media
            )
            
            # Check if successful (2xx status codes)
            success = 200 <= status_code < 300
            
            if success:
                print(f"  ✅ Successfully upserted media ID {media_id}")
                return {
                    'success': True,
                    'media_id': media_id,
                    'file_name': file_name,
                    'status_code': status_code,
                    'message': 'Successfully upserted'
                }
            else:
                print(f"  ❌ Failed to upsert media ID {media_id}: Status {status_code}")
                return {
                    'success': False,
                    'media_id': media_id,
                    'file_name': file_name,
                    'status_code': status_code,
                    'message': f'Upsert failed with status {status_code}',
                    'response': response_text
                }
        
        except Media.DoesNotExist:
            error_msg = f"Media with ID {media_id} not found"
            print(f"  ⚠️  {error_msg}")
            return {
                'success': False,
                'media_id': media_id,
                'message': error_msg,
                'error_type': 'MEDIA_NOT_FOUND'
            }
        
        except Exception as e:
            error_msg = str(e)
            print(f"  ❌ Error processing media ID {media_id}: {error_msg}")
            if not self.skip_errors:
                traceback.print_exc()
            
            return {
                'success': False,
                'media_id': media_id,
                'message': error_msg,
                'error_type': 'PROCESSING_ERROR'
            }
    
    def sync_all(self) -> Dict[str, Any]:
        """
        Sync all filtered media to vector DB
        
        Returns:
            Statistics dictionary
        """
        media_queryset = self.get_media_queryset()
        
        if self.stats['total_media'] == 0:
            print("⚠️  No media found to process!")
            return self.stats
        
        print(f"{'='*80}")
        print(f"Starting Vector DB Sync")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"Batch size: {self.batch_size}")
        print(f"{'='*80}\n")
        
        # Process in batches
        media_ids = list(media_queryset.values_list('id', flat=True))
        
        for i in range(0, len(media_ids), self.batch_size):
            batch = media_ids[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (len(media_ids) + self.batch_size - 1) // self.batch_size
            
            print(f"\n{'='*80}")
            print(f"Batch {batch_num}/{total_batches} (Media IDs: {batch[0]} - {batch[-1]})")
            print(f"{'='*80}")
            
            for media_id in batch:
                self.stats['processed'] += 1
                progress = f"[{self.stats['processed']}/{self.stats['total_media']}]"
                
                print(f"\n{progress} Processing Media ID: {media_id}")
                print(f"{'-'*80}")
                
                result = self.sync_single_media(media_id)
                self.results.append(result)
                
                if result['success']:
                    self.stats['successful'] += 1
                else:
                    self.stats['failed'] += 1
                    
                    # Stop if not skipping errors
                    if not self.skip_errors:
                        print(f"\n❌ Stopping due to error (skip_errors=False)")
                        self._print_summary()
                        return self.stats
                
                # Small delay to avoid overwhelming the vector DB
                if not self.dry_run and i < len(media_ids) - 1:
                    time.sleep(0.1)
        
        self._print_summary()
        return self.stats
    
    def _print_summary(self):
        """Print sync summary"""
        print(f"\n{'='*80}")
        print(f"SYNC SUMMARY")
        print(f"{'='*80}")
        print(f"Mode:               {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"Total Media:        {self.stats['total_media']}")
        print(f"Processed:          {self.stats['processed']}")
        print(f"Successful:         {self.stats['successful']}")
        print(f"Failed:             {self.stats['failed']}")
        print(f"Skipped:            {self.stats['skipped']}")
        print(f"{'='*80}\n")
        
        if self.stats['failed'] > 0:
            print("Failed Media:")
            for result in self.results:
                if not result['success']:
                    media_id = result.get('media_id', 'Unknown')
                    message = result.get('message', 'Unknown error')
                    print(f"  ❌ Media ID {media_id}: {message}")
            print()


def main():
    """Main entry point for command-line usage"""
    parser = argparse.ArgumentParser(
        description='Sync media files from database to vector database'
    )
    
    parser.add_argument(
        '--company-slug',
        help='Filter by company slug'
    )
    parser.add_argument(
        '--bot-id',
        type=int,
        help='Filter by CompanyBot ID'
    )
    parser.add_argument(
        '--media-ids',
        help='Comma-separated list of specific media IDs to process (e.g., 1,2,3)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=10,
        help='Number of media to process in each batch (default: 10)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Test mode - show what would be done without actually upserting'
    )
    parser.add_argument(
        '--stop-on-error',
        action='store_true',
        help='Stop processing if an error occurs (default: continue)'
    )
    
    args = parser.parse_args()
    
    # Parse media IDs if provided
    media_ids = None
    if args.media_ids:
        try:
            media_ids = [int(x.strip()) for x in args.media_ids.split(',')]
        except ValueError:
            print("❌ Error: Invalid media IDs format. Use comma-separated integers (e.g., 1,2,3)")
            sys.exit(1)
    
    try:
        syncer = MediaVectorDBSync(
            company_slug=args.company_slug,
            company_bot_id=args.bot_id,
            media_ids=media_ids,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            skip_errors=not args.stop_on_error
        )
        
        stats = syncer.sync_all()
        
        # Exit with error code if any failed
        sys.exit(0 if stats['failed'] == 0 else 1)
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

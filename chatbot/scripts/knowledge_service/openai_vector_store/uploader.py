"""
Main script to upload all media files from database to OpenAI Vector Store

Usage:
    python uploader.py

Requirements:
    - OPENAI_API_KEY must be set in environment
    - OPENAI_VECTOR_STORE_ID must be set in environment
    - Django must be properly configured
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Django setup
import django
if __name__ == '__main__':
    project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
    sys.path.insert(0, str(project_root))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shikshalokam_mohini.settings')
    django.setup()

from chatbot.models import Media
from openai_client import OpenAIClient
from exceptions import OpenAIVectorStoreError, InvalidMediaError


# Setup logging
SCRIPT_DIR = Path(__file__).parent
LOG_FILE = SCRIPT_DIR / 'openai_vector_store_upload.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class MediaVectorStoreUploader:
    """
    Orchestrator for uploading all media files to OpenAI Vector Store
    """
    
    def __init__(self):
        """Initialize uploader with OpenAI client"""
        self.client = OpenAIClient()
        self.stats = {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'skipped': 0
        }
    
    def _get_media_info(self, media: Media) -> Dict[str, Any]:
        """
        Extract required information from media object
        
        Args:
            media: Media model instance
            
        Returns:
            dict: Contains organization slug, s3_url, and filename
            
        Raises:
            InvalidMediaError: If media is missing required data
        """
        try:
            # Get organization slug
            organization = media._get_org_slug()
            
            # Get S3 URL
            s3_url = media.get_s3_url()
            
            # Get filename from file field
            filename = os.path.basename(media.file.name) if media.file else None
            
            if not organization:
                raise InvalidMediaError(f"Media ID {media.id} has no organization")
            
            if not s3_url:
                raise InvalidMediaError(f"Media ID {media.id} has no S3 URL")
            
            if not filename:
                raise InvalidMediaError(f"Media ID {media.id} has no filename")
            
            return {
                'organization': organization,
                's3_url': s3_url,
                'filename': filename
            }
        except Exception as e:
            raise InvalidMediaError(f"Failed to extract info from media ID {media.id}: {str(e)}")
    
    def _upload_single_media(self, media: Media) -> bool:
        """
        Upload a single media file to OpenAI vector store
        """
        try:
            # Extract media information
            media_info = self._get_media_info(media)
            
            logger.info(
                f"Processing Media ID: {media.id}, Name: {media.name}, "
                f"Company: {media_info['organization']}, File: {media_info['filename']}"
            )
            
            # Upload to OpenAI and add to vector store
            result = self.client.upload_media_to_vector_store(
                s3_url=media_info['s3_url'],
                company=media_info['organization'],
                filename=media_info['filename']
            )
            
            logger.info(
                f"[SUCCESS] Media ID: {media.id}, Name: {media.name}, "
                f"File ID: {result['file_id']}, Company: {media_info['organization']}, "
                f"URL: {media_info['s3_url']}"
            )
            
            self.stats['successful'] += 1
            return True
            
        except InvalidMediaError as e:
            logger.warning(
                f"[SKIPPED] Media ID: {media.id}, Name: {media.name}, "
                f"Reason: {str(e)}"
            )
            self.stats['skipped'] += 1
            return False
            
        except OpenAIVectorStoreError as e:
            logger.error(
                f"[FAILED] Media ID: {media.id}, Name: {media.name}, "
                f"Error: {str(e)}"
            )
            self.stats['failed'] += 1
            return False
            
        except Exception as e:
            logger.error(
                f"[FAILED] Media ID: {media.id}, Name: {media.name}, "
                f"Unexpected error: {str(e)}"
            )
            self.stats['failed'] += 1
            return False
    
    def run(self):
        """
        Main execution method - processes all media files
        """
        start_time = datetime.now()
        
        logger.info("=" * 80)
        logger.info("Starting OpenAI Vector Store Upload Process")
        logger.info(f"Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Vector Store ID: {self.client.vector_store_id}")
        logger.info("=" * 80)
        
        # Query all media from database
        all_media = Media.objects.all()
        self.stats['total'] = all_media.count()
        
        logger.info(f"Total media files to process: {self.stats['total']}")
        logger.info("-" * 80)
        
        # Process each media file
        for index, media in enumerate(all_media, start=1):
            logger.info(f"Processing {index}/{self.stats['total']}...")
            self._upload_single_media(media)
            logger.info("-" * 80)
        
        # Log final summary
        end_time = datetime.now()
        duration = end_time - start_time
        
        logger.info("=" * 80)
        logger.info("Upload Process Completed")
        logger.info(f"End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Duration: {duration}")
        logger.info("")
        logger.info("SUMMARY:")
        logger.info(f"  Total Media Files: {self.stats['total']}")
        logger.info(f"  Successful Uploads: {self.stats['successful']}")
        logger.info(f"  Failed Uploads: {self.stats['failed']}")
        logger.info(f"  Skipped (Invalid): {self.stats['skipped']}")
        logger.info(f"  Success Rate: {(self.stats['successful'] / self.stats['total'] * 100):.2f}%" 
                   if self.stats['total'] > 0 else "  Success Rate: N/A")
        logger.info("=" * 80)
        
        print("\n" + "=" * 80)
        print(f"✅ Process completed! Check logs at: {LOG_FILE}")
        print("=" * 80)


def main():
    """Main entry point"""
    try:
        uploader = MediaVectorStoreUploader()
        uploader.run()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        print(f"❌ Fatal error occurred: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()

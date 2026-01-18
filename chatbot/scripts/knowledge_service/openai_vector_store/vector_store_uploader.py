"""
Standalone Media to OpenAI Vector Store Uploader
All-in-one script that can be run directly or pasted into terminal
Requirements:
    - OPENAI_API_KEY must be set in environment
    - OPENAI_VECTOR_STORE_ID must be set in environment
    - Django must be properly configured
"""

import os
import sys
import logging
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Django setup
import django
try:
    project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
except NameError:
    # __file__ is not defined in interactive shell, use cwd
    project_root = Path.cwd().parent.parent.parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shikshalokam_mohini.settings')
django.setup()

from chatbot.models import Media


# ============================================================================
# EXCEPTIONS
# ============================================================================

class OpenAIVectorStoreError(Exception):
    """Base exception for OpenAI vector store operations"""
    pass


class OpenAIUploadError(OpenAIVectorStoreError):
    """Exception raised when uploading file to OpenAI fails"""
    pass


class S3FetchError(OpenAIVectorStoreError):
    """Exception raised when fetching file from S3 fails"""
    pass


class VectorStoreError(OpenAIVectorStoreError):
    """Exception raised when adding file to vector store fails"""
    pass


class InvalidMediaError(OpenAIVectorStoreError):
    """Exception raised when media object is invalid or missing required data"""
    pass


# ============================================================================
# S3 HANDLER
# ============================================================================

def validate_s3_url(url: str) -> bool:
    """Validate if the URL is a valid S3 URL"""
    if not url:
        return False
    return url.startswith(('http://', 'https://')) and len(url) > 10


def fetch_file_from_s3(s3_url: str, timeout: int = 30) -> requests.Response:
    """Fetch file from S3 URL with streaming support"""
    if not validate_s3_url(s3_url):
        raise S3FetchError(f"Invalid S3 URL: {s3_url}")
    
    try:
        response = requests.get(s3_url, stream=True, timeout=timeout)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        raise S3FetchError(f"Failed to fetch file from S3: {s3_url}. Error: {str(e)}")


def get_filename_from_url(s3_url: str) -> str:
    """Extract filename from S3 URL"""
    return s3_url.split('/')[-1] if s3_url else "unknown_file"


# ============================================================================
# OPENAI CLIENT
# ============================================================================

class OpenAIClient:
    """Client for interacting with OpenAI API"""
    
    OPENAI_FILES_URL = "https://api.openai.com/v1/files"
    OPENAI_VECTOR_STORE_FILES_URL = "https://api.openai.com/v1/vector_stores/{vector_store_id}/files"
    
    def __init__(self, api_key: Optional[str] = None, vector_store_id: Optional[str] = None):
        """Initialize OpenAI client"""
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        self.vector_store_id = vector_store_id or os.getenv('OPENAI_VECTOR_STORE_ID')
        
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        if not self.vector_store_id:
            raise ValueError("OPENAI_VECTOR_STORE_ID not found in environment variables")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
    
    def upload_file_to_openai(self, s3_url: str, filename: Optional[str] = None) -> Dict[str, Any]:
        """Upload a file from S3 to OpenAI Files API"""
        try:
            # Fetch file from S3
            s3_response = fetch_file_from_s3(s3_url)
            
            # Get filename
            if not filename:
                filename = get_filename_from_url(s3_url)
            
            # Upload to OpenAI
            openai_response = requests.post(
                self.OPENAI_FILES_URL,
                headers=self.headers,
                files={
                    "file": (filename, s3_response.raw),
                },
                data={
                    "purpose": "assistants",
                },
            )
            
            openai_response.raise_for_status()
            return openai_response.json()
            
        except Exception as e:
            raise OpenAIUploadError(f"Failed to upload file to OpenAI: {s3_url}. Error: {str(e)}")
    
    def add_file_to_vector_store(
        self, 
        file_id: str, 
        company: str, 
        url: str
    ) -> Dict[str, Any]:
        """Add uploaded file to vector store with metadata"""
        try:
            vector_store_url = self.OPENAI_VECTOR_STORE_FILES_URL.format(
                vector_store_id=self.vector_store_id
            )
            
            payload = {
                "file_id": file_id,
                "attributes": {
                    "company": company,
                    "url": url
                }
            }
            
            response = requests.post(
                vector_store_url,
                headers={**self.headers, "Content-Type": "application/json"},
                json=payload
            )
            
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            raise VectorStoreError(
                f"Failed to add file to vector store. File ID: {file_id}, Company: {company}. "
                f"Error: {str(e)}"
            )
    
    def upload_media_to_vector_store(
        self, 
        s3_url: str, 
        company: str, 
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Complete workflow: Upload file to OpenAI and add to vector store"""
        # Step 1: Upload file to OpenAI
        upload_response = self.upload_file_to_openai(s3_url, filename)
        file_id = upload_response.get('id')
        
        if not file_id:
            raise OpenAIUploadError(f"No file_id returned from OpenAI for {s3_url}")
        
        # Step 2: Add to vector store
        vector_store_response = self.add_file_to_vector_store(file_id, company, s3_url)
        
        return {
            "file_id": file_id,
            "upload_response": upload_response,
            "vector_store_response": vector_store_response
        }


# ============================================================================
# UPLOADER
# ============================================================================

try:
    SCRIPT_DIR = Path(__file__).parent
except NameError:
    SCRIPT_DIR = Path.cwd()
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
    """Orchestrator for uploading all media files to OpenAI Vector Store"""
    
    def __init__(self, max_workers: int = 4):
        """Initialize uploader with OpenAI client"""
        self.client = OpenAIClient()
        self.max_workers = max_workers
        self.stats = {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'skipped': 0
        }
    
    def _get_media_info(self, media: Media) -> Dict[str, Any]:
        """Extract required information from media object"""
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
    
    def _upload_single_media(self, media: Media) -> Tuple[int, bool, str]:
        """Upload a single media file to OpenAI vector store"""
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
            
            success_msg = (
                f"[SUCCESS] Media ID: {media.id}, Name: {media.name}, "
                f"File ID: {result['file_id']}, Company: {media_info['organization']}, "
                f"URL: {media_info['s3_url']}"
            )
            logger.info(success_msg)
            
            return (media.id, True, 'success')
            
        except InvalidMediaError as e:
            skip_msg = (
                f"[SKIPPED] Media ID: {media.id}, Name: {media.name}, "
                f"Reason: {str(e)}"
            )
            logger.warning(skip_msg)
            return (media.id, False, 'skipped')
            
        except OpenAIVectorStoreError as e:
            error_msg = (
                f"[FAILED] Media ID: {media.id}, Name: {media.name}, "
                f"Error: {str(e)}"
            )
            logger.error(error_msg)
            return (media.id, False, 'failed')
            
        except Exception as e:
            error_msg = (
                f"[FAILED] Media ID: {media.id}, Name: {media.name}, "
                f"Unexpected error: {str(e)}"
            )
            logger.error(error_msg)
            return (media.id, False, 'failed')
    
    def _upload_media_parallel(self, all_media):
        """Upload media files in parallel using ThreadPoolExecutor"""
        logger.info(f"Running with ThreadPoolExecutor (workers={self.max_workers})")
        print(f"[INFO] Running with ThreadPoolExecutor (workers={self.max_workers})")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            futures = [
                executor.submit(self._upload_single_media, media)
                for media in all_media
            ]
            
            # Process completed tasks
            completed = 0
            for future in as_completed(futures):
                completed += 1
                media_id, success, status = future.result()
                
                # Update stats based on status
                if status == 'success':
                    self.stats['successful'] += 1
                elif status == 'skipped':
                    self.stats['skipped'] += 1
                elif status == 'failed':
                    self.stats['failed'] += 1
                
                # Log progress
                if completed % 10 == 0 or completed == self.stats['total']:
                    logger.info(f"Progress: {completed}/{self.stats['total']} completed")
                    print(f"[INFO] Progress: {completed}/{self.stats['total']} completed")
    
    def run(self):
        """Main execution method - processes all media files"""
        start_time = datetime.now()
        
        logger.info("=" * 80)
        logger.info("Starting OpenAI Vector Store Upload Process")
        logger.info(f"Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Vector Store ID: {self.client.vector_store_id}")
        logger.info("=" * 80)
        
        # Query all media from database
        all_media = list(Media.objects.all())
        self.stats['total'] = len(all_media)
        
        logger.info(f"Total media files to process: {self.stats['total']}")
        logger.info("-" * 80)
        
        # Process media files in parallel
        self._upload_media_parallel(all_media)
        
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


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main entry point"""
    try:
        # Can adjust max_workers here if needed
        uploader = MediaVectorStoreUploader(max_workers=4)
        uploader.run()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        print(f"❌ Fatal error occurred: {str(e)}")
        sys.exit(1)

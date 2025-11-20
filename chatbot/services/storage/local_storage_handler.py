"""
Local file system storage handler implementation
"""
import os
import shutil
import logging
from pathlib import Path
from typing import BinaryIO
from django.conf import settings

from .base_storage_handler import BaseStorageHandler, UploadConfig, UploadResult

logger = logging.getLogger('django')


class LocalStorageHandler(BaseStorageHandler):
    """
    Local file system implementation of the storage handler
    Handles file uploads, deletions, and URL generation for local storage
    """

    def __init__(self, config: dict):
        """
        Initialize local storage handler
        
        Args:
            config: Dictionary containing local storage configuration
                   Expected keys: location, base_url
        """
        super().__init__(config)
        self.location = config.get('location', os.path.join(settings.BASE_DIR, 'media'))
        self.base_url = config.get('base_url', '/media/')
        
        # Ensure storage directory exists
        Path(self.location).mkdir(parents=True, exist_ok=True)

    def generate_presigned_url(self, upload_config: UploadConfig) -> UploadResult:
        """
        For local storage, return a direct URL (no presigned URL needed)
        
        Args:
            upload_config: Configuration for the upload operation
            
        Returns:
            UploadResult with file path and URL
        """
        try:
            object_key = self._generate_object_key(upload_config)
            file_path = os.path.join(self.location, object_key)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            public_url = self.get_public_url(object_key)
            
            logger.info(f"Generated local file path: {object_key}")
            
            return UploadResult(
                upload_url=file_path,  # For local, upload_url is the file path
                object_key=object_key,
                public_url=public_url,
                success=True
            )
            
        except Exception as e:
            error_msg = f"Failed to generate local file path: {str(e)}"
            logger.error(error_msg)
            return UploadResult(
                upload_url='',
                object_key='',
                public_url='',
                success=False,
                error=error_msg
            )

    def upload_file(self, file_obj: BinaryIO, upload_config: UploadConfig) -> UploadResult:
        """
        Save a file to local storage
        
        Args:
            file_obj: File object to save
            upload_config: Configuration for the upload
            
        Returns:
            UploadResult with file details
        """
        try:
            object_key = self._generate_object_key(upload_config)
            file_path = os.path.join(self.location, object_key)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Write file to disk
            with open(file_path, 'wb') as destination:
                for chunk in file_obj.chunks() if hasattr(file_obj, 'chunks') else [file_obj.read()]:
                    destination.write(chunk)
            
            public_url = self.get_public_url(object_key)
            
            logger.info(f"Successfully saved file locally: {object_key}")
            
            return UploadResult(
                upload_url=file_path,
                object_key=object_key,
                public_url=public_url,
                success=True
            )
            
        except Exception as e:
            error_msg = f"Failed to save file locally: {str(e)}"
            logger.error(error_msg)
            return UploadResult(
                upload_url='',
                object_key='',
                public_url='',
                success=False,
                error=error_msg
            )

    def delete_file(self, object_key: str) -> bool:
        """
        Delete a file from local storage
        
        Args:
            object_key: File path to delete
            
        Returns:
            True if deletion was successful
        """
        try:
            file_path = os.path.join(self.location, object_key)
            
            if os.path.isfile(file_path):
                os.remove(file_path)
                logger.info(f"Successfully deleted local file: {object_key}")
                return True
            else:
                logger.warning(f"File not found for deletion: {object_key}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to delete local file: {str(e)}")
            return False

    def get_public_url(self, object_key: str) -> str:
        """
        Get the public URL for a local file
        
        Args:
            object_key: File path
            
        Returns:
            Public URL string
        """
        # Normalize path separators for URL
        url_path = object_key.replace(os.sep, '/')
        return f"{self.base_url.rstrip('/')}/{url_path}"

    def file_exists(self, object_key: str) -> bool:
        """
        Check if a file exists in local storage
        
        Args:
            object_key: File path
            
        Returns:
            True if file exists
        """
        file_path = os.path.join(self.location, object_key)
        return os.path.isfile(file_path)


"""
OpenAI API client for file upload and vector store operations
"""

import os
import requests
from typing import Dict, Any, Optional
from exceptions import OpenAIUploadError, VectorStoreError
from s3_handler import fetch_file_from_s3, get_filename_from_url


class OpenAIClient:
    """Client for interacting with OpenAI API"""
    
    OPENAI_FILES_URL = "https://api.openai.com/v1/files"
    OPENAI_VECTOR_STORE_FILES_URL = "https://api.openai.com/v1/vector_stores/{vector_store_id}/files"
    
    def __init__(self, api_key: Optional[str] = None, vector_store_id: Optional[str] = None):
        """
        Initialize OpenAI client
        
        Args:
            api_key: OpenAI API key (defaults to environment variable)
            vector_store_id: Vector store ID (defaults to environment variable)
        """
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
        """
        Upload a file from S3 to OpenAI Files API
        """
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
        """
        Add uploaded file to vector store with metadata
        
        """
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
        """
        Complete workflow: Upload file to OpenAI and add to vector store
        
        Args:
            s3_url: Full S3 URL of the file
            company: Company/organization slug
            filename: Optional filename
            
        Returns:
            dict: Combined result with file_id and vector store response
        """
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

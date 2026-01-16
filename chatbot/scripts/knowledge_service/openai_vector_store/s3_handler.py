"""
S3 file handling utilities for fetching files from S3
"""

import requests
from typing import Optional
from exceptions import S3FetchError


def validate_s3_url(url: str) -> bool:
    """
    Validate if the URL is a valid S3 URL
    
    Args:
        url: The S3 URL to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not url:
        return False
    
    # Check if URL starts with http/https and contains expected patterns
    return url.startswith(('http://', 'https://')) and len(url) > 10


def fetch_file_from_s3(s3_url: str, timeout: int = 30) -> requests.Response:
    """
    Fetch file from S3 URL with streaming support
    
    Args:
        s3_url: Full S3 URL of the file
        timeout: Request timeout in seconds
        
    Returns:
        requests.Response: Streaming response object
        
    Raises:
        S3FetchError: If fetching file from S3 fails
    """
    if not validate_s3_url(s3_url):
        raise S3FetchError(f"Invalid S3 URL: {s3_url}")
    
    try:
        response = requests.get(s3_url, stream=True, timeout=timeout)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        raise S3FetchError(f"Failed to fetch file from S3: {s3_url}. Error: {str(e)}")


def get_filename_from_url(s3_url: str) -> str:
    """
    Extract filename from S3 URL
    
    Args:
        s3_url: Full S3 URL
        
    Returns:
        str: Filename extracted from URL
    """
    return s3_url.split('/')[-1] if s3_url else "unknown_file"

"""
Custom exceptions for OpenAI Vector Store upload operations
"""


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

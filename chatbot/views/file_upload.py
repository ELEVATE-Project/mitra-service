import re
import uuid
from os.path import basename, splitext

import boto3
from botocore.config import Config
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

URL_EXPIRES_IN = 3600
REF_PATTERN = re.compile(r"^[a-z0-9_-]+$")
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")

MAX_FILES = 10

# Advisory only: a presigned PUT cannot enforce size. The frontend checks this before upload.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# Explicit allow-list. Anything else (html, js, svg, exe, ...) is rejected.
ALLOWED_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _s3():
    """Create a boto3 S3 client for the configured region.

    Uses Signature Version 4, which the ap-south-1 region requires for presigned URLs.

    Returns:
        boto3.client: An S3 client. Credentials come from the environment, as configured in settings.
    """
    return boto3.client(
        "s3",
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version="s3v4"),
    )


def _clean_name(name):
    """Turn a client-supplied file name into a safe object name.

    Strips any directory part, replaces characters outside A-Z, a-z, 0-9, dot, underscore
    and hyphen with underscores, and rejects names made only of dots.

    Args:
        name (str): The file name as sent by the client. May include a path.

    Returns:
        str: The cleaned file name, or an empty string if nothing usable remains.
    """
    name = SAFE_NAME.sub("_", basename(name or ""))
    # A name made only of dots would become a "." or ".." path segment
    if not name.strip("."):
        return ""
    return name


def _content_type_for(name):
    """Look up the MIME type for a file name from the extension allow-list.

    Args:
        name (str): The cleaned file name, including its extension.

    Returns:
        str | None: The MIME type if the extension is allowed, otherwise None.
    """
    return ALLOWED_EXTENSIONS.get(splitext(name)[1].lower())


def _is_safe_key(key):
    """Check that an S3 object key has no empty, "." or ".." path segments.

    Dots inside a segment are allowed, so names such as "photo..jpg" pass.

    Args:
        key (str): The object key to check, using "/" as the separator.

    Returns:
        bool: True if the key is non-empty and every segment is usable, otherwise False.
    """
    if not key:
        return False
    return all(segment not in ("", ".", "..") for segment in key.split("/"))


class PresignedUploadView(APIView):
    """Issue presigned PUT URLs so the browser can upload files directly to S3.

    Each file gets its own key under ``<ref>/<entity_id>/<uuid>/<name>``. The client
    must send the returned Content-Type header with the PUT, or S3 rejects the
    signature. Size is not enforced by S3 for PUT; the frontend checks MAX_UPLOAD_BYTES.
    Auth is not yet enforced; it is planned separately.
    """

    # No authentication_classes or permission_classes yet. Auth is planned separately.

    def post(self, request):
        """Validate the request and return one presigned PUT URL per file.

        Request body:
            ref (str): Folder prefix made of lowercase letters, digits, "_" and "-".
            files (list[str]): File names to upload. At most MAX_FILES entries.

        Returns:
            Response: 200 with the upload entries under ``result``, or 400 if the
            request is invalid. All files are validated before any URL is created.
        """
        ref = (request.data.get("ref") or "").strip().lower()
        files = request.data.get("files") or []

        if not REF_PATTERN.match(ref):
            return Response({"message": "Invalid ref.", "status": 400},
                            status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(files, list) or not files:
            return Response({"message": "files must be a non-empty list.", "status": 400},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(files) > MAX_FILES:
            return Response({"message": f"At most {MAX_FILES} files per request.", "status": 400},
                            status=status.HTTP_400_BAD_REQUEST)

        # Validate every file before creating any URL
        cleaned = []
        for raw_name in files:
            name = _clean_name(str(raw_name))
            content_type = _content_type_for(name)
            if not name or not content_type:
                return Response(
                    {"message": "Only jpg, jpeg, png, gif and webp files are allowed.", "status": 400},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            cleaned.append((name, content_type))

        entity_id = uuid.uuid4().hex  # generated here, not sent by the client
        s3 = _s3()
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        entries = []

        for name, content_type in cleaned:
            key = f"{ref}/{entity_id}/{uuid.uuid4()}/{name}"
            url = s3.generate_presigned_url(
                ClientMethod="put_object",
                Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=URL_EXPIRES_IN,
            )
            entries.append({
                "file": name,
                "payload": {"sourcePath": key},
                "method": "PUT",
                "url": url,
                "headers": {"Content-Type": content_type},
            })

        return Response({
            "message": "Url generated successfully",
            "status": 200,
            "result": {
                "cloudStorage": "s3",
                entity_id: {"files": entries},
            },
        }, status=status.HTTP_200_OK)


class PresignedDownloadView(APIView):
    """Issue a presigned GET URL for an existing object so it can be displayed or downloaded.

    Endpoint: GET /api/media/presigned-download/?path=<sourcePath>
    Auth is not yet enforced; it is planned separately.
    """

    def get(self, request):
        """Return a time-limited download URL for the object at the given path.

        Query parameters:
            path (str): The object key, as returned in ``payload.sourcePath`` by the upload endpoint.

        Returns:
            Response: 200 with ``result.downloadUrl``, or 400 if the path is missing or unsafe.
        """
        path = (request.query_params.get("path") or "").lstrip("/")
        if not _is_safe_key(path):
            return Response({"message": "Invalid path.", "status": 400},
                            status=status.HTTP_400_BAD_REQUEST)

        url = _s3().generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": path},
            ExpiresIn=URL_EXPIRES_IN,
        )
        return Response({
            "message": "Url generated successfully",
            "status": 200,
            "result": {"downloadUrl": url},
        }, status=status.HTTP_200_OK)
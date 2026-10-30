import mimetypes
import re
import uuid
from os.path import basename

import boto3
from botocore.config import Config
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

URL_EXPIRES_IN = 3600
REF_PATTERN = re.compile(r"^[a-z0-9_-]+$")
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _s3():
    return boto3.client(
        "s3",
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version="s3v4"),
    )


def _clean_name(name):
    name = SAFE_NAME.sub("_", basename(name or ""))
    return name or "file"

def _is_safe_key(key):
    """Reject empty keys and keys with empty, "." or ".." segments. Dots inside a name are fine."""
    if not key:
        return False
    return all(segment not in ("", ".", "..") for segment in key.split("/"))


class PresignedUploadView(APIView):
    # No authentication_classes or permission_classes. The project defaults apply.

    def post(self, request):
        ref = (request.data.get("ref") or "").strip().lower()
        files = request.data.get("files") or []

        if not REF_PATTERN.match(ref):
            return Response({"message": "Invalid ref.", "status": 400},
                            status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(files, list) or not files:
            return Response({"message": "files must be a non-empty list.", "status": 400},
                            status=status.HTTP_400_BAD_REQUEST)

        entity_id = uuid.uuid4().hex  # generated here, not sent by the client
        s3 = _s3()
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        entries = []

        for raw_name in files:
            name = _clean_name(str(raw_name))
            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            key = f"{ref}/{entity_id}/{uuid.uuid4()}/{name}"
            url = s3.generate_presigned_url(
                ClientMethod="put_object",
                Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=URL_EXPIRES_IN,
            )
            entries.append({
                "file": name,
                "payload": {"sourcePath": key},
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
    # GET /api/media/presigned-download/?path=<sourcePath>
    def get(self, request):
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
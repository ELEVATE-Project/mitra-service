import os
import boto3
import time
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["POST"])
def get_presigned_url(request):
    file_name = request.data.get("fileName")
    file_type = request.data.get("fileType")
    story_id = request.data.get("storyId")

    if not file_name or not file_type:
        return Response({"error": "Missing fileName or fileType"}, status=400)

    key = f"chatbot/storymedia/{story_id}/{int(time.time())}-{file_name}"

    s3_client = boto3.client(
        "s3",
        region_name=os.getenv('AWS_REGION'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    )

    # Generate pre-signed URL for upload
    upload_url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": os.getenv('S3_BUCKET_NAME'),
            "Key": key,
            "ContentType": file_type,
            "ACL": "public-read",
        },
        ExpiresIn=3600,
    )

    # Public URL for accessing the uploaded file
    public_url = f"https://{os.getenv('S3_BUCKET_NAME')}/{key}"

    return Response({
        "uploadUrl": upload_url,
        "s3ObjectKey": key,
        "s3Url": public_url,
    })

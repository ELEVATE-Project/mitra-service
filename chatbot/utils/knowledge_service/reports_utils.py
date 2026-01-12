import os
import time
import requests
from io import BytesIO
from openpyxl import Workbook
import boto3


def generate_xlsx_from_json(data, sheet_name="Sheet1"):
    """
    Generate an Excel file from JSON-like data and return BytesIO
    """

    if isinstance(data, dict):
        data = [data]

    if not data or not isinstance(data, list):
        raise ValueError("Invalid or empty data provided for Excel generation")

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    headers = list(data[0].keys())
    ws.append(headers)

    for item in data:
        ws.append([item.get(header, "") for header in headers])

    excel_file = BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)

    return excel_file


def upload_excel_to_s3(
    excel_content,
    file_name,
    project_id=None,
    folder_structure="shikshagraha_commons/"
):
    """
    Upload Excel file to S3 using presigned URL
    """

    key = f"{folder_structure}{project_id + '/' if project_id else ''}{int(time.time())}-{file_name}"

    s3_client = boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

    upload_url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": os.getenv("S3_BUCKET_NAME"),
            "Key": key,
            "ContentType": (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        },
        ExpiresIn=3600,
    )

    upload_response = requests.put(
        upload_url,
        data=excel_content,
        headers={
            "Content-Type": (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        },
    )

    if upload_response.status_code != 200:
        raise RuntimeError("Failed to upload Excel file to S3")

    public_url = (
        f"{os.getenv('S3_MEDIA_URL')}{key}"
    )

    return {
        "key": key,
        "url": public_url,
        "file_name": file_name,
    }

import traceback
import requests
from chatbot.models import Profile, MediaTypeChoices
from chatbot.pdf.knowledge_service.project_report_pdf import generate_project_pdf
from chatbot.utils.shikshalokam_mitra_utils import create_project_utils, create_mitra_project_utils
from rest_framework.decorators import api_view
from rest_framework.response import Response
import boto3
import os
import time


def get_s3_presigned_url_and_upload(file_name, file_content, file_type, project_id, folder_structure):
    """Generate presigned URL and upload file to S3"""
    try:
        # Prepare S3 key
        if project_id:
            id_to_use = f'{project_id}/'
        else:
            id_to_use = ''

        key = f"{folder_structure}{id_to_use}{int(time.time())}-{file_name}"

        # Initialize S3 client
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
            },
            ExpiresIn=3600,
        )

        print("Upload URL: ", upload_url)
        # Public URL for accessing the uploaded file
        public_url = (
            f"https://{os.getenv('S3_BUCKET_NAME')}.s3.{os.getenv('AWS_REGION')}.amazonaws.com/{key}"
        )

        print("public_url: ", public_url)
        # Upload file to S3 using presigned URL
        upload_response = requests.put(
            upload_url,
            data=file_content,
            headers={
                'Content-Type': file_type,
            }
        )
        print("upload_response: ", upload_response)
        if upload_response.status_code == 200:
            print(f"File uploaded successfully to S3: {key}")
            return key
        else:
            print(f"Failed to upload file to S3: {upload_response.status_code}")
            return None

    except Exception as e:
        print(f"Error in S3 upload: {str(e)}")
        return None


@api_view(['POST'])
def create_project_view(request):
    body = request.data
    access_token = body.get('access_token')
    session = body.get('session')
    user_problem_statement = body.get('user_problem_statement')
    user_action_steps = body.get('user_action_steps')
    project_duration = body.get('project_duration')
    project_title = body.get('project_title')
    project_objective = body.get('user_objective')
    profile_id = body.get('profile_id')
    chunks = body.get('chunks')
    language = body.get('language')

    print("project_title: ", project_title)
    print("profile_id: ", profile_id)

    # if not access_token and profile_id:
    #     return Response({
    #         'status': 'ok',
    #         'message': 'Skipping api call',
    #     }, status=200)


    project_id = None
    program_id = None
    response = ""
    if access_token:
        if not chunks:
            return Response({
                'status': 'error',
                'message': 'Project source cant be empty',
            }, status=500)

        response = create_project_utils(
            access_token=access_token, user_problem_statement=user_problem_statement,
            user_action_steps=user_action_steps, project_title=project_title,
            project_duration_weeks=project_duration, chunks=chunks, session=session,
            project_objective=project_objective, status='started'
        )

        project_id = response.get('projectId')
        program_id = response.get('programId')

    profile = Profile.objects.filter(id=profile_id).first()

    result = create_mitra_project_utils(
        profile=profile,
        actual_problem_statement=user_problem_statement,
        project_title=project_title,
        project_duration=project_duration,
        project_objective=project_objective,
        user_action_steps=user_action_steps,
        project_id=project_id,
        program_id=program_id,
        chunks=chunks,
        language=language,
        session=session
    )

    print("Result: ", result)
    pdf_url = None
    pdf_filename = "Project_Report.pdf"

    try:
        # Get author info from profile
        author_name = profile.first_name if profile else ""
        location = profile.location if profile and hasattr(profile, '') else ""

        # Format timeline with proper week/weeks suffix
        timeline = ""
        if project_duration:
            # Check if it's already a string with "week" or "weeks"
            duration_str = str(project_duration).strip().lower()
            if "week" in duration_str:
                # Already contains "week", use as-is
                timeline = str(project_duration).strip()
            else:
                try:
                    # Convert to int and add appropriate suffix
                    duration_value = int(project_duration)
                    # Add "week" or "weeks" based on the value
                    if duration_value == 1:
                        timeline = f"{duration_value} week"
                    else:
                        timeline = f"{duration_value} weeks"
                except (ValueError, TypeError):
                    # If conversion fails, use the value as-is
                    timeline = str(project_duration)

        # Generate the PDF
        pdf_content = generate_project_pdf(
            project_title=project_title,
            author_name=author_name,
            location=location,
            problem_statement=user_problem_statement,
            objective=project_objective,
            timeline=timeline,
            action_steps=user_action_steps,
            sources=chunks,
            language=language,
            session=session
        )

        print("PDF report is generated successfully")

        if pdf_content and result.get('project_id'):
            # Prepare file name for S3
            pdf_filename = f"{project_title}.pdf" if project_title else "Project_Report.pdf"
            # Clean filename for S3 (remove special characters)
            pdf_filename = "".join(c for c in pdf_filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
            pdf_filename = pdf_filename.replace(' ', '_')

            # Upload to S3 and get public URL
            key = get_s3_presigned_url_and_upload(
                file_name=pdf_filename,
                file_content=pdf_content.read(),
                file_type="application/pdf",
                project_id=result.get('project_id'),
                folder_structure="shikshagraha_commons/"
            )

            if key:
                base = os.getenv("S3_MEDIA_URL")
                pdf_url = f"{base}{key}"
            else:
                print("Failed to upload PDF to S3")

    except Exception as e:
        print(f"Error generating/uploading PDF: {str(e)}")
        traceback.print_exc()

        # Prepare media response
    media_response = []
    if pdf_url:
        media_response.append({
            'media_type': MediaTypeChoices.PDF,
            'url': pdf_url,
            'file_name': pdf_filename
        })
    else:
        # Fallback to default URL if upload failed
        media_response.append({
            'media_type': MediaTypeChoices.PDF,
            'url': '',
            'file_name': pdf_filename
        })

    return Response({
        'status': 'ok',
        'result': response,
        'mitra_result': result,
        'media': media_response
    }, status=200)

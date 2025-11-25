import traceback
from chatbot.models import Profile, MediaTypeChoices
from chatbot.pdf.knowledge_service.project_report_pdf import generate_project_pdf
from chatbot.utils.shikshalokam_mitra_utils import create_project_utils, create_mitra_project_utils
from rest_framework.decorators import api_view
from rest_framework.response import Response


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

    try:
        # Get author info from profile
        author_name = profile.first_name if profile else ""
        location = profile.location if profile and hasattr(profile, '') else ""

        timeline = f"{project_duration}" if project_duration else ""

        # Generate the PDF
        pdf_content = generate_project_pdf(
            project_title=project_title,
            author_name=author_name,
            location=location,
            problem_statement=user_problem_statement,
            objective=project_objective,
            timeline=timeline,
            action_steps=user_action_steps,
            sources=None
        )

        print("PDF report is generated successfully")

        if pdf_content and result.get('project_id'):
            # Prepare file name for S3
            pdf_filename = f"{project_title}.pdf" if project_title else "Project_Report.pdf"
            # Clean filename for S3 (remove special characters)
            pdf_filename = "".join(c for c in pdf_filename if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
            pdf_filename = pdf_filename.replace(' ', '_')

            # Upload to S3 and get public URL
            pdf_url = get_s3_presigned_url_and_upload(
                file_name=pdf_filename,
                file_content=pdf_content.read(),
                file_type="application/pdf",
                project_id=result.get('project_id'),
                folder_structure="shikshagraha_commons/"
            )

            if pdf_url:
                print(f"PDF successfully uploaded to: {pdf_url}")
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
            'url': pdf_url
        })
    else:
        # Fallback to default URL if upload failed
        media_response.append({
            'media_type': MediaTypeChoices.PDF,
            'url': ''
        })

    return Response({
        'status': 'ok',
        'result': response,
        'mitra_result': result,
        'media': media_response
    }, status=200)

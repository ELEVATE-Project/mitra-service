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


    except Exception as e:
        print(f"Error generating PDF: {str(e)}")
        traceback.print_exc()

    return Response({
        'status': 'ok',
        'result': response,
        'mitra_result': result,
        'media': [{
            'media_type': MediaTypeChoices.PDF,
            'url': 'https://qa-mohini-static.shikshalokam.org/chatbot/storymedia/1215/Ground_Realities_Education_Challenges_and_Community_Responses.pdf'
        }]
    }, status=200)

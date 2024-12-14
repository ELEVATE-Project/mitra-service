from rest_framework.decorators import api_view
from rest_framework.response import Response
from chatbot.models import CompanyChat, ChatSession, ChatStatus, Profile, Company


@api_view(['POST'])
def save_chats_view(request):
    body = request.data
    message = body.get('message')
    session = body.get('session')
    status = body.get('status', 'COMPLETED')
    role = body.get('role')

    if not message or not session:
        return Response({"error": "message and session are required."}, status=400)

    print("message: ", message)


    try:
        ai_user = Profile.objects.get(id=1)
    except Profile.DoesNotExist:
        return Response({"error": "AI profile not found."}, status=400)


    if role == 'bot':
        sender = ai_user
        receiver = None
    elif role == 'user':
        sender = None
        receiver = ai_user
    else:
        return Response({"error": "Invalid role. Must be 'bot' or 'user'."}, status=400)

    CompanyChat.objects.create(
        message=message,
        session=session,
        status=status,
        sender=sender,
        receiver=receiver
    )


    return Response({
        'status': 'ok',
        'message': 'Message saved successfully!'
    }, status=200)


@api_view(['POST'])
def create_chatsession(request):
    body = request.data
    session = body.get('session')
    email = body.get('email')
    first_name = body.get('first_name')
    preferred_language =  body.get('preferred_language', {}).get('value')

    if not session:
        return Response({"error": "session is required."}, status=400)

    if not email:
        return Response({"error": "Email is required."}, status=400)

    try:
        company = Company.objects.get(slug='shikshalokamstaging')
    except Exception as e:
        return Response({"error": f"{e}"}, status=400)

    profile, created = Profile.objects.get_or_create(
        email=email,
        defaults={
            'first_name': first_name,
            'password': 'grit@123',
            'preferred_route': preferred_language,
            'company': company
        }
    )

    c, created = ChatSession.objects.get_or_create(
        session=session,
        defaults={
            'session_status': ChatStatus.IN_PROGRESS,
            'profile': profile,
        }
    )

    return Response({
        'status': 'ok',
        'message': 'Chatsession created!' if created else 'Chatsession already exists!',
        'chatsession': {
            'session': c.session,
            'session_status': c.session_status,
            'profile_id': profile.id
        }
    }, status=200)

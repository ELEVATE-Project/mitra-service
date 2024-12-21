from rest_framework.decorators import api_view
from rest_framework.response import Response
from chatbot.models import CompanyChat, ChatSession, ChatStatus, Profile, Company
import jwt
from django.http import JsonResponse


@api_view(['POST'])
def save_chats_view(request):
    body = request.data
    message = body.get('message')
    session = body.get('session')
    status = body.get('status', 'COMPLETED')
    role = body.get('role')
    chunks = body.get('chunks')
    user_profile = None
    if not message or not session:
        return Response({"error": "message and session are required."}, status=400)

    print("message: ", message)


    try:
        ai_user = Profile.objects.get(id=1)
    except Profile.DoesNotExist:
        return Response({"error": "AI profile not found."}, status=400)

    try:
        chat_session = ChatSession.objects.get(session=session)
        if chat_session:
            user_profile = chat_session.profile
    except ChatSession.DoesNotExist:
        return Response({"error": "chat_session not found."}, status=400)


    if role == 'bot':
        sender = ai_user
        receiver = user_profile
    elif role == 'user':
        sender = user_profile
        receiver = ai_user
    else:
        return Response({"error": "Invalid role. Must be 'bot' or 'user'."}, status=400)

    CompanyChat.objects.create(
        message=message,
        session=session,
        status=status,
        sender=sender,
        receiver=receiver,
        chunks=chunks
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
    preferred_language =  body.get('preferred_language', {}).get('value')

    access_token = request.headers.get("X-auth-token")
    decoded = jwt.decode(access_token, options={"verify_signature": False})
    print(decoded)
    if decoded:
        user_id = decoded.get('data', {}).get('id')
        first_name = decoded.get('data', {}).get('name')
        user_roles = decoded.get('roles', [])
    else:
        return JsonResponse({'message': f"Invalid access token"}, status=500)

    if not session:
        return Response({"error": "session is required."}, status=400)

    if not email:
        return Response({"error": "Email is required."}, status=400)

    try:
        company = Company.objects.get(slug='shikshalokamstaging')
    except Exception as e:
        return Response({"error": f"{e}"}, status=400)

    profile, created = Profile.objects.get_or_create(
        userid = user_id,
        defaults={
            'first_name': first_name,
            'email': email,
            'password': 'grit@123',
            'preferred_route': preferred_language,
            'company': company,
            "designation": user_roles
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

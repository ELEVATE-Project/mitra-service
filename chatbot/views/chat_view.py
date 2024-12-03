from rest_framework.decorators import api_view
from rest_framework.response import Response
from chatbot.models import CompanyChat, ChatSession, ChatStatus, Profile


@api_view(['POST'])
def save_chats_view(request):
    body = request.data
    chat_history = body.get('chat_history')
    session = body.get('session')

    if not chat_history or not session:
        return Response({"error": "chat_history and session are required."}, status=400)

    print("chat history: ", chat_history)

    company_chat_objects = []

    try:
        ai_user = Profile.objects.get(id=1)
    except Profile.DoesNotExist:
        return Response({"error": "AI profile not found."}, status=400)

    for chat in chat_history:
        message = chat.get('message')
        created_at = chat.get('created_at')
        status = chat.get('status', 'COMPLETED')
        role = chat.get('role')

        if not message or not session:
            return Response({
                "error": "Each chat must have 'message' and 'session' fields."
            }, status=400)

        if role == 'bot':
            sender = ai_user
            receiver = None
        elif role == 'user':
            sender = None
            receiver = ai_user
        else:
            return Response({"error": "Invalid role. Must be 'bot' or 'user'."}, status=400)

        company_chat_objects.append(CompanyChat(
            message=message,
            session=session,
            status=status,
            created_at=created_at,
            sender=sender,
            receiver=receiver
        ))

    CompanyChat.objects.bulk_create(company_chat_objects)

    return Response({
        'status': 'ok',
        'message': 'Chats saved successfully!'
    }, status=200)


@api_view(['POST'])
def create_chatsession(request):
    body = request.data
    session = body.get('session')

    if not session:
        return Response({"error": "session is required."}, status=400)

    c, created = ChatSession.objects.get_or_create(
        session=session,
        session_status=ChatStatus.IN_PROGRESS
    )

    return Response({
        'status': 'ok',
        'message': 'Chatsession created!' if created else 'Chatsession already exists!',
        'chatsession': {
            'session': c.session,
            'session_status': c.session_status
        }
    }, status=200)

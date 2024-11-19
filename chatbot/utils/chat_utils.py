from chatbot.models import Profile


def format_message_as_per_openai_format(chats, prompt=None):
    ai_user = Profile.objects.get(id=1)
    messages = []
    if prompt:
        messages.append({
            'role': 'system',
            'content': prompt
        })
    for chat in chats:
        if chat.receiver == ai_user:
            messages.append({
                'role': 'user',
                'content': chat.message
            })
        else:
            messages.append({
                'role': 'assistant',
                "content": chat.message
            })
    return messages

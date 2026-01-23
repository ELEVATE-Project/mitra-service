import json
import tempfile

from chatbot.models import ChatSession, ChatType, CompanyChat


def get_target_sessions(session_id=None):
    qs = ChatSession.objects.filter(
        session_type=ChatType.ParentPerceptionSurvey
    )

    if not session_id:
        return qs

    if isinstance(session_id, list):
        return qs.filter(session__in=session_id)

    return qs.filter(session=session_id)


def get_chat_text(chat):
    if chat.translated_message:
        return chat.translated_message.strip()

    if chat.message:
        return chat.message.strip()

    return ""


def extract_location_from_chats(chat_session):
    chats = CompanyChat.objects.filter(
        session=chat_session.session,
        receiver=1
    ).order_by("created_at")[:2]

    state = ""
    district = ""

    for chat in chats:
        text = get_chat_text(chat)
        if not text:
            continue

        if not state:
            state = text.lower()
            continue

        if not district:
            district = text.lower()

    if state and district:
        return f"{state} {district}"

    return ""


def extract_ip_location(chat_session):
    other_params = chat_session.other_params or {}
    ip_data = other_params.get("ip_address", {})

    ip_city = ip_data.get("ipCity", "")
    ip_state = ip_data.get("ipState", "")

    parts = [p for p in [ip_state, ip_city] if p]
    return " ".join(parts)


def build_location_response(chat_session):
    return {
        "session_id": chat_session.session,
        "user_chat_location": extract_location_from_chats(chat_session),
        "ip_location": extract_ip_location(chat_session),
    }


def get_parent_perception_location_metadata(session_id=None):
    sessions = get_target_sessions(session_id)

    results = []
    for chat_session in sessions:
        results.append(build_location_response(chat_session))

    return results


def save_parent_perception_location_to_temp_file(session_id=None):

    results = get_parent_perception_location_metadata(session_id)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False
    ) as temp_file:
        json.dump(results, temp_file, indent=2)
        temp_file_path = temp_file.name

    return temp_file_path

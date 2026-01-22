from chatbot.models import ChatSession
from chatbot.models import ChatType


def build_user_chat_location(district: str = "", location: str = "") -> str:
    parts = []

    if district:
        parts.append(district.strip())

    if location and location.lower() not in district.lower():
        parts.append(location.strip())

    return " ".join(parts)


def get_parent_perception_location_metadata(session_id: str, ip_location: str = ""):
    chat_session = ChatSession.objects.filter(
        session=session_id,
        session_type=ChatType.ParentPerceptionSurvey
    ).first()

    if not chat_session:
        return None

    district = ""
    location = ""

    if hasattr(chat_session, "other_params") and chat_session.other_params:
        district = chat_session.other_params.get("district", "")
        location = chat_session.other_params.get("location", "")

    user_chat_location = build_user_chat_location(
        district=district,
        location=location
    )

    if not user_chat_location:
        user_chat_location = ip_location

    return {
        "session_id": chat_session.session,
        "user_chat_location": user_chat_location,
        "ip_location": ip_location
    }

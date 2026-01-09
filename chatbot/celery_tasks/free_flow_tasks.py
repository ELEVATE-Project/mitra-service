from celery import shared_task
from chatbot.services.free_flow.free_flow_service import FreeFlowService
import logging

logger = logging.getLogger('django')


@shared_task
def get_free_flow_response(channel_name, session_id, profile_id, route, bot_route):
    """
    Celery task for free-flow streaming responses using OpenAI Responses API.
    
    This task runs in a separate Celery worker process and:
    1. Fetches conversation history and bot configuration from database
    2. Calls OpenAI Responses API with file_search tool for RAG
    3. Streams response chunks back to the WebSocket via channel layer
    4. Saves complete response to database
    
    Args:
        channel_name: Unique WebSocket channel identifier (e.g., "specific.websocket!abc123")
        session_id: Chat session ID
        profile_id: User profile ID
        route: Language route (e.g., 'en', 'hi')
        bot_route: Bot route identifier
    
    Returns:
        str: Success message when streaming completes
    """
    logger.info(f"Free flow task started for session {session_id}, channel {channel_name}")
    
    service = FreeFlowService()
    service.process_and_stream(
        channel_name=channel_name,
        session_id=session_id,
        profile_id=profile_id,
        route=route,
        bot_route=bot_route
    )
    
    logger.info(f"Free flow task completed for session {session_id}")
    return "Free flow streaming completed"

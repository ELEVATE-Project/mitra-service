from celery import shared_task

from chatbot.services.core.bot_service_factory import BotServiceFactory
from chatbot.services.core.orchestrator import ChatOrchestrator
import logging

logger = logging.getLogger('django')


# Purpose: Celery task that drives the full LLM response pipeline for a chat turn.
#          Runs in a separate worker process — decouples the slow LLM call from the WebSocket consumer.
#          Pushes the bot response back to the client via Redis channel layer using channel_name.
# Inputs:  channel_name — WebSocket channel to push response to; session_id, profile_id, route — conversation context;
#          bot_type — always 'common' for ws/common/; bot_route — CompanyBot.route
# Side effects: DB reads (session, profile, bot config), LLM API call, channel layer push
@shared_task
def get_flow_response(channel_name, session_id, profile_id, route, bot_type, bot_route):
    print(f"bot_type is {bot_type} and bot_route is {bot_route}")
    bot_strategy = BotServiceFactory.create_bot_service(
        bot_type=bot_type, route=bot_route
    )
    orchestrator = ChatOrchestrator(bot_strategy=bot_strategy)
    return orchestrator.process_chat_request(
        channel_name=channel_name, session_id=session_id, profile_id=profile_id,
        language=route
    )

"""
Free Flow Service

Service layer for handling free-flow conversations with OpenAI Responses API.
This service runs in Celery workers and handles:
- Fetching conversation history from database
- Calling LLM with RAG (file_search tool)
- Streaming responses back via channel layer
- Saving complete responses to database
"""

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from chatbot.llm_models.llm_script import handle_openai_response_api
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.models import ChatStatus, Profile, CompanyBot, CompanyChat
from chatbot.utils.chat_utils import get_guided_chat
import logging
import json

channel_layer = get_channel_layer()
logger = logging.getLogger('django')


class FreeFlowService:
    """
    Service for handling free-flow streaming responses.
    
    This service is called from Celery workers and uses synchronous code
    (which is fine in Celery). It sends responses back to the WebSocket
    via the channel layer using the channel_name identifier.
    """
    
    def process_and_stream(self, channel_name, session_id, profile_id, route, bot_route):
        """
        Process user message and stream LLM response back via channel layer.
        
        This method:
        1. Fetches data from database (sync - OK in Celery)
        2. Formats messages for OpenAI
        3. Calls handle_openai_response_api() synchronously
        4. For each chunk, sends via channel_layer.send() to the WebSocket
        5. Saves complete response to database
        
        Args:
            channel_name: WebSocket channel identifier (e.g., "specific.websocket!abc123")
            session_id: Chat session ID
            profile_id: User profile ID
            route: Language route
            bot_route: Bot route identifier
        """
        try:
            logger.info(f"Processing free-flow for session {session_id}, channel {channel_name}")
            
            # 1. Fetch data from database (sync is OK in Celery)
            profile = None
            if profile_id:
                profile = Profile.objects.filter(id=profile_id).first()
            
            # Get company bot configuration
            if profile:
                company_bot = CompanyBot.objects.filter(company=profile.company, route=bot_route).first()
            else:
                company_bot = CompanyBot.objects.filter(route=bot_route).first()
            
            if not company_bot:
                logger.error(f"Company bot not found for route: {bot_route}")
                self._send_error(channel_name, "Bot configuration not found")
                return
            
            # Get conversation history
            all_chats = CompanyChat.objects.filter(session=session_id).order_by('created_at')
            
            # Apply history limit if configured
            if company_bot.chat_history_limit:
                chat_count = all_chats.count()
                if chat_count > company_bot.chat_history_limit:
                    skip_count = chat_count - company_bot.chat_history_limit
                    company_chats = list(all_chats[skip_count:])
                else:
                    company_chats = list(all_chats)
            else:
                company_chats = list(all_chats)
            
            logger.info(f"Fetched {len(company_chats)} chat messages for history")
            
            # 2. Format messages for OpenAI using get_guided_chat
            messages = get_guided_chat(
                company_bot=company_bot,
                company_chats=company_chats,
                intro=None  # No intro for free-flow
            )
            
            # 3. Prepare system prompt
            system_prompt = company_bot.context
            
            # Convert to list format for Responses API
            system_prompt = [{'role': 'system', 'content': system_prompt}]
            
            # 4. Parse tools from company_bot.tool_context
            tools = None
            if company_bot.tool_context:
                try:
                    tools = json.loads(company_bot.tool_context)
                    logger.info(f"Loaded tools from company_bot.tool_context: {len(tools) if isinstance(tools, list) else 'object'}")
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error(f"Error parsing company_bot.tool_context: {e}")
            
            # 5. Stream response from OpenAI Responses API
            accumulated_response = ""
            finish_reason = None

            stream = company_bot.stream if hasattr(company_bot, 'stream') else True
            
            logger.info(f"Starting LLM {'streaming' if stream else 'call'} for session {session_id}")
            
            # Call LLM synchronously (this is fine in Celery worker)
            for chunk_data in handle_openai_response_api(
                messages=messages,
                system_prompt=system_prompt,
                max_token=company_bot.max_token if company_bot.max_token else 2048,
                temperature=company_bot.bot_temperature if company_bot.bot_temperature is not None else 0.0,
                company_bot=company_bot,
                top_p=company_bot.filter_score if company_bot.filter_score else None,
                tool_choice="auto",
                tools=tools,
                stream=stream
            ):
                content = chunk_data.get('content', '')
                finish_reason = chunk_data.get('finish_reason')
                error = chunk_data.get('error')
                
                if error:
                    logger.error(f'Streaming error: {error}')
                    self._send_error(channel_name, "Error processing your request")
                    return
                
                if content:
                    accumulated_response += content
                    # Send chunk via channel layer to WebSocket
                    self._send_chunk(channel_name, content, finish_reason)
                
                if finish_reason:
                    logger.info(f"Streaming completed with finish_reason: {finish_reason}")
                    break
            
            # 6. Save complete response to database
            if accumulated_response:
                save_in_company_db(
                    session_id=session_id,
                    profile_id=profile_id,
                    initiated_by='AI',
                    message=accumulated_response,
                    chunks=None,
                    status=ChatStatus.IN_PROGRESS,
                    stage='FREE_FLOW'
                )
                
                logger.info(f'Completed streaming response, length: {len(accumulated_response)} chars')
            else:
                logger.warning(f'No response accumulated for session {session_id}')
                
        except Exception as e:
            logger.error(f'Error in process_and_stream: {e}', exc_info=True)
            self._send_error(channel_name, "An error occurred processing your message")
    
    def _send_chunk(self, channel_name, content, finish_reason):
        """
        Send a chunk via channel layer to the WebSocket.
        
        Uses async_to_sync wrapper to call the async channel layer from sync code.
        The message type "chat.message" gets converted to chat_message() method call.
        
        Args:
            channel_name: Target WebSocket channel
            content: Chunk content to send
            finish_reason: OpenAI finish reason (stop, length, etc.)
        """
        try:
            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "chat.message",  # → calls chat_message() in consumer
                    "text": {
                        "msg": content,
                        "source": "bot",
                        "type": "chunk",
                        "finish_reason": finish_reason
                    },
                },
            )
        except Exception as e:
            # Don't crash if WebSocket disconnected - log and continue
            logger.warning(f"Failed to send chunk to channel {channel_name}: {e}")
    
    def _send_error(self, channel_name, error_msg):
        """
        Send error message via channel layer to the WebSocket.
        
        Args:
            channel_name: Target WebSocket channel
            error_msg: Error message to display to user
        """
        try:
            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "chat.message",
                    "text": {
                        "msg": error_msg,
                        "source": "bot",
                        "type": "error",
                        "finish_reason": "error"
                    },
                },
            )
        except Exception as e:
            logger.error(f"Failed to send error to channel {channel_name}: {e}")

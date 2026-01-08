import json
import traceback
import asyncio
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.consumers.async_base_consumer import AsyncBaseConsumer
from chatbot.models import ChatStatus, ChatSession, Profile, CompanyBot, CompanyChat
from chatbot.llm_models.llm_script import handle_openai_response_api
from chatbot.utils.chat_utils import format_message_as_per_openai_format
import logging
from channels.db import database_sync_to_async
import jwt

logger = logging.getLogger('django')


class FreeFlowConsumer(AsyncBaseConsumer):
    """
    WebSocket consumer for free-flow conversation using OpenAI Responses API.
    Unlike other consumers, this bypasses the state machine architecture and enables
    direct streaming conversations with file_search for vector store RAG.
    
    Uses OpenAI Responses API (client.responses.create) which supports file_search tool.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = None
        self.profile_id = None
        self.route = None
        self.bot_route = None
        self.company_bot = None
        self.flow_name = None
        self.ip_address = None
        self.access_token = None
        self.vector_store_id = None  # For file_search capability with Responses API

    async def disconnect(self, code):
        try:
            logger.info(f"Free-flow websocket closed with code: %s", code)
        except Exception as e:
            logger.error('Disconnect Error: %s', e, exc_info=True)
        finally:
            await super().disconnect(code)

    async def receive(self, text_data):
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type', None)
            company_chat_status = None
            
            if message_type == 'authenticate':
                # Handle authentication
                self.session_id = text_data_json.get('sessionid')
                self.profile_id = text_data_json.get('profileid')
                self.route = text_data_json.get('route', 'en')
                self.bot_route = text_data_json.get('bot_route')
                self.flow_name = text_data_json.get('flow_name', 'free_flow')
                self.ip_address = text_data_json.get('address')
                self.access_token = text_data_json.get('access_token')
                self.vector_store_id = text_data_json.get('vector_store_id')  # Optional

                profile = await self.get_profile(self.profile_id)
                logger.info(
                    f"Free-flow channel_name: %s, session_id: %s, profile_id: %s, route: %s, vector_store_id: %s",
                    self.channel_name, self.session_id, self.profile_id, self.route, self.vector_store_id
                )

                user_id = await self.handle_access_token(self.access_token)
                self.company_bot = await self.get_company_bot(profile, self.bot_route)

                # Create chat session asynchronously
                await self.create_chat_session(
                    self.session_id, profile, self.company_bot, self.ip_address, user_id
                )
                
                # Send acknowledgment
                await self.send(text_data=json.dumps({
                    "text": {
                        "msg": "Connected to free-flow chat with Responses API file_search",
                        "source": "system",
                        "type": "connection_ack",
                        "vector_store_enabled": bool(self.vector_store_id)
                    }
                }))
                
            else:
                # Handle regular chat messages
                user_message = text_data_json.get('text')
                if not user_message:
                    logger.warning("Received empty message")
                    return
                
                # Determine chat status
                company_chat_status = await self.determine_company_chat_status_async(
                    session_id=self.session_id, profile_id=self.profile_id, route=self.bot_route
                )
                
                # Echo user message back
                await self.send(text_data=json.dumps({
                    "text": {
                        "msg": user_message,
                        "source": "user"
                    }
                }))
                
                # Save user message to database
                await database_sync_to_async(save_in_company_db)(
                    session_id=self.session_id,
                    profile_id=self.profile_id,
                    initiated_by='User',
                    message=user_message,
                    chunks=None,
                    status=company_chat_status,
                    translated_message=None,
                    audio_base64=text_data_json.get('asr_audio'),
                    stage='FREE_FLOW'
                )
                
                logger.info(
                    f"Processing free-flow message - channel_name: %s, session_id: %s",
                    self.channel_name, self.session_id
                )
                
                # Process the message and stream response
                await self.process_and_stream_response(user_message)

        except Exception as e:
            logger.error('Receive Error: %s', e, exc_info=True)
            traceback.print_exc()
            await self.send(text_data=json.dumps({
                "text": {
                    "msg": "An error occurred processing your message",
                    "source": "system",
                    "type": "error"
                }
            }))

    async def connect(self):
        try:
            logger.info(f"Attempting to connect to free-flow websocket")
            await super().connect()
        except Exception as e:
            logger.error('Connect Error: %s', e, exc_info=True)
            traceback.print_exc()

    async def process_and_stream_response(self, user_message):
        """
        Process user message and stream LLM response chunks back to client.
        """
        try:
            # Get conversation history
            company_chats = await self.get_conversation_history()
            
            # Format messages for OpenAI
            messages = await database_sync_to_async(format_message_as_per_openai_format)(
                chats=company_chats,
                intro=None  # No intro for free-flow
            )
            # Prepare system prompt for retrieval-only behavior
            system_prompt = None
            if self.company_bot and self.company_bot.context:
                system_prompt = self.company_bot.context
            else:
                # Default retrieval-only prompt for RAG
                system_prompt = (
                    "You are a retrieval-only assistant.\n"
                    "Answer the user ONLY using information found in the vector store.\n"
                    "If the answer is not present in the retrieved documents, reply exactly:\n"
                    "'I do not have enough information in the knowledge base to answer this.'"
                )
            
            # Convert to list format for Responses API
            system_prompt = [{
                'role': 'system',
                'content': system_prompt
            }]
            
            # Prepare vector store IDs for file_search tool
            vector_store_ids = None
            if self.vector_store_id:
                vector_store_ids = [self.vector_store_id]
                logger.info(f"Using vector store for RAG: {self.vector_store_id}")
            else:
                logger.warning("⚠️ No vector_store_id provided - responses won't use file_search")
            
            # Stream response from OpenAI Responses API with file_search
            accumulated_response = ""
            finish_reason = None
            
            # Run streaming in thread pool to avoid blocking
            def stream_generator():
                return handle_openai_response_api(
                    messages=messages,
                    system_prompt=system_prompt,
                    max_token=self.company_bot.max_token if self.company_bot else 2048,
                    temperature=self.company_bot.bot_temperature if self.company_bot else 0.0,  # 0.0 for deterministic retrieval
                    company_bot=self.company_bot,
                    vector_store_ids=vector_store_ids,
                    top_p=self.company_bot.filter_score if self.company_bot else None,
                    tool_choice="auto"  # Use "required" to force file_search
                )
            
            # Execute streaming in thread pool
            for chunk_data in await asyncio.to_thread(stream_generator):
                content = chunk_data.get('content', '')
                finish_reason = chunk_data.get('finish_reason')
                error = chunk_data.get('error')
                
                if error:
                    logger.error('Streaming error: %s', error)
                    await self.send(text_data=json.dumps({
                        "text": {
                            "msg": "I apologize, but I encountered an error processing your request.",
                            "source": "bot",
                            "type": "error",
                            "finish_reason": "error"
                        }
                    }))
                    return
                
                if content:
                    accumulated_response += content
                    # Send chunk to client
                    await self.send(text_data=json.dumps({
                        "text": {
                            "msg": content,
                            "source": "bot",
                            "type": "chunk",
                            "finish_reason": finish_reason
                        }
                    }))
                
                if finish_reason:
                    break
            
            # Save complete bot response to database
            if accumulated_response:
                await database_sync_to_async(save_in_company_db)(
                    session_id=self.session_id,
                    profile_id=self.profile_id,
                    initiated_by='AI',
                    message=accumulated_response,
                    chunks=None,
                    status=ChatStatus.IN_PROGRESS,
                    stage='FREE_FLOW'
                )
                
                logger.info('Completed streaming response, length: %d', len(accumulated_response))
            
        except Exception as e:
            logger.error('Error in process_and_stream_response: %s', e, exc_info=True)
            traceback.print_exc()
            await self.send(text_data=json.dumps({
                "text": {
                    "msg": "I apologize, but I encountered an error. Please try again.",
                    "source": "bot",
                    "type": "error"
                }
            }))

    @database_sync_to_async
    def get_profile(self, profile_id):
        if not profile_id:
            return None
        return Profile.objects.filter(id=profile_id).first()

    @database_sync_to_async
    def handle_access_token(self, access_token):
        user_id = None
        try:
            if access_token:
                decoded = jwt.decode(access_token, options={"verify_signature": False})
                if decoded:
                    user_id = decoded.get('data', {}).get('id')
        except Exception as e:
            logger.error('Access token Decode Error: %s', e, exc_info=True)
        logger.info("User_id: %s", user_id)
        return user_id

    @database_sync_to_async
    def get_company_bot(self, profile, route):
        if profile:
            return CompanyBot.objects.get(company=profile.company, route=route)
        else:
            return CompanyBot.objects.get(route=route)

    @database_sync_to_async
    def create_chat_session(self, session_id, profile, company_bot, ip_address, user_id):
        cs, cs_created = ChatSession.objects.get_or_create(
            session=session_id,
            defaults={
                'profile': profile,
                'current_step': 1,  # Not used in free-flow but required
                'language': self.route,
                'company_bot': company_bot,
                'session_status': ChatStatus.IN_PROGRESS,
                'user_id': user_id,
                'session_type': self.flow_name
            }
        )
        logger.info(f"Chat session for free-flow: %s %s", cs, cs_created)

        if not cs_created:
            if cs.language != self.route:
                cs.language = self.route

            other_params = cs.other_params or {}
            other_params["ip_address"] = ip_address
            cs.other_params = other_params
            cs.save(update_fields=["language", "other_params"])
        else:
            cs.other_params = {"ip_address": ip_address}
            cs.save(update_fields=["other_params"])

        return cs

    @database_sync_to_async
    def get_conversation_history(self):
        """
        Get conversation history limited by company_bot.chat_history_limit.
        Returns CompanyChat queryset ordered by creation time.
        """
        all_chats = CompanyChat.objects.filter(
            session=self.session_id
        ).order_by('created_at')
        
        # Apply history limit if configured
        if self.company_bot and self.company_bot.chat_history_limit:
            # Get last N messages based on history limit
            chat_count = all_chats.count()
            if chat_count > self.company_bot.chat_history_limit:
                # Skip older messages
                skip_count = chat_count - self.company_bot.chat_history_limit
                return list(all_chats[skip_count:])
        
        return list(all_chats)

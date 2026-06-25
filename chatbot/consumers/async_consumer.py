import json
import traceback
import os
from django.conf import settings
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.consumers.async_base_consumer import AsyncBaseConsumer
from chatbot.models import ChatStatus, ChatSession, Profile, CompanyBot, Voice, VoiceType, ChatType, CompanyChat, \
    TextConversionType, CompanyBotTypeChoices
from chatbot.celery_tasks.flow_tasks import get_flow_response
from chatbot.models.company_models import CompanyStateMachine
from chatbot.utils.audio_provider_utils import text_translate_provider
import logging
from channels.db import database_sync_to_async
from chatbot.utils.transliterate_utils import transliterate_text
import jwt

logger = logging.getLogger('django')
PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY")


class AsyncSocketConsumer(AsyncBaseConsumer):
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
        self.background_tasks = set()

    async def disconnect(self, code):
        try:
            logger.info(f"Websocket closed with code: %s", code)
        except Exception as e:
            logger.error('Disconnect Error: %s', e, exc_info=True)
        finally:
            # Don't call self.close() here - let the parent handle that
            await super().disconnect(code)

    # Every WebSocket frame from the client lands here.
    # The client MUST send type='authenticate' first before sending any chat messages —
    # that first message sets up session/profile/bot context on this consumer instance.
    # After authentication, all subsequent messages are treated as chat turns.
    async def receive(self, text_data):
        try:
            logger.info(f"Received text data via common websocket: {text_data}")
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type', None)
            company_chat_status = None
            if message_type == 'authenticate':
                # Store conversation context on the consumer instance so it is available
                # for every subsequent message without hitting the DB again.
                self.session_id = text_data_json.get('sessionid')
                self.profile_id = text_data_json.get('profileid')
                self.route = text_data_json.get('route')      # language code, e.g. 'en', 'hi'
                self.bot_route = text_data_json.get('bot_route')  # identifies which CompanyBot to use
                self.flow_name = text_data_json.get('flow_name')
                self.ip_address = text_data_json.get('address')

                profile = await self.get_profile(self.profile_id)
                logger.info(
                    f"channel_name: %s, session_id: %s, profile_id: %s, route: %s",
                    self.channel_name, self.session_id, self.profile_id, self.route
                )

                user_id = await self.handle_access_token(self.access_token)

                self.company_bot = await self.get_company_bot(profile, self.bot_route)

                await self.create_chat_session(
                    self.session_id, profile, self.company_bot, self.ip_address, user_id
                )
            else:
                if not self.session_id or not self.bot_route:
                    error_msg = "Authentication required. Please send authentication message first with type='authenticate', sessionid, profileid, route, and bot_route."
                    logger.error(f"Unauthenticated message attempt: {error_msg}")
                    await self.channel_layer.send(
                        self.channel_name,
                        {
                            "type": "chat_message",
                            "text": {
                                "msg": error_msg,
                                "source": "system",
                                "error": True
                            },
                        },
                    )
                    return
                company_chat_status = await self.determine_company_chat_status_async(
                    session_id=self.session_id, profile_id=self.profile_id, route=self.bot_route
                )
                # Echo the user's message back through the channel layer so the frontend
                # receives it via the same unified message stream as bot responses.
                await self.channel_layer.send(
                    self.channel_name,
                    {
                        "type": "chat_message",
                        "text": {"msg": text_data_json["text"], "source": "user"},
                    },
                )

            translated_message = None
            if self.route != 'en' and text_data_json and text_data_json.get('text'):
                # Translate non-English input to English so the LLM always receives English text.
                # The original message is preserved separately for display and audit.
                translated_message = await self.translate_message(text_data_json['text'])

            if message_type != 'authenticate' and text_data_json and text_data_json.get('text'):
                chat_session = await database_sync_to_async(
                    lambda: ChatSession.objects.filter(session=self.session_id).order_by('-created_at').first()
                )()

                # Capture the human-readable stage name (e.g. "CHALLENGES") for analytics —
                # storing the step number alone makes historical records hard to interpret.
                current_stage = None
                if chat_session and self.company_bot and self.company_bot.bot_type == CompanyBotTypeChoices.STATE_MACHINE:
                    try:
                        state_machine = await database_sync_to_async(
                            lambda: CompanyStateMachine.objects.get(
                                company_bot=self.company_bot, step=chat_session.current_step
                            )
                        )()
                        if state_machine:
                            current_stage = state_machine.name
                    except CompanyStateMachine.DoesNotExist:
                        logger.error(
                            f"CompanyStateMachine not found for bot_id={self.company_bot.id}, "
                            f"step={chat_session.current_step}. "
                            f"Please create state machines in admin panel."
                        )
                await database_sync_to_async(save_in_company_db)(
                    session_id=self.session_id, profile_id=self.profile_id, initiated_by='User',
                    message=text_data_json['text'], chunks=None, status=company_chat_status,
                    translated_message=translated_message, audio_base64=text_data_json.get('asr_audio'),
                    stage=current_stage
                )

            logger.info(
                f"channel_name: %s, session_id: %s, profile_id: %s, route: %s",
                self.channel_name, self.session_id, self.profile_id, self.route
            )

            if message_type != 'authenticate':
                # Hand off to Celery so the LLM call doesn't block this async consumer.
                # The worker pushes the bot reply back via channel layer using channel_name as the address.
                # This consumer returns immediately — the response arrives as a separate event.
                get_flow_response.delay(
                    self.channel_name, self.session_id, self.profile_id, self.route,
                    'common', self.bot_route
                )

        except Exception as e:
            logger.error('Receive Error: %s', e, exc_info=True)
            traceback.print_exc()

    async def connect(self):
        try:
            logger.info(f"Attempting to connect to websocket")
            await super().connect()
        except Exception as e:
            logger.error('Connect Error: %s', e, exc_info=True)
            traceback.print_exc()

    @database_sync_to_async
    def get_profile(self, profile_id):
        if not profile_id:
            return None
        return Profile.objects.filter(id=profile_id).first()

    # Extracts user_id from the JWT so the session can be linked to an authenticated Elevate user.
    # access_token is optional — anonymous/guest users proceed with user_id=None.
    @database_sync_to_async
    def handle_access_token(self, access_token):
        user_id = None

        if access_token:
            print("Access Token: ", access_token)

            try:
                decoded = jwt.decode(
                    access_token,
                    PUBLIC_KEY,
                    algorithms=["HS256"]
                )
                print("Decoded JWT: ", decoded)
                if decoded:
                    user_id = decoded.get("data", {}).get("id")
            except Exception as e:
                logger.error('JWT Decode Error: %s', e, exc_info=True)
                print(f"JWT Decode Error: {e}")

        logger.info("User_id: %s", user_id)
        return user_id

    @database_sync_to_async
    def get_company_bot(self, profile, route):
        if profile:
            return CompanyBot.objects.get(company=profile.company, route=route)
        else:
            return CompanyBot.objects.get(route=route)

    # get_or_create a ChatSession for this connection.
    # If the session already exists (e.g. user reconnected), only language and ip_address are
    # refreshed — step and status are preserved so the conversation resumes mid-flow.
    @database_sync_to_async
    def create_chat_session(self, session_id, profile, company_bot, ip_address, user_id):
        step_number = 1
        if profile and profile.first_name and profile.first_name != '':
            try:
                # Profile already has a name, so skip the name-collection steps at the start
                # of the state machine and jump directly to CHALLENGES.
                challenges_step = CompanyStateMachine.objects.get(
                    company_bot=self.company_bot, name="CHALLENGES"
                )
                step_number = challenges_step.step
            except CompanyStateMachine.DoesNotExist:
                step_number = 1
        cs, cs_created = ChatSession.objects.get_or_create(
            session=session_id,
            defaults={
                'profile': profile,
                'current_step': step_number,
                'language': self.route,
                'company_bot': company_bot,
                'session_status': ChatStatus.IN_PROGRESS,
                'user_id': user_id,
                'session_type': self.flow_name
            }
        )
        logger.info(f"Chatsession: %s %s", cs, cs_created)

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

    # Converts the user's regional-language message to English for LLM consumption.
    # Which conversion to use depends on the state machine step config:
    #   TRANSLITERATE — converts script only (e.g. Hindi in Roman chars → Devanagari → English phonetic)
    #   TRANSLATE     — converts meaning (full language translation via configured provider)
    # Falls back to the original message if the provider is not configured or the call fails.
    @database_sync_to_async
    def translate_message(self, message):
        try:
            if not self.company_bot:
                return message

            voice_provider = Voice.objects.filter(
                company_bot=self.company_bot,
                type=VoiceType.TextToText,
                language=self.route
            ).first()

            if not voice_provider:
                return message

            chat_session = ChatSession.objects.filter(session=self.session_id).first()
            if not chat_session:
                return message

            state_machine = CompanyStateMachine.objects.get(
                company_bot=self.company_bot, step=chat_session.current_step
            )

            if state_machine and state_machine.text_conversion_type == TextConversionType.TRANSLITERATE:
                transliterate_voice_provider = Voice.objects.filter(
                    company_bot=self.company_bot,
                    type=VoiceType.Transliterate,
                    language=self.route
                ).first()
                if not transliterate_voice_provider:
                    logger.warning(
                        'No Transliterate Voice row for company_bot=%s language=%s, falling back to translate',
                        self.company_bot, self.route
                    )
                else:
                    response = transliterate_text(
                        voice_provider=transliterate_voice_provider, source_language=self.route, target_language='en',
                        message_body=message, is_sentence=True,
                        session_id=self.session_id, profile_id=self.profile_id
                    )
                    if response and response.get('content'):
                        content = response.get('content')
                        if content and isinstance(content, list) and len(content) > 0:
                            content = content[0]
                        return content
            else:
                response = text_translate_provider(
                    voice_provider=voice_provider, message_body=message,
                    target_language='en', source_language=self.route,
                    session_id=self.session_id, profile_id=self.profile_id
                )

                if response.get('status') == 200:
                    return response.get('content')
                else:
                    return message

        except Exception as e:
            logger.error('Translation Error: %s', e, exc_info=True)
            return message

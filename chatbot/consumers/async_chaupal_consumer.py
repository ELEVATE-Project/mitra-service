import asyncio
import json
import traceback
from asgiref.sync import async_to_sync
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.consumers.async_base_consumer import AsyncBaseConsumer
from chatbot.models import ChatStatus, ChatSession, Profile, CompanyBot, Voice, VoiceType, ChatType, CompanyChat
from chatbot.celery_tasks.chaupal_tasks import get_chaupal_response
from chatbot.models.company_models import CompanyStateMachine
from chatbot.utils.audio_provider_utils import text_translate_provider
import logging
from channels.db import database_sync_to_async

from chatbot.utils.transliterate_utils import transliterate_text

logger = logging.getLogger('django')


class AsyncShikshalokamChaupalConsumer(AsyncBaseConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = None
        self.profile_id = None
        self.route = None
        self.company_bot = None
        self.background_tasks = set()

    # async def send_ping(self):
    #     while True:
    #         await asyncio.sleep(25)  # Send ping every 25 seconds
    #         if self.scope["type"] == "websocket":
    #             try:
    #                 # Send ping frame
    #                 await self.send({"type": "websocket.ping"})  # Empty ping
    #                 # Or send a text ping
    #                 # await self.send(text_data=json.dumps({"type": "ping"}))
    #             except Exception as e:
    #                 print(f"Error sending ping: {e}")
    #                 break

    async def disconnect(self, code):
        try:
            print(f'Websocket closed with code: {code}')
        except Exception as e:
            logger.error('Disconnect Error: %s', e, exc_info=True)
            print(f"Disconnect Error: {e}")
        finally:
            # Don't call self.close() here - let the parent handle that
            await super().disconnect(code)

    async def receive(self, text_data):
        try:
            print(text_data)
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type', None)

            if message_type == 'authenticate':
                self.session_id = text_data_json.get('sessionid')
                self.profile_id = text_data_json.get('profileid')
                self.route = text_data_json.get('route')

                profile = await self.get_profile(self.profile_id)
                print(f"Authenticated with session_id: {self.session_id}, profile_id: {self.profile_id}, "
                      f"route: {self.route}")

                self.company_bot = await self.get_company_bot(profile, '/shikshalokam_chaupal')

                # Create chat session asynchronously
                await self.create_chat_session(self.session_id, profile, self.company_bot)
            else:
                company_chat_status = await self.determine_company_chat_status_async(
                    session_id=self.session_id, profile_id=self.profile_id, route='/shikshalokam_chaupal'
                )
                print("COMPANY CHAT STATUS: ", company_chat_status)
                await self.channel_layer.send(
                    self.channel_name,
                    {
                        "type": "chat_message",
                        "text": {"msg": text_data_json["text"], "source": "user"},
                    },
                )

            translated_message = None
            if self.route != 'en' and text_data_json and text_data_json.get('text'):
                translated_message = await self.translate_message(text_data_json['text'])

            if message_type != 'authenticate' and text_data_json and text_data_json.get('text'):
                # Use a task for database operations
                await database_sync_to_async(save_in_company_db)(
                    session_id=self.session_id, profile_id=self.profile_id, initiated_by='User',
                    message=text_data_json['text'], chunks=None, status=company_chat_status,
                    translated_message=translated_message, audio_base64=text_data_json.get('asr_audio')
                )

            print(f"channel_name: {self.channel_name}, session_id: {self.session_id}, profile_id: "
                  f"{self.profile_id}, route: {self.route}")

            if message_type != 'authenticate':
                # Start the Celery task but don't wait for it
                get_chaupal_response.delay(
                    self.channel_name, self.session_id, self.profile_id, self.route
                )

        except Exception as e:
            logger.error('Receive Error: %s', e, exc_info=True)
            print(f"Receive Error: {e}")
            traceback.print_exc()

    async def connect(self):
        try:
            print('Attempting to connect to websocket')
            await super().connect()
        except Exception as e:
            logger.error('Connect Error: %s', e, exc_info=True)
            print(f"Connect Error: {e}")
            traceback.print_exc()

    @database_sync_to_async
    def get_profile(self, profile_id):
        if not profile_id:
            return None
        return Profile.objects.filter(id=profile_id).first()

    @database_sync_to_async
    def get_company_bot(self, profile, route):
        if profile:
            return CompanyBot.objects.get(company=profile.company, route=route)
        else:
            return CompanyBot.objects.get(route=route)

    @database_sync_to_async
    def create_chat_session(self, session_id, profile, company_bot):
        cs, cs_created = ChatSession.objects.get_or_create(
            session=session_id,
            defaults={
                'profile': profile,
                'current_step': 1,
                'company_bot': company_bot,
                'session_status': ChatStatus.IN_PROGRESS,
                'session_type': ChatType.shikshaChaupal
            }
        )
        print(cs, cs_created)
        return cs

    @database_sync_to_async
    def translate_message(self, message):
        try:
            if not self.company_bot:
                return message

            voice_provider = Voice.objects.filter(
                company_bot=self.company_bot,
                type=VoiceType.TextToText
            ).first()

            if not voice_provider:
                return message

            chat_session = ChatSession.objects.filter(session=self.session_id).first()
            if not chat_session:
                return message

            state_machine = CompanyStateMachine.objects.get(
                company_bot=self.company_bot, step=chat_session.current_step
            )

            if state_machine and state_machine.name in ['INTRODUCTION', 'ORGANIZATION']:
                transliterate_bot = CompanyBot.objects.filter(route='/transliterate').first()
                return transliterate_text(
                    transliterate_bot, self.route, 'en', message
                )
            else:
                response = text_translate_provider(
                    voice_provider=voice_provider, message_body=message,
                    target_language='en', source_language=self.route
                )
                if response.get('status') == 200:
                    return response.get('content')
                else:
                    return message
        except Exception as e:
            logger.error('Translation Error: %s', e, exc_info=True)
            return message

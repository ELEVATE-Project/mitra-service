import json
from asgiref.sync import async_to_sync
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.consumers.base_consumer import BaseConsumer
from chatbot.models import ChatStatus, ChatSession, Profile, CompanyBot, Voice, VoiceType, ChatType, CompanyChat
from chatbot.celery_tasks.oneshot_guest_tasks import get_oneshot_guest_response
from chatbot.models.company_models import CompanyStateMachine
from chatbot.utils.audio_provider_utils import text_translate_provider
import jwt
import logging

from chatbot.utils.transliterate_utils import transliterate_text

logger = logging.getLogger('django')


class OneShotGuestConsumer(BaseConsumer):

    try:
        session_id = None
        profile_id = None
        project_id = None
        access_token = None
        route = None
        company_bot = None

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

                company_chats = CompanyChat.objects.filter(session=self.session_id).order_by('created_at')

                if (state_machine and state_machine.name in ['INTRODUCTION', 'ORGANIZATION', 'DESIGNATION'] and
                        company_chats and len(company_chats)>1):
                    transliterate_voice_provider = Voice.objects.filter(
                        company_bot=self.company_bot,
                        type=VoiceType.Transliterate,
                        language=self.route
                    ).first()
                    response = transliterate_text(
                        voice_provider=transliterate_voice_provider, source_language=self.route, target_language='en',
                        message_body=message, is_sentence=True
                    )
                    print("Trans response: ", response)
                    if response and response.get('content'):
                        content = response.get('content')
                        print("Trans content: ", content)
                        if content and isinstance(content, list) and len(content) > 0:
                            content = content[0]
                        return content
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

        def disconnect(self, code):
            chat_session = ChatSession.objects.filter(session=self.session_id)
            if chat_session.exists():
                c = chat_session[0]
            else:
                c = ChatSession(session=self.session_id)
            c.save_title(self.route)
            company_chat_status = self.determine_company_chat_status(
                session_id=self.session_id, profile_id=self.profile_id, is_disconnected=True, route='/oneshot_guest'
            )
            print("COMPANY CHAT STATUS: ", company_chat_status)
            self.update_last_chat_status(chat_status=company_chat_status)
            self.close()

        def receive(self, text_data):
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type', None)

            if message_type == 'authenticate':
                self.session_id = text_data_json.get('sessionid')
                self.profile_id = text_data_json.get('profileid')
                self.project_id = text_data_json.get('projectid')
                self.access_token = text_data_json.get('access_token')
                self.route = text_data_json.get('route')
                profile = Profile.objects.filter(id=self.profile_id).first()
                print(f"Authenticated with session_id: {self.session_id}, profile_id: {self.profile_id}, "
                      f"route: {self.route}")
                if profile:
                    self.company_bot = CompanyBot.objects.get(company=profile.company, route='/oneshot_guest')
                else:
                    self.company_bot = CompanyBot.objects.get(route='/oneshot_guest')

                if self.access_token:
                    decoded = jwt.decode(self.access_token, options={"verify_signature": False})
                    print(decoded)
                    if decoded:
                        user_id = decoded.get('data', {}).get('id')
                    else:
                        user_id = None
                else:
                    user_id = None
                print("User_id: ", user_id)

                # chat session create (session, profile)
                cs, cs_created = ChatSession.objects.get_or_create(
                    session=self.session_id,
                    defaults={
                        'profile': profile,
                        'current_step': 1,
                        'company_bot': self.company_bot,
                        'session_status': ChatStatus.IN_PROGRESS,
                        'project_id': self.project_id,
                        'user_id': user_id,
                        'session_type': ChatType.oneStepReflection
                    }
                )
                print(cs, cs_created)
            else:
                company_chat_status = self.determine_company_chat_status(
                    session_id=self.session_id, profile_id=self.profile_id, route='/oneshot_guest'
                )
                print("COMPANY CHAT STATUS: ", company_chat_status)
                async_to_sync(self.channel_layer.send)(
                    self.channel_name,
                    {
                        "type": "chat_message",
                        "text": {"msg": text_data_json["text"], "source": "user"},
                    },
                )

                translated_message = None

                if self.route != 'en'  and text_data_json and text_data_json.get('text') :
                    translated_message = self.translate_message(message=text_data_json['text'])

                if message_type != 'authenticate' and text_data_json and text_data_json.get('text'):
                    save_in_company_db(
                        session_id=self.session_id, profile_id=self.profile_id, initiated_by='User',
                        message=text_data_json['text'], chunks=None, status=company_chat_status,
                        translated_message=translated_message, audio_base64=text_data_json.get('asr_audio')
                    )

                print(f"channel_name: {self.channel_name}, session_id: {self.session_id}, profile_id: "
                      f"{self.profile_id}, route: {self.route}")

                if message_type != 'authenticate':
                    get_oneshot_guest_response.delay(
                        self.channel_name, self.session_id, self.profile_id, self.route
                    )
    except Exception as e:
            logger.error('Error: %s', e, exc_info=True)
            print(f"Error: {e}")

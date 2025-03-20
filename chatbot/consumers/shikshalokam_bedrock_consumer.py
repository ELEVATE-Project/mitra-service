import json
import traceback
from asgiref.sync import async_to_sync
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.consumers.base_consumer import BaseConsumer
from chatbot.models import ChatStatus, ChatSession, Profile, CompanyBot, Voice, VoiceType, ChatType
from chatbot.celery_tasks.shikshalokam_bedrock_tasks import get_shikshalokam_bedrock_response
from chatbot.utils.audio_provider_utils import text_translate_provider


class ShikshalokamBedrockConsumer(BaseConsumer):

    session_id = None
    profile_id = None
    route = None

    def disconnect(self, code):
        print('Websocket closed')
        chat_session = ChatSession.objects.filter(session=self.session_id)
        if chat_session.exists():
            c = chat_session[0]
        else:
            c = ChatSession(session=self.session_id)
        c.save_title(self.route)
        company_chat_status = self.determine_company_chat_status(
            session_id=self.session_id, profile_id=self.profile_id, is_disconnected=True, route='/'
        )
        print("COMPANY CHAT STATUS: ", company_chat_status)
        self.update_last_chat_status(chat_status=company_chat_status)
        self.close()

    def receive(self, text_data):
        print(text_data)
        text_data_json = json.loads(text_data)
        message_type = text_data_json.get('type', None)

        try:
            if message_type == 'authenticate':
                self.session_id = text_data_json.get('sessionid')
                self.profile_id = text_data_json.get('profileid')
                self.route = text_data_json.get('route')
                profile = Profile.objects.get(id=self.profile_id)
                print(f"Authenticated with session_id: {self.session_id}, profile_id: {self.profile_id}, "
                      f"route: {self.route}")

                # chat session create (session, profile)
                cs, cs_created = ChatSession.objects.get_or_create(
                    session=self.session_id,
                    defaults={
                        'profile': profile,
                        'current_step': 1,
                        'company_bot': CompanyBot.objects.get(company=profile.company, route='/'),
                        'session_status': ChatStatus.IN_PROGRESS,
                        'session_type': ChatType.guidedReflection
                    }
                )
                print(cs, cs_created)
            else:
                company_chat_status = self.determine_company_chat_status(
                    session_id=self.session_id, profile_id=self.profile_id, route='/'
                )
                print("COMPANY CHAT STATUS: ", company_chat_status)
                async_to_sync(self.channel_layer.send)(
                    self.channel_name,
                    {
                        "type": "chat_message",
                        "text": {"msg": text_data_json["text"], "source": "user"},
                    },
                )

            if self.route != 'en':
                profile = Profile.objects.get(id=self.profile_id)
                company_bot = CompanyBot.objects.filter(company=profile.company, route='/').first()
                voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()

                response = text_translate_provider(
                    voice_provider=voice_provider, message_body=text_data_json['text'], target_language='en',
                    source_language=self.route
                )
                if response.get('status') == 200:
                    translated_message = response.get('content')
                else:
                    translated_message = text_data_json['text']
            else:
                translated_message = None

            print("text_data_json: ", text_data_json)
            if text_data_json and text_data_json['text']:
                save_in_company_db(self.session_id, self.profile_id, 'User', text_data_json['text'],
                                   None, company_chat_status, translated_message)

            print(f"channel_name: {self.channel_name}, session_id: {self.session_id}, profile_id: "
                  f"{self.profile_id}, route: {self.route}")

            get_shikshalokam_bedrock_response.delay(
                self.channel_name, self.session_id, self.profile_id, self.route
            )
        except Exception as e:
            print(e)
            traceback.print_exc()

    def connect(self):
        try:
            print('Attempting to connect to websocket')
            super().connect()
        except Exception:
            traceback.print_exc()

import json
from asgiref.sync import async_to_sync
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.consumers.base_consumer import BaseConsumer
from chatbot.models import ChatStatus, ChatSession, Profile, CompanyBot, Voice, VoiceType
from chatbot.celery_tasks.one_shot_bedrock_tasks import get_one_shot_bedrock_response
from chatbot.utils.audio_provider_utils import text_translate_provider


class OneShotBedrockConsumer(BaseConsumer):

    session_id = None
    profile_id = None
    route = None
    language = None

    def disconnect(self, code):
        chat_session = ChatSession.objects.filter(session=self.session_id)
        if chat_session.exists():
            c = chat_session[0]
        else:
            c = ChatSession(session=self.session_id)
        c.save_title(self.language)
        company_chat_status = self.determine_company_chat_status(
            session_id=self.session_id, profile_id=self.profile_id, is_disconnected=True
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
            self.route = text_data_json.get('route')
            self.language = text_data_json.get('language')
            profile = Profile.objects.get(id=self.profile_id)
            print(f"Authenticated with session_id: {self.session_id}, profile_id: {self.profile_id}, "
                  f"route: {self.route} and language: {self.language}")

            # chat session create (session, profile)
            cs, cs_created = ChatSession.objects.get_or_create(
                session=self.session_id,
                defaults={
                    'profile': profile,
                    'current_step': 1,
                    'company_bot': CompanyBot.objects.get(company=profile.company, route='/'),
                    'session_status': ChatStatus.IN_PROGRESS
                }
            )
            print(cs, cs_created)
        else:
            company_chat_status = self.determine_company_chat_status(
                session_id=self.session_id, profile_id=self.profile_id
            )
            print("COMPANY CHAT STATUS: ", company_chat_status)
            async_to_sync(self.channel_layer.send)(
                self.channel_name,
                {
                    "type": "chat_message",
                    "text": {"msg": text_data_json["text"], "source": "user"},
                },
            )

            if self.route != '/':
                company_bot = CompanyBot.objects.filter(route='/oneshot_bot').first()
                voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()

                response = text_translate_provider(
                    voice_provider=voice_provider, message_body=text_data_json['text'], target_language='en',
                    source_language='hi'
                )
                if response.get('status') == 200:
                    translated_message = response.get('content')
                else:
                    translated_message = text_data_json['text']
            else:
                translated_message = None
            save_in_company_db(self.session_id, self.profile_id, 'User', text_data_json['text'],
                               None, company_chat_status, translated_message)
            get_one_shot_bedrock_response.delay(self.channel_name, self.session_id, self.profile_id, self.route)

import json
import traceback

from asgiref.sync import async_to_sync
from chatbot.celery_tasks.common_chat_tasks import save_in_company_db
from chatbot.consumers.base_consumer import BaseConsumer
from chatbot.models import ChatStatus, ChatSession, Profile, CompanyBot
from chatbot.translate.ai4Bharat.text_to_text import call_ai4bharat_translation_api
from chatbot.celery_tasks.shikshalokam_bedrock_tasks import get_shikshalokam_bedrock_response
import jwt


class ShikshalokamBedrockConsumer(BaseConsumer):

    session_id = None
    profile_id = None
    project_id = None
    access_token = None
    route = None

    def disconnect(self, code):
        print('Websocket closed')
        chat_session = ChatSession.objects.filter(session=self.session_id)
        if chat_session.exists():
            c = chat_session[0]
        else:
            c = ChatSession(session=self.session_id)
        c.save_title()
        company_chat_status = self.determine_company_chat_status(
            session_id=self.session_id, profile_id=self.profile_id, is_disconnected=True
        )
        print("COMPANY CHAT STATUS: ", company_chat_status)
        self.update_last_chat_status(chat_status=company_chat_status)
        self.close()

    def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message_type = text_data_json.get('type', None)

        try:
            if message_type == 'authenticate':
                self.session_id = text_data_json.get('sessionid')
                self.profile_id = text_data_json.get('profileid')
                self.project_id = text_data_json.get('projectid')
                self.access_token = text_data_json.get('access_token')
                self.route = text_data_json.get('route')
                profile = Profile.objects.get(id=self.profile_id)
                print(f"Authenticated with session_id: {self.session_id}, profile_id: {self.profile_id}, "
                      f"route: {self.route}")
                print(f"Received project_id: {self.project_id} and access_token: {self.access_token}")
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
                        'company_bot': CompanyBot.objects.get(company=profile.company, route='/'),
                        'session_status': ChatStatus.IN_PROGRESS,
                        'project_id': self.project_id,
                        'user_id': user_id,
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
                    translated_message = call_ai4bharat_translation_api(
                        message_body=text_data_json['text'], target_language='en',
                        source_language='hi'
                    )
                else:
                    translated_message = None
                save_in_company_db(self.session_id, self.profile_id, 'User', text_data_json['text'],
                                   None, company_chat_status, translated_message)

                print(f"channel_name: {self.channel_name}, session_id: {self.session_id}, profile_id: {self.profile_id}, "
                      f"route: {self.route}")

                get_shikshalokam_bedrock_response.delay(self.channel_name, self.session_id, self.profile_id, self.route)
        except Exception as e:
            print(e)
            traceback.print_exc()

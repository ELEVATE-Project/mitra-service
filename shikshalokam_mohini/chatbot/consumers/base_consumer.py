import json
from channels.generic.websocket import WebsocketConsumer
from chatbot.models import ChatSession


class BaseConsumer(WebsocketConsumer):
    def connect(self):
        self.accept()

    def disconnect(self, code):
        session_id = self.scope['cookies']['sessionid']
        chat_session = ChatSession.objects.filter(session=session_id)
        if chat_session.exists():
            c = chat_session[0]
        else:
            c = ChatSession(session=session_id)
        c.save_title()
        self.close()

    def receive(self, text_data):
        raise NotImplementedError("receive method must be implemented in subclass")

    def chat_message(self, event):
        text = event["text"]
        self.send(text_data=json.dumps({"text": text}))

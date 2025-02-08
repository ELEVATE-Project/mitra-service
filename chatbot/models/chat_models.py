import datetime
import json
from django.db import models
from chatbot.models import CompanyChat, Profile, CompanyBot, ChatStatus, LLMModel, Voice, VoiceType
from chatbot.llm_models.llm_script import handle_bedrock_model
from chatbot.utils.audio_provider_utils import text_translate_provider


class ChatSession(models.Model):
    session = models.CharField(max_length=255, unique=True)
    profile = models.ForeignKey(Profile, on_delete=models.DO_NOTHING, null=True, blank=True)
    company_bot = models.ForeignKey(CompanyBot, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    current_step = models.IntegerField(null=True, blank=True)
    session_context = models.JSONField(null=True, blank=True)
    session_status = models.CharField(max_length=20, choices=ChatStatus.choices, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save_title(self, language='en'):
        company_chats = CompanyChat.objects.filter(session=self.session).order_by('created_at')
        messages = self._get_bedrock_format_message(chats=company_chats)
        tool_to_use = self._get_bedrock_tools()
        company_bot = CompanyBot.objects.filter(route='/mohini_title').first()
        prompt = self._get_prompt(company_bot=company_bot)

        json_output = self._handle_bedrock_model(
            prompt=prompt, messages=messages, tools=tool_to_use, company_bot=company_bot
        )
        if json_output:
            if isinstance(json_output, str):
                json_output = json.loads(json_output)
            output_title = json_output.get('title')
            if language != 'en':
                voice_provider = Voice.objects.filter(company_bot=company_bot, type=VoiceType.TextToText).first()

                response = text_translate_provider(
                    voice_provider=voice_provider, message_body=output_title, target_language=language,
                    source_language='en'
                )
                if response.get('status') == 200:
                    output_title = response.get('content')
        else:
            output_title = 'Project'

        self.title = output_title
        self.save()

    def _get_prompt(self, company_bot):
        prompt = company_bot.context

        return [{'text': prompt}]

    def _get_bedrock_format_message(self, chats):
        ai_user = Profile.objects.get(id=1)
        messages = []
        for chat in chats:
            if chat.receiver == ai_user:
                user_message = chat.message
                if chat.translated_message is not None and chat.translated_message != '':
                    user_message = chat.translated_message
                messages.append({
                    'role': 'user',
                    'content': [{'text': user_message}]
                })
            else:
                messages.append({
                    'role': 'assistant',
                    "content": [{'text': chat.message}]
                })
        return messages

    def _determine_model(self):
        model = LLMModel.GPT4_O
        if self.company_bot:
            model = self.company_bot.llm_model if self.company_bot.llm_model else model
        return model

    def _handle_bedrock_model(self, prompt, messages, tools, company_bot):
        print("Using Bedrock")
        response_json = handle_bedrock_model(
            system_prompt=prompt, messages=messages, model_name=company_bot.llm_model,
            temperature=company_bot.bot_temperature, max_token=company_bot.max_token,
            tools=tools
        )

        if response_json:
            print("pre: ", response_json)
            if response_json.get('parameters'):
                response_json = response_json.get('parameters')
            elif response_json.get('input'):
                response_json = response_json.get('input')
        print("post: ", response_json)
        return response_json

    def _get_bedrock_tools(self):
        tool = {
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": "generate_conversation_title",
                            "description": "Generate a concise 3-4 word title for the conversation.",
                            "inputSchema": {
                                "json": {
                                    "type": "object",
                                    "properties": {
                                        "title": {
                                            "type": "string",
                                            "description": (
                                                "Summary of the conversation. "
                                                "Output should be in JSON format with a 'title' field containing a concise, 3-4 word title."
                                            )
                                        }
                                    },
                                    "required": ["title"]
                                }
                            }
                        }
                    }
                ]
            }
        }
        return tool

    def _parse_response(self, response):
        response_str = str(response.content, encoding="utf-8")
        response_json = json.loads(response_str)
        response_content = response_json['choices'][0]['message']['content']
        cleaned_content = (response_content.replace('\n', '').replace('\t', '').replace('\r', '')
                           .replace('\\n', '').replace('\\t', '').replace('\\r', ''))
        return json.loads(cleaned_content)

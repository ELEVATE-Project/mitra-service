from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from chatbot.models import RouteLanguageChoices
from chatbot.translate.ai4Bharat.text_to_text import call_ai4bharat_translation_api


channel_layer = get_channel_layer()


def translate_and_send_message(accumulated_message, current_channel_name, current_step_number, finish_reason, route):

    if route != '/':
        target_language_code = get_language_code_from_route(route)
        print("target_language_code: ", target_language_code)
        translated_messages = call_ai4bharat_translation_api(
            message_body=accumulated_message, target_language=target_language_code,
            source_language='en'
        )
        if translated_messages is None:
            translated_messages = call_ai4bharat_translation_api(
                message_body=accumulated_message, target_language=target_language_code,
                source_language='en'
            )
        if translated_messages:
            translated_messages+= " "
        else:
            translated_messages = accumulated_message

        async_to_sync(channel_layer.send)(
            current_channel_name,
            {
                "type": "chat.message",
                "text": {
                    "msg": translated_messages,
                    "source": "bot",
                    "finish_reason": finish_reason,
                    "step": current_step_number
                },
            },
        )
        print("Translated message: ", translated_messages)
        return translated_messages
    else:
        print("Sending  accumulated_message: ", accumulated_message)
        async_to_sync(channel_layer.send)(
            current_channel_name,
            {
                "type": "chat.message",
                "text": {
                    "msg": accumulated_message,
                    "source": "bot",
                    "finish_reason": finish_reason,
                    "step": current_step_number
                },
            },
        )
        return None

def get_language_code_from_route(route):
    for choice in RouteLanguageChoices:
        if choice.label == route:
            return choice.value
    return RouteLanguageChoices.ENGLISH.value

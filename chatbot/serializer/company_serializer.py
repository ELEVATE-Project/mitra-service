from rest_framework import serializers
from chatbot.models.base_models import CompanyBot, Company
from chatbot.models.company_models import CompanyStateMachine
from chatbot.translate.ai4Bharat.text_to_text import call_ai4bharat_translation_api


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ('name', 'slug')


class CompanyBotSerializer(serializers.ModelSerializer):
    company = CompanySerializer(read_only=True)
    statemachine_length = serializers.SerializerMethodField()

    class Meta:
        model = CompanyBot
        fields = '__all__'

    def get_statemachine_length(self, obj):
        return obj.companystatemachine_set.count()

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        request = self.context.get('request')
        target_language = request.query_params.get('target_language') if request else 'en'

        if target_language and target_language != 'en':
            translated_name = self.translate_name_with_bhashini(
                name=instance.name, target_language=target_language
            )
            representation['name'] = translated_name

        return representation

    def translate_name_with_bhashini(self, name, target_language):
        translated_content = call_ai4bharat_translation_api(
            source_language='en', target_language=target_language, message_body=name
        )
        return translated_content if translated_content else name


class CompanyStateMachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyStateMachine
        fields = '__all__'

from rest_framework import serializers

from chatbot.models import BotVernacular
from chatbot.models.base_models import CompanyBot, Company
from chatbot.models.company_models import CompanyStateMachine


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ('name', 'slug')


class CompanyBotSerializer(serializers.ModelSerializer):
    company = CompanySerializer(read_only=True)

    class Meta:
        model = CompanyBot
        fields = '__all__'


class CompanyStateMachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyStateMachine
        fields = '__all__'


class BotVernacularSerializer(serializers.ModelSerializer):
    company_bot = CompanyBotSerializer(read_only=True)

    class Meta:
        model = BotVernacular
        fields = '__all__'
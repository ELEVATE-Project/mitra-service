from rest_framework import serializers
from chatbot.models import BotVernacular
from chatbot.models.company_models import CompanyStateMachine, CompanyBot, Company, ImageConfiguration


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


class CompanyStateMachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyStateMachine
        fields = '__all__'


class BotVernacularSerializer(serializers.ModelSerializer):
    company_bot = CompanyBotSerializer(read_only=True)
    default_name = serializers.SerializerMethodField()

    class Meta:
        model = BotVernacular
        fields = '__all__'

    def get_default_name(self, obj):
        english_bot = BotVernacular.objects.filter(company_bot=obj.company_bot, language='en').first()
        return english_bot.name if english_bot else ""


class ImageConfigurationSerializer(serializers.ModelSerializer):
    """Serializer for ImageConfiguration model."""
    image_size_mb = serializers.SerializerMethodField()

    class Meta:
        model = ImageConfiguration
        fields = ('id', 'name', 'max_images', 'image_size', 'image_size_mb')
        read_only_fields = ('id',)

    def get_image_size_mb(self, obj):
        """Convert image size from bytes to MB for easier reading."""
        return round(obj.image_size / 1048576, 2)
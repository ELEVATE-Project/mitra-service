from rest_framework import serializers
from chatbot.models import BotVernacular
from chatbot.models.company_models import CompanyStateMachine, CompanyBot, Company, ImageConfiguration, Flow


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

    # Purpose: Converts raw image_size (bytes) to MB for client display.
    def get_image_size_mb(self, obj):
        return round(obj.image_size / 1048576, 2)


class FlowLanguagesSerializer(serializers.ModelSerializer):
    """Serializer for Flow languages."""
    
    class Meta:
        model = Flow
        fields = ('flow_route', 'languages')
        read_only_fields = ('flow_route', 'languages')


class ChildFlowSerializer(serializers.ModelSerializer):
    """Serializer for child flow minimal information."""
    
    class Meta:
        model = Flow
        fields = ('flow_route', 'flow_name', 'active')
        read_only_fields = ('flow_route', 'flow_name', 'active')


class FlowConnectionInfoSerializer(serializers.ModelSerializer):
    """Serializer for Flow connection information."""
    bot_route = serializers.CharField(source='bot.route', read_only=True)
    isParentFlow = serializers.SerializerMethodField()
    children_flows = serializers.SerializerMethodField()
    image_config = serializers.SerializerMethodField()
    
    class Meta:
        model = Flow
        fields = ('flow_route', 'websocket_url', 'bot_route', 'isParentFlow', 'children_flows', 'image_config', 'create_story')
        read_only_fields = ('flow_route', 'websocket_url', 'bot_route', 'isParentFlow', 'children_flows', 'image_config')
    
    # Purpose: Returns True if this flow has child flows — signals the client to show a flow-selection UI.
    def get_isParentFlow(self, obj):
        return obj.child_flows.exists()

    # Purpose: Returns serialized child flows; relies on prefetch_related('child_flows') in the view
    #          query to avoid an extra DB hit here.
    def get_children_flows(self, obj):
        if obj.child_flows.exists():
            return ChildFlowSerializer(obj.child_flows.all(), many=True).data
        return []

    # Purpose: Returns image upload constraints for this flow; None if no config is attached.
    def get_image_config(self, obj):
        if obj.image_config:
            return ImageConfigurationSerializer(obj.image_config).data
        return None
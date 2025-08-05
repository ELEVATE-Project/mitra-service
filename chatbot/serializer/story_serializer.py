from rest_framework import serializers
from chatbot.models import Story, StoryMedia, StoryTranslation
from chatbot.serializer.profile_serializer import ProfileSerializer


class TranslationMixin:
    """Mixin to handle story translations in serializers"""

    def apply_translation(self, data, instance):
        """Apply translation to story data based on request language"""
        request = self.context.get('request')
        if not request:
            return data

        language = request.query_params.get('language', 'en')

        if language == 'en':
            return data

        try:
            translation = instance.translations.get(language=language)

            data['title'] = translation.title
            if translation.content:
                data['content'] = translation.content
            if translation.blurb:
                data['blurb'] = translation.blurb
            if translation.tweet:
                data['tweet'] = translation.tweet
            if translation.objective:
                data['objective'] = translation.objective
            if translation.action_steps:
                data['action_steps'] = translation.action_steps
            if translation.impact:
                data['impact'] = translation.impact
            if translation.micro_improvement:
                data['micro_improvement'] = translation.micro_improvement

            if translation.translated_other_params and data['other_params']:
                data['other_params'].update(translation.translated_other_params)
            elif translation.translated_other_params:
                data['other_params'] = translation.translated_other_params

        except StoryTranslation.DoesNotExist:
            pass

        return data


class StoryMediaCreateSerializer(serializers.ModelSerializer):
    public_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = StoryMedia
        exclude = ('base64_str', )

    def get_public_url(self, obj):
        return obj.get_public_url()


class StoryMediaRetrieveSerializer(serializers.ModelSerializer):
    public_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = StoryMedia
        fields = '__all__'

    def get_public_url(self, obj):
        return obj.get_public_url()


class StoryCreateSerializer(serializers.ModelSerializer):
    story_media = StoryMediaCreateSerializer(many=True, read_only=True)

    class Meta:
        model = Story
        exclude = ('formatted_content', )


class StoryRetrieveSerializer(TranslationMixin, serializers.ModelSerializer):
    story_media = StoryMediaRetrieveSerializer(many=True, read_only=True)

    def to_representation(self, instance):
        """Override to return translated content based on language"""
        data = super().to_representation(instance)
        return self.apply_translation(data, instance)

    class Meta:
        model = Story
        fields = '__all__'


class StoryFullSerializer(TranslationMixin, serializers.ModelSerializer):
    story_media = StoryMediaCreateSerializer(many=True, read_only=True)
    author = ProfileSerializer(read_only=True)

    def to_representation(self, instance):
        """Override to return translated content based on language"""
        data = super().to_representation(instance)
        return self.apply_translation(data, instance)

    class Meta:
        model = Story
        fields = '__all__'

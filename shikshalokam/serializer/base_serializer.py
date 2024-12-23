import json

from rest_framework import serializers

from chatbot.serializer.profile_serializer import ProfileSerializer
from shikshalokam.models.base_model import Project, Task, Category, ProjectTemplate, Evidence


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'


class ProjectTemplateSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    class Meta:
        model = ProjectTemplate
        fields = '__all__'


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = '__all__'


class EvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Evidence
        fields = '__all__'


class ProjectSerializer(serializers.ModelSerializer):
    project_template = ProjectTemplateSerializer(read_only=True)
    task = TaskSerializer(many=True, read_only=True)
    author = ProfileSerializer(read_only=True)
    categories = serializers.ListField(child=serializers.JSONField(), required=False)
    recommended_for = serializers.ListField(child=serializers.JSONField(), required=False)

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        for field in ['categories', 'recommended_for']:
            try:
                representation[field] = json.loads(getattr(instance, field)) if getattr(instance, field) else []
            except json.JSONDecodeError:
                representation[field] = []
        return representation

    def to_internal_value(self, data):
        internal_value = super().to_internal_value(data)
        for field in ['categories', 'recommended_for']:
            if field in data:
                internal_value[field] = json.dumps(data[field])
        return internal_value

    class Meta:
        model = Project
        fields = '__all__'

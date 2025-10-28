from django.contrib import admin
from shikshalokam.models import LearningResources


@admin.register(LearningResources)
class LearningResourcesAdmin(admin.ModelAdmin):
    list_display = ('project', 'name', 'created_at')
    list_filter = ('created_at', 'project',)

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        obj.save()
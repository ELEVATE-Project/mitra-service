from django.contrib import admin
from shikshalokam.models.project_vernacular_model import ProjectVernacular


@admin.register(ProjectVernacular)
class ProjectVernacularAdmin(admin.ModelAdmin):
    list_display = ('project', 'language', 'created_at')
    list_filter = ('created_at', 'project', 'language',)

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        obj.save()

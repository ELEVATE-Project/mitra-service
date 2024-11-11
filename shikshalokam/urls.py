from django.urls import path
from shikshalokam.views.story_views import create_story_from_project_view

app_name = "shikshalokam"

urlpatterns = [
    path('create-story/', create_story_from_project_view, name='create story'),
]

from django.urls import path

from shikshalokam.views.project_views import ProjectListCreateView, duplicate_project_view, project_ingestion_view
from shikshalokam.views.story_views import create_story_from_project_view
from shikshalokam.views.wishlist_views import wishlist_project_view

app_name = "shikshalokam"

urlpatterns = [
    path('create-story/', create_story_from_project_view, name='create story'),
    path('project/', ProjectListCreateView.as_view(), name='project-list-create'),
    path('start-project/', duplicate_project_view, name='start-project'),
    path('ingest-data/', project_ingestion_view, name='ingest-data'),
    path('wishlist-project/', wishlist_project_view, name='wishlist-project'),

]

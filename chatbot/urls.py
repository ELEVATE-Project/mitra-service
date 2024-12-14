from chatbot.views.gotenberg_view import generate_pdf_view
from chatbot.views.profile_views import create_profile_views
from django.urls import path
from chatbot.views import api_views
from chatbot.views.bhashini_views import ai4bharat_text_speech, ai4bharat_asr, \
    ai4bharat_text_translation
from chatbot.views.chat_view import save_chats_view, create_chatsession
from chatbot.views.drf_views import CompanyChatListCreateView, CompanyChatRetrieveUpdateDestroyView, \
    CompanyBotListCreateView, CompanyBotRetrieveUpdateDestroyView, ProfileListCreateView, \
    ProfileRetrieveUpdateDestroyView, ChatSessionListCreateView, ChatSessionRetrieveUpdateDestroyView, \
    ChatSessionRetrieveUpdateDestroyViewSession
from chatbot.views.mitra_views import paraphrase_view, generate_objectives_view, generate_action_list_view, \
    generate_title_view, create_project_view, update_project_status_view
from chatbot.views.recommendation import generate_recommendation
from chatbot.views.story_views import end_story, StoryListCreateView, StoryBySessionView, \
    StoryRetrieveUpdateDestroyView, story_recreate_view, StoryMediaListCreateView, StoryMediaRetrieveUpdateDestroyView
from shikshalokam.utils.project_utils import update_project_status_utils

app_name = "chatbot"

urlpatterns = [
    path('api/profile/', api_views.post_profile),
    path('api/generate-session/', api_views.generate_session_id, name='generate_session_id'),
    path('api/login/', api_views.login, name='login'),
    path('api/logout/', api_views.logout, name='logout'),

    path('api/end-story/', end_story, name='end-story'),


    path('api/ai4bharat/', ai4bharat_text_speech, name='ai4bharat_text_speech'),
    path('api/ai4bharat/asr', ai4bharat_asr, name='ai4bharat_asr'),
    path('api/ai4bharat/translate', ai4bharat_text_translation, name='ai4bharat_text_translation'),

    path('api/companychat/', CompanyChatListCreateView.as_view(), name='companychat-list-create'),
    path('api/companychat/<int:pk>/', CompanyChatRetrieveUpdateDestroyView.as_view(),
         name='companychat-retrieve-update-destroy'),

    path('api/companybot/', CompanyBotListCreateView.as_view(), name='companybot-list-create'),
    path('api/companybot/<int:pk>/', CompanyBotRetrieveUpdateDestroyView.as_view(),
         name='companybot-retrieve-update-destroy'),

    path('api/story/', StoryListCreateView.as_view(), name='story-list-create'),
    path('api/get-story/', StoryBySessionView.as_view(), name='story-by-session'),
    path('api/story/<int:pk>/', StoryRetrieveUpdateDestroyView.as_view(),
         name='story-retrieve-update-destroy'),
    path('api/story-re-create/', story_recreate_view, name='story_recreate_view'),

    path('api/storymedia/', StoryMediaListCreateView.as_view(), name='story-media-list-create'),
    path('api/storymedia/<int:pk>/', StoryMediaRetrieveUpdateDestroyView.as_view(),
         name='story-media-retrieve-update-destroy'),

    path('api/profileuser/', ProfileListCreateView.as_view(), name='profile-user-list-create'),
    path('api/profileuser/<int:pk>/', ProfileRetrieveUpdateDestroyView.as_view(),
         name='profile-user-retrieve-update-destroy'),

    path('api/chatsession/', ChatSessionListCreateView.as_view(), name='chatsession-list-create'),
    path('api/chatsession/<int:pk>/', ChatSessionRetrieveUpdateDestroyView.as_view(),
         name='chatsession-retrieve-update-destroy'),
    path('api/chatsession/<str:session>/', ChatSessionRetrieveUpdateDestroyViewSession.as_view(),
         name='chatsession-retrieve-update-destroy'),


    path('api/paraphrase/', paraphrase_view, name="paraphrase"),
    path('api/generate-objective/', generate_objectives_view, name="generate-objectives"),
    path('api/generate-action-list/', generate_action_list_view, name="generate-action-list"),
    path('api/generate-title/', generate_title_view, name="generate-title"),
    path('api/save-company-chat/', save_chats_view, name="save-company-chat"),
    path('api/create-chatsession/', create_chatsession, name="create-chatsession"),
    path('api/create-profile/', create_profile_views, name="create-profile"),
    path('api/create-project/', create_project_view, name="create-project"),
    path('api/generate-pdf/', generate_pdf_view, name='generate_pdf'),
    path('api/generate-recommendation/', generate_recommendation, name='generate-recommendation'),
    path('api/update-project-status/', update_project_status_view, name='update-project-status'),

]

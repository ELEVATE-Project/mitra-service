import django_filters
from rest_framework import generics
from rest_framework.decorators import authentication_classes
from chatbot.auth import ProfileJWTAuthentication
from chatbot.filter.drf_filter import ChatSessionProfileFilter
from chatbot.models import ChatSession
from chatbot.models.base_models import CompanyChat, CompanyBot, Profile
from chatbot.serializer.base_serializer import ChatSessionSerializer
from chatbot.serializer.company_serializer import CompanyBotSerializer
from chatbot.serializer.profile_serializer import ProfileSerializer, CompanyChatSerializer


class CompanyChatListCreateView(generics.ListCreateAPIView):
    queryset = CompanyChat.objects.all()
    serializer_class = CompanyChatSerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['message', 'sender', 'receiver', 'session', 'status']


class CompanyChatRetrieveUpdateDestroyView(generics.RetrieveUpdateAPIView):
    queryset = CompanyChat.objects.all()
    serializer_class = CompanyChatSerializer


class CompanyBotListCreateView(generics.ListCreateAPIView):
    queryset = CompanyBot.objects.all()
    serializer_class = CompanyBotSerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['name', 'company__name', 'llm_model', 'company__slug']


class CompanyBotRetrieveUpdateDestroyView(generics.RetrieveUpdateAPIView):
    queryset = CompanyBot.objects.all()
    serializer_class = CompanyBotSerializer


class ProfileListCreateView(generics.ListCreateAPIView):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['first_name', 'email', 'company__name', 'phone', 'company__slug']


class ProfileRetrieveUpdateDestroyView(generics.RetrieveUpdateAPIView):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer


class ChatSessionListCreateView(generics.ListCreateAPIView):
    queryset = ChatSession.objects.all()
    serializer_class = ChatSessionSerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend, ChatSessionProfileFilter]
    filterset_fields = ['session', 'retell_call_id', 'sqs_message_id']


class ChatSessionRetrieveUpdateDestroyView(generics.RetrieveUpdateAPIView):
    queryset = ChatSession.objects.all()
    serializer_class = ChatSessionSerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['session', 'twilio_call_id']


class ChatSessionRetrieveUpdateDestroyViewSession(generics.RetrieveUpdateAPIView):
    queryset = ChatSession.objects.all()
    serializer_class = ChatSessionSerializer
    lookup_field = 'session'

import traceback
from chatbot.models import Story, StoryMedia
from chatbot.serializer.story_serializer import StoryCreateSerializer, StoryRetrieveSerializer, \
    StoryMediaRetrieveSerializer, StoryFullSerializer
from chatbot.utils.media_utils import upload_to_cloud
from chatbot.utils.shikshalokam_story_utils import update_story_pdf
from chatbot.utils.story_utils import create_story_object
import django_filters
from rest_framework import generics, status
from rest_framework.decorators import api_view, authentication_classes
from chatbot.auth import ProfileJWTAuthentication
from rest_framework.response import Response
from chatbot.models.media_models import ProfileMedia
from chatbot.serializer.profile_serializer import ProfileMediaSerializer
from chatbot.utils.recreate_story_utils import re_create_story_object


@api_view(['POST'])
def end_story(request):
    try:
        profile_id = request.data['profile_id']
        session = request.data['session']
        language = request.data['language']
        print("profile_id:", profile_id)
        print("session:", session)
        print("language:", language)
        if profile_id is None or session is None:
            return Response({
                'status': 'error',
                'message': 'profile id or session or access_token is mandatory'
            }, status=400)
        else:
            id, content, error_msg = create_story_object(
                profile_id=profile_id, session=session, language=language
            )
            return Response({
                'status': 'ok',
                'message': 'Story created',
                'id': id,
                'content': content,
                'error_message': error_msg
            }, status=200)
    except Exception as e:
        print(e)
        traceback.print_exc()
        return Response({
            'status': 'error',
            'message': '',
            'error_message': f'{e}'
        }, status=500)


# @authentication_classes([ProfileJWTAuthentication])
class StoryListCreateView(generics.ListCreateAPIView):
    queryset = Story.objects.all()
    serializer_class = StoryCreateSerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['session', 'author']


@authentication_classes([ProfileJWTAuthentication])
class StoryRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Story.objects.all()
    serializer_class = StoryRetrieveSerializer

    def partial_update(self, request, *args, **kwargs):
        """
        Handle PATCH requests for partial updates.
        """
        print("Updating (PATCH)")
        return self.handle_update_logic(request, *args, **kwargs, is_partial=True)


    def handle_update_logic(self, request, *args, **kwargs):
        """
        Shared PATCH requests.
        """
        is_partial = kwargs.pop('is_partial', False)
        session_value = request.data.get('session')
        print("session_value: ", session_value)

        try:
            if is_partial:
                response = super().partial_update(request, *args, **kwargs)
                if response and response.status_code in [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT]:
                    print("response.data: ", response.data.get('session'))
                    update_story_pdf(session=session_value)

                return response
        except Exception as e:
            print("Error occurred: ", str(e))
            raise



# @authentication_classes([ProfileJWTAuthentication])
class StoryMediaListCreateView(generics.ListCreateAPIView):
    queryset = StoryMedia.objects.all()
    serializer_class = StoryMediaRetrieveSerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['story']

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def create(self, request, *args, **kwargs):
        """
        Handle POST requests (create).
        """
        print("Creating")
        session_value = request.data.get('session')
        access_token = request.data.get('access_token')
        print("session_value: ", session_value)
        print("access_token: ", access_token)
        try:
            response = super().create(request, *args, **kwargs)
            print("response: ", response)
            print("response status_code: ", response.status_code)
            update_story_pdf(session=session_value)
            # if response.status_code == status.HTTP_201_CREATED:
            #     upload_to_cloud(session_value=session_value, access_token=access_token, instance=response.data)
            return response

        except Exception as e:
            print("Error occurred: ", str(e))
            raise


# @authentication_classes([ProfileJWTAuthentication])
class StoryMediaRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = StoryMedia.objects.all()
    serializer_class = StoryMediaRetrieveSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def partial_update(self, request, *args, **kwargs):
        """
        Handle PATCH requests for partial updates.
        """
        print("Updating (PATCH)")
        return self.handle_update_logic(request, *args, **kwargs, is_partial=True)

    def update(self, request, *args, **kwargs):
        """
        Handle PUT requests for full updates.
        """
        print("Updating (PUT)")
        return self.handle_update_logic(request, *args, **kwargs, is_partial=False)

    def handle_update_logic(self, request, *args, **kwargs):
        """
        Shared logic for PUT and PATCH requests.
        """
        is_partial = kwargs.pop('is_partial', False)  # Safely extract the flag
        session_value = request.data.get('session')
        access_token = request.data.get('access_token')
        print("session_value: ", session_value)
        print("access_token: ", access_token)

        try:
            if is_partial:
                response = super().partial_update(request, *args, **kwargs)
            else:
                response = super().update(request, *args, **kwargs)

            print("response: ", response)
            print("response status_code: ", response.status_code)
            update_story_pdf(session=session_value)

            # if response.status_code in [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT]:
                # Pass response.data directly as the instance
                # upload_to_cloud(session_value=session_value, access_token=access_token, instance=response.data)

            return response
        except Exception as e:
            print("Error occurred: ", str(e))
            raise


@authentication_classes([ProfileJWTAuthentication])
class ProfileMediaListCreateView(generics.ListCreateAPIView):
    queryset = ProfileMedia.objects.all()
    serializer_class = ProfileMediaSerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['profile']

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


@authentication_classes([ProfileJWTAuthentication])
class ProfileMediaRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ProfileMedia.objects.all()
    serializer_class = ProfileMediaSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


@api_view(['POST'])
def story_recreate_view(request):
    profile_id = request.data.get('profile_id')
    session_id = request.data.get('session_id')
    print('profile_id: ', profile_id)
    print('session_id: ', session_id)
    if profile_id is None or session_id is None:
        return Response({'error': 'Profile ID and Session ID are required.'}, status=status.HTTP_400_BAD_REQUEST)

    story_id, story_content = re_create_story_object(profile_id, session_id)
    temp_json = {
        'id': story_id,
        'content': story_content
    }

    return Response({'message': temp_json}, status=status.HTTP_200_OK)


# @authentication_classes([ProfileJWTAuthentication])
class StoryBySessionView(generics.ListAPIView):
    serializer_class = StoryFullSerializer
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['session']

    def get_queryset(self):
        session_id = self.request.query_params.get('session')
        if session_id:
            return Story.objects.filter(session=session_id)
        return Story.objects.none()

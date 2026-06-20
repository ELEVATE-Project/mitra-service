import logging
import traceback
from django.contrib.auth.hashers import check_password
from rest_framework.response import Response
from rest_framework.decorators import api_view, authentication_classes
from chatbot.models import ProfileType
from chatbot.models.geo_models import ProfileAddress
from chatbot.models.auth_models import BlacklistedToken
from chatbot.models.company_models import Company, CompanyBot
from chatbot.models.profile_models import Profile
from chatbot.serializer.profile_serializer import ProfileSerializer
from django.http import JsonResponse
from django.contrib.sessions.backends.db import SessionStore
from rest_framework_simplejwt.tokens import RefreshToken
from chatbot.translate.ai4Bharat.transliterate import call_ai4bharat_transliterate_api
from chatbot.models.company_models import Flow

logger = logging.getLogger('django')


# Purpose: Creates a new anonymous server-side session and returns its key to the caller.
#          The key is used by the WebSocket client as an identity token in the
#          ws/common/ authenticate message, linking the socket to a ChatSession.
# Inputs:  request — Django HttpRequest (no body or query params required; method not enforced)
# Output:  JsonResponse {"sessionid": "<40-char random key>"} on success (HTTP 200);
#          no response body on DB failure (bare except swallows error → Django returns 500)
# Side effects: Inserts one row into the django_session table (empty session, future expiry)
# Failure conditions: DB unavailable — exception is swallowed; traceback printed to stdout
def generate_session_id(request):
    try:
        session = SessionStore()
        # create() persists the session to DB immediately; SessionStore() alone is just an in-memory object
        session.create()
        return JsonResponse({'sessionid': session.session_key})
    except Exception as e:
        # no return here — DB failure silently results in a 500 with no response body
        print('Exception is here')
        print(e)
        traceback.print_exc()



# Purpose: Create or update a Profile for a given company. Acts as an upsert:
#          updates if email+company match exists, returns existing if phone matches,
#          creates new otherwise. Optionally transliterates first_name into the target script.
# Inputs:  request.data — { email, company (slug), first_name?, preferred_route?,
#                            latest_flow (flow_route string)?, phone?, ...profile fields }
# Output:  Serialized Profile (password excluded) on success;
#          400 if email/company missing or data invalid;
#          404 if company or flow_route not found; 500 on unexpected error
# Side effects: May INSERT or UPDATE profile, profile_address, profile_media rows;
#               may call AI4Bharat transliteration API
@api_view(['POST'])
def post_profile(request):
    try:
        data = request.data
        if not ('email' in data and 'company' in data):
            return Response({
               'status': 'error',
               'message': 'email and subdomain/company are mandatory'
            }, status=400)
        company_slug = data.get('company')
        company = Company.objects.get(slug=company_slug)

        email = data['email']
        first_name = data.get('first_name', '')
        target_language = data.get('preferred_route', None)
        if first_name and first_name != '' and target_language:
            source_language='en'
            first_names = call_ai4bharat_transliterate_api(
                source_language=source_language, target_language=target_language, message_body=first_name
            )
            if first_names and isinstance(first_names, dict):
                first_names = first_names.get('content', [])
            if first_names and isinstance(first_names, list) and len(first_names) > 0:
                data['first_name'] = first_names[0]

        flow_route = data.get('latest_flow', None)
        # client sends latest_flow as a flow_route string; serializer expects a FK id
        if flow_route:
            flow = Flow.objects.values('id').get(flow_route=flow_route)
            data['latest_flow'] = flow.get('id')

        profile = Profile.objects.filter(email=email, company=company).first()
        if profile:
            serializer = ProfileSerializer(profile, data=data)
        else:
            phone = data.get('phone', None)
            if phone:
                profile = Profile.objects.filter(phone=phone, company=company)
                if len(profile) > 0:
                    # phone match found — return existing profile without applying any updates
                    serializer = ProfileSerializer(profile[0])
                    return Response(serializer.data)
            serializer = ProfileSerializer(data=data)
        if serializer.is_valid():
            serializer.save(company=company)
            return Response(serializer.data)
        else:
            return Response({
                'status': 'error',
                'message': 'Invalid data',
                'errors': serializer.errors
            }, status=400)

    except Company.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Company does not exist'
        }, status=404)

    except Flow.DoesNotExist:
        return Response({
            'status': 'error',
            'message': 'Flow does not exist'
        }, status=404)

    except Exception as e:
        traceback.print_exc()
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)


@api_view(['POST'])
def login(request):
    try:
        if 'email' in request.data and 'password' in request.data:
            email = request.data['email']
            password = request.data['password']
            print("Login User Email: ", email)
            print("Login User Password: ", password)

            p = Profile.objects.filter(email=email)
            if len(p) > 0:
                p = p[0]
                if check_password(password, p.password):
                    profile_address = ProfileAddress.objects.filter(profile=p)
                    if len(profile_address) > 0:
                        state = profile_address[0].state
                    else:
                        state = ''
                    token = RefreshToken.for_user(p)
                    access_token = str(token.access_token)
                    request.session['is_authenticated'] = True
                    request.session['profileid'] = p.id
                    return Response({
                        'status': 'ok',
                        'id': p.id,
                        'first_name': p.first_name,
                        'email': p.email,
                        'access_token': access_token,
                        'company': p.company.slug,
                        'state': state
                    }, status=200)
                else:
                    logger.error('Password incorrect')
                    return Response({
                        'status': 'error',
                        'message': 'Password is incorrect'
                    }, status=401)
            else:
                logger.error('Profile does not exist')
                return Response({
                    'status': 'error',
                    'message': 'Profile does not exist'
                }, status=400)
        else:
            logger.error('Email and Password are mandatory')
            return Response({
                'status': 'error',
                'message': 'Email and Password are mandatory'
            }, status=400)
    except Exception as e:
        traceback.print_exc()
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)


@api_view(['POST'])
def logout(request):
    try:
        # Blacklist the token
        token = request.headers.get('Authorization', '').split(' ')[1]
        if token:
            BlacklistedToken.objects.create(token=token)

        # Clear the session data to log the user out
        request.session.clear()

        response = Response({
            'status': 'ok',
            'message': 'Logout successful'
        }, status=200)

        response.delete_cookie('sessionid')
        return response
    except Exception as e:
        traceback.print_exc()
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)



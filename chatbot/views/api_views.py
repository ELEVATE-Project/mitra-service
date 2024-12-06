import logging
import traceback
from django.contrib.auth.hashers import check_password
from rest_framework.response import Response
from rest_framework.decorators import api_view, authentication_classes
from chatbot.auth import ProfileJWTAuthentication
from chatbot.models import ProfileType
from chatbot.models.geo_models import ProfileAddress
from chatbot.models.auth_models import BlacklistedToken
from chatbot.models.base_models import Profile, Company
from chatbot.serializer.profile_serializer import ProfileSerializer
from django.http import JsonResponse
from django.contrib.sessions.backends.db import SessionStore
from rest_framework_simplejwt.tokens import RefreshToken


logger = logging.getLogger('django')


def generate_session_id(request):
    try:
        session = SessionStore()
        session.create()
        return JsonResponse({'sessionid': session.session_key})
    except Exception as e:
        print('Exception is here')
        print(e)
        traceback.print_exc()


@api_view(['POST'])
def post_profile(request):
    try:
        data = request.data
        if not ('email' in data and ('company' in data or 'subdomain' in data)):
            return Response({
               'status': 'error',
               'message': 'email and subdomain/company are mandatory'
            }, status=400)
        company_slug = data.get('company') if 'company' in data else data.get('subdomain')
        company = Company.objects.filter(slug=company_slug)
        if len(company) > 0:
            company = company[0]
            email = data['email']
            profile = Profile.objects.filter(email=email, company=company).first()
            if profile:
                serializer = ProfileSerializer(profile, data=request.data)
            else:
                phone = data.get('phone', None)
                if phone:
                    profile = Profile.objects.filter(phone=phone, company=company)
                    if len(profile) > 0:
                        serializer = ProfileSerializer(profile[0])
                        return Response(serializer.data)
                serializer = ProfileSerializer(data=request.data)
            if serializer.is_valid():
                serializer.save(company=company)
                return Response(serializer.data)
            else:
                return Response({
                    'status': 'error',
                    'message': 'Invalid data',
                    'errors': serializer.errors
                }, status=400)
        else:
            if company_slug in ['demo', 'demous', 'localhost', 'interview', 'voicedemo']:
                email = data['email']
                profile = Profile.objects.filter(email=email).first()
                if profile:
                    serializer = ProfileSerializer(profile, data=request.data)
                else:
                    serializer = ProfileSerializer(data=request.data)
                if serializer.is_valid():
                    serializer.save()
                    return Response(serializer.data)
                else:
                    return Response({
                        'status': 'error',
                        'message': 'Invalid data',
                        'errors': serializer.errors
                    }, status=400)
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

            host = request.get_host()
            subdomain = host.split('.')[0]
            if subdomain in ['demo', 'demous', 'localhost:9000', 'interview', 'voicedemo', 'mohini']:
                print("In here 1")
                p = Profile.objects.filter(email=email)
            elif subdomain in ['prospect']:
                print("In here 2")
                p = Profile.objects.filter(email=email, profile_type=ProfileType.MODERATOR)
            else:
                print("In here 3")
                p = Profile.objects.filter(email=email, company__slug=subdomain)
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



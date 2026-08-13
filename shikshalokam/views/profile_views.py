import os
import traceback

import jwt

from chatbot.models import Company, Profile
from rest_framework.decorators import api_view
from rest_framework.response import Response
from chatbot.utils.elevate.profile_utils import handle_elevate_profile


@api_view(['GET'])
def read_elevate_profile(request):
    access_token = request.headers.get('X-auth-token')
    print("Access token: ", access_token)

    if not access_token:
        return Response({
            'status': 'error',
            'message': 'Access token is required.'
        }, status=400)

    profile_details = handle_elevate_profile(access_token=access_token)

    if not profile_details or not profile_details.get('profileid'):
        return Response({
            'status': 'error',
            'message': 'Failed to fetch or create profile from Elevate.'
        }, status=500)

    return Response({
        'status': 'ok',
        'profile_details': profile_details
    }, status=200)


@api_view(['GET'])
def authenticate_profile_view(request):
    """Authenticate profile using JWT token from cookie or Authorization header."""
    try:
        # Determine token source: 'cookie' (default) or 'header'
        jwt_source = os.environ.get('JWT_SOURCE', 'cookie').lower()
        if jwt_source == 'header':
            header_key = os.environ.get('JWT_HEADER_KEY', 'Authorization')
            header_value = request.headers.get(header_key, '')
            # Strip Bearer prefix if present
            token = header_value[len('Bearer '):].strip() if header_value.startswith('Bearer ') else header_value.strip()
        else:
            cookie_key = os.environ.get('JWT_COOKIE_KEY', '')
            token = request.COOKIES.get(cookie_key, '')

        secret = os.environ.get('JWT_TOKEN_SECRET', '')

        if not token:
            return Response({
                'status': 'error',
                'message': 'Authentication token not found'
            }, status=401)

        if not secret:
            return Response({
                'status': 'error',
                'message': 'JWT secret not configured'
            }, status=500)

        # Verify and decode the token
        try:
            decoded_token = jwt.decode(token, secret, algorithms=['HS512'])

            other_params = decoded_token.get('data', {})

            identifier_field = os.environ.get('JWT_IDENTIFIER_FIELD', 'userId')
            email_suffix = os.environ.get('JWT_EMAIL_SUFFIX', '@shikshalokam.org')
            identifier = other_params.get(identifier_field, '')
            if not identifier:
                return Response({
                    'status': 'error',
                    'message': 'Identifier not found in token payload'
                }, status=401)

            email = identifier + email_suffix if email_suffix else identifier
            userid = identifier

            company_slug = os.environ.get('COMPANY_SLUG', 'shikshalokamstaging')
            try:
                company = Company.objects.get(slug=company_slug)
            except Company.DoesNotExist:
                print(f"Company slug '{company_slug}' not found in database")
                return Response({
                    'status': 'error',
                    'message': 'Authentication failed'
                }, status=500)

            profile, profile_created = Profile.objects.update_or_create(
                email=email,
                defaults={
                    'company': company,
                    'userid': userid,
                    'other_params': other_params,
                }
            )

            if profile_created:
                print("Profile created: ", profile.id)
            else:
                print("Profile updated: ", profile.id)

            profile_response = {
                "first_name": profile.first_name,
                "company": profile.company.slug if profile.company else None,
                "has_accepted_tnc": "ONGOING",
                "route": profile.preferred_route,
                "profileid": profile.id,
                'reroute_url': os.environ.get('SSO_REROUTE_URL')
            }

            return Response({
                'status': 'ok',
                'message': 'Authentication successful',
                'profile_details': profile_response
            }, status=200)

        except jwt.ExpiredSignatureError:
            return Response({
                'status': 'error',
                'message': 'Token has expired'
            }, status=401)

        except jwt.InvalidTokenError:
            return Response({
                'status': 'error',
                'message': 'Invalid token'
            }, status=401)

    except Exception as e:
        print(f"Error authenticating profile: {str(e)}")
        traceback.print_exc()
        return Response({
            'status': 'error',
            'message': 'Authentication failed'
        }, status=500)

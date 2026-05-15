from django.http import JsonResponse

from chatbot.models import Profile
from shikshalokam.models import Project, ProjectWishlist
from rest_framework.decorators import api_view
from shikshalokam.utils.wishlist_utils import add_project_wishlist, remove_project_wishlist
import jwt


@api_view(['POST'])
def wishlist_project_view(request):
    try:
        body = request.data
        in_wishlist = body.get('in_wishlist')
        project_id = body.get('id')
        access_token = request.headers.get("X-auth-token")
        in_wishlist = bool(in_wishlist)

        if project_id is None or in_wishlist is None:
            return JsonResponse({
                'error': 'Both "id" and "in_wishlist" fields are required.'
            }, status=400, safe=False)

        if access_token:
            decoded = jwt.decode(access_token, options={"verify_signature": False})
            print(decoded)
            if decoded:
                user_id = decoded.get('data', {}).get('id')
                profile = Profile.objects.get(userid=user_id)

        project = Project.objects.filter(id=project_id).first()
        if not project:
            return JsonResponse({
                'error': f'Project with id {project_id} not found.'
            }, status=404, safe=False)

        project_in_wishlist = ProjectWishlist.objects.filter(author=profile, project=project).exists()

        if in_wishlist:
            if project_in_wishlist:
                return JsonResponse({
                    'error': 'error',
                    'details': "Project templates already exist in  wishlist."
                }, status=500, safe=False)
            else:
                try:
                    json_response = add_project_wishlist(project=project, access_token=access_token)
                    if json_response.get('status') == 200:
                        pw = ProjectWishlist.objects.create(
                            author=profile,
                            project=project
                        )
                        print("Adeed project from our db: ", pw.id)
                    return JsonResponse({
                        'message': json_response.get('message'),
                        'status': json_response.get('status')
                    }, status=200, safe=False)
                except Exception as e:
                    return JsonResponse({
                        'error': 'An unexpected error occurred.',
                        'details': str(e)
                    }, status=500, safe=False)
        else:
            if project_in_wishlist:
                try:
                    json_response = remove_project_wishlist(project=project, access_token=access_token)
                    if json_response.get('status') == 200:
                        ProjectWishlist.objects.filter(
                            author=profile,
                            project=project
                        ).delete()
                        print("removed project from our db.")
                    return JsonResponse({
                        'message': json_response.get('message'),
                        'status': json_response.get('status')
                    }, status=200, safe=False)
                except Exception as e:
                    return JsonResponse({
                        'error': 'An unexpected error occurred.',
                        'details': str(e)
                    }, status=500, safe=False)
            else:
                return JsonResponse({
                    'error': 'error',
                    'details': "Project templates does not exist in  wishlist."
                }, status=500, safe=False)

    except Exception as e:
        return JsonResponse({
            'error': 'An unexpected error occurred.',
            'details': str(e)
        }, status=500, safe=False)

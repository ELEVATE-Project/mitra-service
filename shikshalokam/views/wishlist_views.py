from django.http import JsonResponse
from shikshalokam.models import Project
from rest_framework.decorators import api_view
from shikshalokam.utils.wishlist_utils import add_project_wishlist, remove_project_wishlist


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

        project = Project.objects.filter(id=project_id).first()
        if not project:
            return JsonResponse({
                'error': f'Project with id {project_id} not found.'
            }, status=404, safe=False)

        if in_wishlist:
            json_response = add_project_wishlist(project=project, access_token=access_token)
        else:
            json_response = remove_project_wishlist(project=project, access_token=access_token)

        if json_response.get('status') == 200:
            print(f"Success! switching in_wishlist to {in_wishlist}.")
            project.wishlist = in_wishlist
            project.save()


        return JsonResponse({
            'message': json_response.get('message'),
            'status': json_response.get('status')
        }, status=200, safe=False)

    except Exception as e:
        return JsonResponse({
            'error': 'An unexpected error occurred.',
            'details': str(e)
        }, status=500, safe=False)

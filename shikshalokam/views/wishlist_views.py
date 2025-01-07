from django.http import JsonResponse
from shikshalokam.models import Project
from rest_framework.decorators import api_view


@api_view(['POST'])
def wishlist_project_view(request):
    try:
        body = request.data
        in_wishlist = body.get('in_wishlist')
        project_id = body.get('id')

        if project_id is None or in_wishlist is None:
            return JsonResponse({
                'error': 'Both "id" and "in_wishlist" fields are required.'
            }, status=400, safe=False)

        project = Project.objects.filter(id=project_id).first()
        if not project:
            return JsonResponse({
                'error': f'Project with id {project_id} not found.'
            }, status=404, safe=False)

        project.wishlist = bool(in_wishlist)
        project.save()

        return JsonResponse({
            'message': f"Wishlist status updated to {project.wishlist} for project with id {project.id}"
        }, status=200, safe=False)

    except Exception as e:
        return JsonResponse({
            'error': 'An unexpected error occurred.',
            'details': str(e)
        }, status=500, safe=False)

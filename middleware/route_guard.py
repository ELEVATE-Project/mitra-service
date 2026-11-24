import logging

from django.http import JsonResponse
from django.urls import Resolver404, resolve
from middleware.route_config import AUTH_ROUTES, GUEST_URLS


logger = logging.getLogger(__name__)

GUARDED_NAMESPACE = "chatbot"


class RouteGuardMiddleware:
    """
    Enforces auth only on chatbot routes. Routes in GUEST_URLS pass without a token.
    Everything else in chatbot requires a verified token, so unlisted routes fail closed.
    Other apps (health, docs, admin, shikshalokam, storage upload) are not touched.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.guest_prefixes = tuple(GUEST_URLS)
        self.auth_prefixes = tuple(AUTH_ROUTES)

    def __call__(self, request):
        path = request.path_info

        try:
            match = resolve(path)
        except Resolver404:
            return self.get_response(request)

        if match.namespace != GUARDED_NAMESPACE:
            return self.get_response(request)

        if path.startswith(self.guest_prefixes):
            return self.get_response(request)

        if not path.startswith(self.auth_prefixes):
            logger.warning(
                "Chatbot route %s is in neither GUEST_URLS nor AUTH_ROUTES; requiring auth", path
            )

        if request.elevate_user_id is None:
            return JsonResponse(
                {
                    "status": "ERR_AUTH_REQUIRED",
                    "message": request.auth_error or "Authentication required",
                },
                status=401,
            )

        return self.get_response(request)
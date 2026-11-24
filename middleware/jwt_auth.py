import jwt
from django.conf import settings

from middleware.user_details import UserDetails

# Django exposes the x-auth-token request header as HTTP_X_AUTH_TOKEN.
TOKEN_META_KEY = "HTTP_X_AUTH_TOKEN"


class JWTAuthMiddleware:
    """
    Verifies the token signature and expiry, then attaches the user ID and
    a UserDetails object. It never rejects requests itself; the route guard does.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Pinned to one algorithm, so a token's header cannot switch it.
        self.algorithm = settings.JWT_ALGORITHM
        self.key = settings.JWT_VERIFY_KEY

    def __call__(self, request):
        request.elevate_user_id = None
        request.user_claims = None
        request.user_details = None
        request.auth_error = None

        token = request.META.get(TOKEN_META_KEY)
        if token:
            self._authenticate(request, token)

        return self.get_response(request)

    def _authenticate(self, request, token):
        try:
            claims = jwt.decode(
                token,
                self.key,
                algorithms=[self.algorithm],
                options={"require": ["exp"]},
            )
        except jwt.ExpiredSignatureError:
            request.auth_error = "Token expired"
            return
        except jwt.PyJWTError:
            request.auth_error = "Invalid token"
            return

        user_id = (claims.get("data") or {}).get("id")
        if user_id is None:
            request.auth_error = "Invalid token"
            return

        request.user_claims = claims
        request.elevate_user_id = str(user_id)
        request.user_details = UserDetails(token=token, user_id=str(user_id))
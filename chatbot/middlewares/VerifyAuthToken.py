import traceback
import jwt
from django.http import JsonResponse

class VerifyAuthToken:
    # Purpose: Initialises the middleware instance during Django's application boot.
    #          Stores the next middleware/view callable so requests can be forwarded
    #          after authentication checks pass.
    # Inputs:  get_response — callable representing the next layer in the middleware stack
    # Output:  None (constructor)
    # Side effects: None
    def __init__(self, get_response):
        self.get_response = get_response

    # Purpose: HTTP request gatekeeper. If an Authorization: Bearer token is present,
    #          validates it is a structurally valid, non-expired JWT before forwarding.
    #          Requests with no Authorization header are allowed through unconditionally.
    # Inputs:  request — Django HttpRequest (reads HTTP_AUTHORIZATION from request.META)
    # Output:  Next middleware/view response on success;
    #          JsonResponse {"error": "Invalid token"} + 401 if token malformed/expired;
    #          JsonResponse {"error": "Authentication failed"} + 500 on unexpected error
    # Side effects: None — no DB writes, no session mutations
    # Note:    Signature verification is disabled (verify_signature=False).
    #          This only checks token structure and expiry, not issuer trust.
    #          Identity enforcement is deferred to individual views.
    def __call__(self, request):

        auth_header = request.META.get('HTTP_AUTHORIZATION')

        AUTH_ERROR_MESSAGE = "Invalid token"
        
        if auth_header:
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
            else:
                return JsonResponse(
                    {'error': AUTH_ERROR_MESSAGE},
                    status=401
                )
            
            try:
                # verify_signature=False means only expiry and structure are checked —
                # the token is NOT verified against a server secret, so any well-formed JWT passes
                jwt.decode( token, options={"verify_signature": False})
                
            except jwt.ExpiredSignatureError:
                return JsonResponse(
                    {'error': AUTH_ERROR_MESSAGE},
                    status=401
                )
            except jwt.InvalidTokenError:
                return JsonResponse(
                    {'error': AUTH_ERROR_MESSAGE},
                    status=401
                )
            except Exception as e:
                traceback.print_exc()
                return JsonResponse(
                    {'error': f'Authentication failed'},
                    status=500
                )
        
        # Reached when: (a) no Authorization header, or (b) token present and structurally valid.
        # Invalid/expired tokens are rejected above; this line is never reached for those cases.
        response = self.get_response(request)
        return response
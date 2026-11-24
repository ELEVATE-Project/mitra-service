import logging
import os

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

PROFILE_CACHE_TTL = 600  # seconds
REQUEST_TIMEOUT = 10     # seconds


def get_user_profile(user_id, token, fresh=False):
    """
    Returns (body, error). body is the full user/read response.
    error is a (http_status, message) tuple or None.
    fresh=True skips the cache read. A successful call always refreshes the cache.
    The token is sent upstream only and is never cached.
    """
    cache_key = f"user_profile:{user_id}"
    if not fresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached, None

    base_url = os.environ["ELEVATE_BASE_URL"].rstrip("/")
    try:
        response = requests.get(
            f"{base_url}/user/v1/user/read",
            headers={"x-auth-token": token, "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("User service unreachable: %s", exc)
        return None, (502, "User service unavailable")

    if response.status_code == 401:
        return None, (401, "Token rejected by user service")
    if response.status_code != 200:
        logger.error("User service returned %s: %s", response.status_code, response.text[:500])
        return None, (502, f"User service error {response.status_code}")

    try:
        body = response.json()
    except ValueError:
        return None, (502, "Invalid response from user service")

    if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
        return None, (502, "Invalid response from user service")

    cache.set(cache_key, body, PROFILE_CACHE_TTL)
    return body, None


class UserDetails:
    """
    Attached to request.user_details by JWTAuthMiddleware.

    userToken          the raw token, used only for upstream calls
    userId             data.id from the token, as a string
    userReadResponse   the full user/read response body (stored on ChatSession.user_profile)
    userProfile        the "result" object inside that response
    """

    def __init__(self, token, user_id):
        self.userToken = token
        self.userId = user_id
        self._body = None
        self._error = None
        self._loaded = False

    def _load(self):
        if not self._loaded:
            self._body, self._error = get_user_profile(self.userId, self.userToken)
            self._loaded = True

    @property
    def userReadResponse(self):
        self._load()
        return self._body

    @property
    def userProfile(self):
        self._load()
        return self._body["result"] if self._body else None

    @property
    def profileError(self):
        self._load()
        return self._error

    def to_dict(self):
        return {
            "userToken": self.userToken,
            "userId": self.userId,
            "userProfile": self.userProfile,
        }
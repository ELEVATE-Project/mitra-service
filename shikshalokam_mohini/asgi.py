"""
ASGI config for shikshalokam_mohini project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os
from channels.sessions import CookieMiddleware, SessionMiddleware
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application
from chatbot import routing


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shikshalokam_mohini.settings')

django_asgi_app = get_asgi_application()

# Import AFTER Django initialization
import django
django.setup()  # Extra insurance that Django is fully set up
import chatbot.routing


application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                CookieMiddleware(SessionMiddleware(URLRouter(routing.websocket_urlpatterns)))
            )
        ),
    }
)

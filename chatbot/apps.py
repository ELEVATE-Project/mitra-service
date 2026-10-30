from django.apps import AppConfig


class ChatbotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'chatbot'
    def ready(self):
        # Registers the MEDIATemplates cache-invalidation receiver at startup,
        # so it runs in workers and management commands too.
        from chatbot.constants import template_cache  # noqa: F401

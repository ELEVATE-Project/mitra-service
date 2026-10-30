import logging

from jinja2 import Environment, TemplateError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from chatbot.models import MEDIATemplates
from django.core.cache import cache

from chatbot.constants.template_cache import CACHE_TTL, detail_cache_key, get_version
logger = logging.getLogger(__name__)

_env = Environment(autoescape=True)
FALLBACK_LANGUAGE = "en"


def _select_language(constants_json, requested):
    """Return (language_code, block). Missing or unknown codes fall back to en."""
    if not isinstance(constants_json, dict):
        return FALLBACK_LANGUAGE, {}

    code = (requested or "").strip().lower()
    block = constants_json.get(code)
    if not isinstance(block, dict):
        code = FALLBACK_LANGUAGE
        block = constants_json.get(code)

    if not isinstance(block, dict):
        return FALLBACK_LANGUAGE, {}
    return code, block


class TemplateDetailsView(APIView):
    def get(self, request, template_id):
        requested = (request.query_params.get("language") or "en").strip().lower()

        version = get_version(template_id)
        cache_key = detail_cache_key(template_id, version, requested)

        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        template = MEDIATemplates.objects.filter(pk=template_id).first()
        if template is None:
            return Response(
                {"detail": "Template not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        code, block = _select_language(template.constants_json, requested)

        try:
            html = _env.from_string(template.template).render(
                constants={**block, "lang": code}
            )
        except TemplateError:
            logger.exception("Failed to render template id=%s", template.id)
            return Response(
                {"detail": "Template could not be rendered."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        payload = {"template_id": template.id, "language": code, "html": html}

        # Only cache when the requested language really exists. Fallbacks to "en"
        # are not cached under the requested key.
        if code == requested:
            cache.set(cache_key, payload, timeout=CACHE_TTL)

        return Response(payload, status=status.HTTP_200_OK)
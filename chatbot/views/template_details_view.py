import logging
import os
from functools import lru_cache

import boto3
from botocore.config import Config
from django.conf import settings
from django.core.cache import cache
from jinja2 import Environment, TemplateError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from chatbot.constants.template_cache import CACHE_TTL, detail_cache_key, get_version
from chatbot.models import MEDIATemplates

logger = logging.getLogger(__name__)

_env = Environment(autoescape=True)
FALLBACK_LANGUAGE = "en"

# Top-level block in constants_json whose S3 keys apply to every language.
# A language block can still set its own key to override it.
SHARED_KEY = "media"

# Stored S3 key field -> (template variable, placeholder token used in cached HTML)
MEDIA_FIELDS = {
    "banner_image_key": ("banner_image_url", "__BANNER_IMAGE_URL__"),
    "header_gif_key": ("header_gif_url", "__HEADER_GIF_URL__"),
    "achievement_icon_key": ("achievement_icon_url", "__ACHIEVEMENT_ICON_URL__"),
}

# Download link: same banner object, served with Content-Disposition: attachment
DOWNLOAD_FIELD = "banner_download_url"
DOWNLOAD_TOKEN = "__BANNER_DOWNLOAD_URL__"

TOKENS = {url_field: token for url_field, token in MEDIA_FIELDS.values()}
TOKENS[DOWNLOAD_FIELD] = DOWNLOAD_TOKEN

# Presigned URLs are created per request, so one hour is enough
PRESIGN_EXPIRES = 60 * 60


@lru_cache(maxsize=1)
def _s3_client():
    return boto3.client(
        "s3",
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version="s3v4"),
    )


def _select_language(constants_json, requested):
    """Return (language_code, block) with the shared media keys merged in."""
    if not isinstance(constants_json, dict):
        return FALLBACK_LANGUAGE, {}

    shared = constants_json.get(SHARED_KEY)
    shared = shared if isinstance(shared, dict) else {}

    code = (requested or "").strip().lower()
    block = constants_json.get(code) if code != SHARED_KEY else None
    if not isinstance(block, dict):
        code = FALLBACK_LANGUAGE
        block = constants_json.get(code)

    if not isinstance(block, dict):
        return FALLBACK_LANGUAGE, dict(shared)
    return code, {**shared, **block}


def _render_block(block):
    """Replace stored S3 keys with placeholder tokens. Literal URLs are dropped, so only keys decide what is shown."""
    render_block = dict(block)
    for url_field, token in TOKENS.items():
        render_block.pop(url_field, None)

    for key_field, (url_field, token) in MEDIA_FIELDS.items():
        if render_block.get(key_field):
            render_block[url_field] = token
    if render_block.get("banner_image_key"):
        render_block[DOWNLOAD_FIELD] = DOWNLOAD_TOKEN
    return render_block


def _media_keys(block):
    """The S3 keys for this language. These are cached; URLs are not."""
    return {key_field: block[key_field] for key_field in MEDIA_FIELDS if block.get(key_field)}


def _presign(key, disposition=None):
    params = {"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": key}
    if disposition:
        params["ResponseContentDisposition"] = disposition
    return _s3_client().generate_presigned_url(
        ClientMethod="get_object",
        Params=params,
        ExpiresIn=PRESIGN_EXPIRES,
    )


def _safe_presign(key, label, disposition=None):
    try:
        return _presign(key, disposition)
    except Exception:
        logger.exception("Could not presign %s=%s", label, key)
        return ""


def _resolve_media(media_keys):
    """Create fresh presigned URLs for every stored key. Runs on every request, never cached."""
    urls = {}
    for key_field, key in media_keys.items():
        url_field, _ = MEDIA_FIELDS[key_field]
        urls[url_field] = _safe_presign(key, key_field)
        if key_field == "banner_image_key":
            filename = os.path.basename(key)
            urls[DOWNLOAD_FIELD] = _safe_presign(
                key, key_field, disposition=f'attachment; filename="{filename}"'
            )
    return urls


def _fill_placeholders(html, urls):
    for url_field, token in TOKENS.items():
        html = html.replace(token, urls.get(url_field, ""))
    return html


class TemplateDetailsView(APIView):
    def get(self, request, template_id):
        requested = (request.query_params.get("language") or "en").strip().lower()

        version = get_version(template_id)
        cache_key = detail_cache_key(template_id, version, requested)

        # Entries without "media_keys" were written by older code, so rebuild them
        cached = cache.get(cache_key)
        if cached is None or "media_keys" not in cached:
            template = MEDIATemplates.objects.filter(pk=template_id).first()
            if template is None:
                return Response(
                    {"detail": "Template not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            code, block = _select_language(template.constants_json, requested)

            try:
                html = _env.from_string(template.template).render(
                    constants={**_render_block(block), "lang": code}
                )
            except TemplateError:
                logger.exception("Failed to render template id=%s", template.id)
                return Response(
                    {"detail": "Template could not be rendered."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            cached = {
                "template_id": template.id,
                "language": code,
                "html": html,
                "media_keys": _media_keys(block),
            }

            # Fallbacks to "en" are not cached under the requested language
            if code == requested:
                cache.set(cache_key, cached, timeout=CACHE_TTL)

        urls = _resolve_media(cached["media_keys"])
        html = _fill_placeholders(cached["html"], urls)

        # Response matches the agreed contract: template_id, language, html
        return Response(
            {
                "template_id": cached["template_id"],
                "language": cached["language"],
                "html": html,
            },
            status=status.HTTP_200_OK,
        )
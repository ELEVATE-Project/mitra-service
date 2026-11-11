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


def _languages_key(template_id, version):
    """Build the cache key that holds the language codes for one template version.

    The suffix starts with an underscore, so it cannot collide with a real
    language code, which is always a plain lowercase code.

    Args:
        template_id (int): Primary key of the MEDIATemplates row.
        version (str): Current cache version token for the template.

    Returns:
        str: The Redis key for the language list.
    """
    return f"mediatemplate:{template_id}:{version}:_languages"


@lru_cache(maxsize=1)
def _s3_client():
    """Return a shared boto3 S3 client for generating presigned URLs.

    Uses Signature Version 4, which the ap-south-1 region requires.

    Returns:
        boto3.client: An S3 client. Credentials come from the environment.
    """
    return boto3.client(
        "s3",
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version="s3v4"),
    )


def _load_template(template_id):
    """Fetch one MEDIATemplates row by primary key.

    Args:
        template_id (int): Primary key of the row to load.

    Returns:
        MEDIATemplates | None: The row, or None if it does not exist.
    """
    return MEDIATemplates.objects.filter(pk=template_id).first()


def _available_languages(constants_json):
    """List the language codes that have their own block in constants_json.

    The shared media block and any value that is not a dict are excluded.

    Args:
        constants_json (dict | None): The MEDIATemplates.constants_json value.

    Returns:
        list[str]: Sorted language codes. Empty if constants_json is not a dict.
    """
    if not isinstance(constants_json, dict):
        return []
    return sorted(
        code
        for code, block in constants_json.items()
        if code != SHARED_KEY and isinstance(block, dict)
    )


def _resolve_code(requested, languages):
    """Choose the language code that will actually be rendered.

    Unknown codes resolve to FALLBACK_LANGUAGE, so cache keys only ever use
    codes that exist in the template.

    Args:
        requested (str): The normalized language code from the query string.
        languages (list[str]): Language codes available on the template.

    Returns:
        str: `requested` if it is available, otherwise FALLBACK_LANGUAGE.
    """
    return requested if requested in languages else FALLBACK_LANGUAGE


def _block_for(constants_json, code):
    """Return the text for one language, merged over the shared media block.

    Keys in the language block take precedence over the shared block.

    Args:
        constants_json (dict | None): The MEDIATemplates.constants_json value.
        code (str): The resolved language code.

    Returns:
        dict: The merged block. Empty if constants_json is not a dict.
    """
    if not isinstance(constants_json, dict):
        return {}
    shared = constants_json.get(SHARED_KEY)
    shared = shared if isinstance(shared, dict) else {}
    block = constants_json.get(code)
    block = block if isinstance(block, dict) else {}
    return {**shared, **block}


def _render_block(block):
    """Replace stored S3 keys with placeholder tokens so the HTML can be cached.

    Any literal URL in the block is dropped, so only the stored keys decide
    what the page shows.

    Args:
        block (dict): The merged language block.

    Returns:
        dict: A copy of the block with URL fields set to placeholder tokens.
    """
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
    """Collect the S3 keys used by one language block.

    Only keys are cached. Presigned URLs are created on every request.

    Args:
        block (dict): The merged language block.

    Returns:
        dict: Map of each present key field to its S3 object key.
    """
    return {key_field: block[key_field] for key_field in MEDIA_FIELDS if block.get(key_field)}


def _presign(key, disposition=None):
    """Generate a presigned GET URL for one S3 object.

    Args:
        key (str): The S3 object key.
        disposition (str | None): Optional Content-Disposition to force on the response,
            such as an attachment header for downloads.

    Returns:
        str: A presigned URL that is valid for PRESIGN_EXPIRES seconds.
    """
    params = {"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": key}
    if disposition:
        params["ResponseContentDisposition"] = disposition
    return _s3_client().generate_presigned_url(
        ClientMethod="get_object",
        Params=params,
        ExpiresIn=PRESIGN_EXPIRES,
    )


def _safe_presign(key, label, disposition=None):
    """Presign a URL, logging and returning an empty string on failure.

    A failed presign leaves the image empty instead of failing the whole page.

    Args:
        key (str): The S3 object key.
        label (str): Field name used in the log message.
        disposition (str | None): Optional Content-Disposition passed to `_presign`.

    Returns:
        str: The presigned URL, or an empty string if presigning failed.
    """
    try:
        return _presign(key, disposition)
    except Exception:
        logger.exception("Could not presign %s=%s", label, key)
        return ""


def _resolve_media(media_keys):
    """Create fresh presigned URLs for every stored key.

    Runs on every request and is never cached. The banner also gets a
    second URL that makes the browser download the file.

    Args:
        media_keys (dict): Map of key field to S3 object key, from the cache.

    Returns:
        dict: Map of template variable to presigned URL.
    """
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
    """Replace each placeholder token in the cached HTML with its presigned URL.

    Args:
        html (str): The cached HTML containing placeholder tokens.
        urls (dict): Map of template variable to presigned URL.

    Returns:
        str: The HTML with tokens replaced. Missing URLs become empty strings.
    """
    for url_field, token in TOKENS.items():
        html = html.replace(token, urls.get(url_field, ""))
    return html


def _render_html(template, block, code):
    """Render the template HTML for one language, with placeholder tokens for URLs.

    Args:
        template (MEDIATemplates): The template row being rendered.
        block (dict): The merged language block for `code`.
        code (str): The resolved language code, exposed to the template as `lang`.

    Returns:
        str: The rendered HTML.

    Raises:
        jinja2.TemplateError: If the template source is invalid.
    """
    return _env.from_string(template.template).render(
        constants={**_render_block(block), "lang": code}
    )


class TemplateDetailsView(APIView):
    """Serve the rendered success page for one MEDIATemplates row.

    Endpoint: GET /api/template-details/<template_id>/?language=<code>

    Caching:
        - The language list for each template version is cached.
        - Rendered HTML is cached per resolved language, with placeholder tokens.
        - Presigned URLs are never cached and are created on every request.
    """

    def get(self, request, template_id):
        """Return the rendered page for the requested language.

        Unknown or missing languages fall back to FALLBACK_LANGUAGE and are served
        from that language's cache entry.

        Args:
            request (rest_framework.request.Request): The incoming request.
            template_id (int): Primary key of the MEDIATemplates row.

        Returns:
            Response: 200 with template_id, language and html. 404 if the template
            does not exist. 500 if the template source cannot be rendered.
        """
        requested = (request.query_params.get("language") or "en").strip().lower()
        version = get_version(template_id)

        # Language list first. A cache hit avoids reading the database entirely.
        template = None
        languages = cache.get(_languages_key(template_id, version))
        if languages is None:
            template = _load_template(template_id)
            if template is None:
                return Response(
                    {"detail": "Template not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            languages = _available_languages(template.constants_json)
            cache.set(_languages_key(template_id, version), languages, timeout=CACHE_TTL)

        code = _resolve_code(requested, languages)
        cache_key = detail_cache_key(template_id, version, code)

        # Entries without "media_keys" were written by older code, so rebuild them
        cached = cache.get(cache_key)
        if cached is None or "media_keys" not in cached:
            if template is None:
                template = _load_template(template_id)
                if template is None:
                    return Response(
                        {"detail": "Template not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )

            block = _block_for(template.constants_json, code)
            try:
                html = _render_html(template, block, code)
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
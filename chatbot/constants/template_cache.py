# chatbot/constants/template_cache.py
import uuid

from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from chatbot.models import MEDIATemplates

CACHE_TTL = 60 * 60 * 24  # 24 hours


def _version_key(template_id):
    return f"mediatemplate:{template_id}:version"


def get_version(template_id):
    key = _version_key(template_id)
    version = cache.get(key)
    if version is None:
        # add() only sets the key if it is absent, so concurrent first requests agree.
        cache.add(key, uuid.uuid4().hex, timeout=None)
        version = cache.get(key)
    return version


def detail_cache_key(template_id, version, language):
    return f"mediatemplate:{template_id}:{version}:{language}"


def _bump_version(template_id):
    # A fresh random token means old entries can never be served again,
    # even if the version key is evicted and recreated.
    cache.set(_version_key(template_id), uuid.uuid4().hex, timeout=None)


@receiver([post_save, post_delete], sender=MEDIATemplates)
def invalidate_template_cache(sender, instance, **kwargs):
    # Bump only after the transaction commits, so a reader that sees the new
    # version is guaranteed to read the new row from the DB.
    transaction.on_commit(lambda pk=instance.pk: _bump_version(pk))
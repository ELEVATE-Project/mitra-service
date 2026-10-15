"""
Migrate data from a source Postgres DB to the target DB using Django ORM.

Source DB must be configured as 'source_db' in DATABASES (via SOURCE_DATABASE_* env vars).

S3 objects referenced by CompanyChat.file_url and StoryMedia.file / file_url are copied
server-side from --src-bucket to --target-bucket (both required, bare bucket names such as
'mohini-static.shikshalokam.org') before each row is inserted; the row is skipped if any copy
fails. StoryMedia keys are rewritten to the target story id. Objects already present in the
target bucket are not re-copied (reruns resume). Dry run HEAD-checks target, then source.
Target bucket needs s3:ListBucket so missing keys return 404 (checked at startup).

Usage:
    # Migrate everything
    python manage.py migrate_data --src-bucket <src> --target-bucket <target>

    # Migrate only transactional data within a date range, plus all referenced
    # Company / CompanyBot / Flow / ImageConfiguration / PDFTemplates / Profile
    python manage.py migrate_data --date-from 2024-01-01 --date-to 2024-12-31

    # Exact time window — e.g. 30 June 2026, 2:00 PM to 5:00 PM
    python manage.py migrate_data \
        --date-from "2026-06-30 14:00" --date-to "2026-06-30 17:00"

    # Restrict to one bot (CompanyBot route), optionally with date/time
    python manage.py migrate_data --dry-run [--date-from ...] [--date-to ...] \
        --session_name shiksha-samvad

    # Only the sessions listed in a CSV column (cannot combine with date / --session_name)
    python manage.py migrate_data --sessions-csv sessions.csv --sessions-csv-column session_id

    # Dry run (count rows, no writes)
    python manage.py migrate_data --dry-run [--date-from ...] [--date-to ...]

Scope:
    ChatSessions are selected by date range / bot route, or by CSV. CompanyChat and Story
    always follow the in-scope ChatSessions (matched on session), never their own created_at.

Date/time filters:
    --date-from / --date-to accept 'YYYY-MM-DD' (whole day) or
    'YYYY-MM-DD HH:MM[:SS]' (exact time). Filters run against created_at, so
    time-of-day is honoured (ChatSession only). If settings.USE_TZ is True, naive inputs are made
    timezone-aware in the current timezone before filtering.

Sessions CSV:
    --sessions-csv / --sessions-csv-column go together; the column is picked by header name.
    Values are trimmed, blanks skipped, duplicates dropped (file read as utf-8-sig). CSV
    sessions missing from source are logged (entity CSVSession) to migration_errors.jsonl.

Timestamp handling:
    auto_now_add / auto_now fields are overwritten via QuerySet.update() after
    each row is saved, so source DB timestamps are preserved exactly.

Upsert keys:
    Company            : slug
    CompanyBot         : route
    ImageConfiguration : name
    Flow               : flow_route
    PDFTemplates       : template_name
    Profile            : (email, company)
    ChatSession        : session  — skip + log if already exists in target
    Story              : session  — skip + log if already exists in target

Bot sub-models (CompanyStateMachine, Voice, Theme, BotVernacular, StoryVernacular)
only migrate for CompanyBots newly created in this run.

Resource logging (logger 'django' -> info.log, prefix 'migrate_data[res]'):
    Per step: wall time, CPU time / %, current + peak RSS, RSS delta, gc counts, DB query log
    sizes, MigrationContext container sizes. Per batch: rows, RSS, CPU %.
    --trace-memory adds tracemalloc: top per-line allocation growth per step and top live
    allocations at the end (noticeably slower; use to locate leaks).
    KNOWN ISSUE: memory grows over long runs; these logs exist to locate it, not fix it.
    Current RSS needs /proc (Linux); elsewhere only peak RSS is reported.
"""

import argparse
import csv
import json
import logging
import gc
import os
import re
import resource
import sys
import time as time_mod
import tracemalloc
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import datetime, time
from itertools import islice
from typing import Any, Optional, Set

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.models import QuerySet
from django.utils import timezone

from chatbot.models.bot_vernacular_model import BotVernacular
from chatbot.models.chat_models import ChatSession
from chatbot.models.company_models import (
    Company,
    CompanyBot,
    CompanyChat,
    CompanyStateMachine,
    Flow,
    ImageConfiguration,
    PDFTemplates,
    Voice,
)
from chatbot.models.profile_models import Profile
from chatbot.models.story_models import Story, StoryMedia, StoryTranslation
from chatbot.models.story_vernacular_model import StoryVernacular
from chatbot.models.theme_models import Theme

SRC = "source_db"

logger = logging.getLogger("django")

# Bare S3 bucket name in DNS form, e.g. 'mohini-static.shikshalokam.org'
BUCKET_NAME_RE = re.compile(r"^(?=.{3,63}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*$")
S3_URL_SCHEMES = ("https://", "s3://")
S3_CLIENT_CONFIG = Config(retries={"max_attempts": 5, "mode": "standard"})
S3_NOT_FOUND_CODES = ("404", "NoSuchKey", "NotFound")

# A parsed --date-from / --date-to value.
#   value    : datetime (date-only inputs land on that date at 00:00:00)
#   has_time : True if the user supplied an explicit time-of-day component
DateArg = namedtuple("DateArg", ["value", "has_time"])


def parse_date_arg(raw: str) -> DateArg:
    """Accept 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]' and remember which."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return DateArg(datetime.strptime(raw, fmt), True)
        except ValueError:
            continue
    try:
        return DateArg(datetime.strptime(raw, "%Y-%m-%d"), False)
    except ValueError:
        raise ValueError(f"Use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]', got '{raw}'")


def _make_aware(dt: datetime) -> datetime:
    if getattr(settings, "USE_TZ", False) and timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _range_kwargs(date_from: Optional[DateArg], date_to: Optional[DateArg]) -> dict:
    """created_at range filter honouring time-of-day; date-only bounds cover the full day."""
    f = {}
    if date_from is not None:
        start = date_from.value if date_from.has_time else datetime.combine(date_from.value.date(), time.min)
        f["created_at__gte"] = _make_aware(start)
    if date_to is not None:
        end = date_to.value if date_to.has_time else datetime.combine(date_to.value.date(), time.max)
        f["created_at__lte"] = _make_aware(end)
    return f


def chunked(iterable, n):
    it = iter(iterable)
    while chunk := list(islice(it, n)):
        yield chunk


def iter_batches(ctx, label, qs, batch_size):
    """Batches of a source queryset; logs resource usage after each batch."""
    for i, batch in enumerate(chunked(qs.iterator(chunk_size=batch_size), batch_size), 1):
        yield batch
        if ctx.monitor is not None:
            ctx.monitor.batch(label, i, len(batch))


# ---------------------------------------------------------------------------
# Resource monitoring (CPU / memory) — diagnostics only, see docstring
# ---------------------------------------------------------------------------

TRACEMALLOC_TOP_N = 15
TRACEMALLOC_FILTERS = (
    tracemalloc.Filter(False, tracemalloc.__file__),
    tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
    tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
    tracemalloc.Filter(False, "<unknown>"),
)


def _mb(n: Optional[int]) -> str:
    return "n/a" if n is None else f"{n / (1024 * 1024):.1f}MB"


def _current_rss_bytes() -> Optional[int]:
    """Resident set size now; Linux only (/proc), None elsewhere."""
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # Linux reports KB


def _cpu_seconds() -> float:
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return ru.ru_utime + ru.ru_stime


class ResourceMonitor:
    """
    Logs CPU / memory per step (checkpoint) and per batch, to find where memory grows.
    CPU % = process CPU time / wall time over the interval; >100% means multiple threads
    (e.g. boto3 S3 transfer threads).
    """

    def __init__(self, trace_memory: bool):
        self.trace_memory = trace_memory
        self.ctx = None  # MigrationContext, attached once built
        if trace_memory:
            tracemalloc.start()
        self._snapshot = self._take_snapshot()
        self._run_start = self._step_start = self._batch_last = self._sample()

    def _take_snapshot(self):
        if not self.trace_memory:
            return None
        return tracemalloc.take_snapshot().filter_traces(TRACEMALLOC_FILTERS)

    @staticmethod
    def _sample() -> dict:
        return {"wall": time_mod.monotonic(), "cpu": _cpu_seconds(), "rss": _current_rss_bytes()}

    @staticmethod
    def _cpu_pct(start: dict, end: dict) -> float:
        wall = end["wall"] - start["wall"]
        return 100.0 * (end["cpu"] - start["cpu"]) / wall if wall > 0 else 0.0

    @staticmethod
    def _rss_delta(start: dict, end: dict) -> str:
        if start["rss"] is None or end["rss"] is None:
            return "n/a"
        return f"{(end['rss'] - start['rss']) / (1024 * 1024):+.1f}MB"

    def _ctx_sizes(self) -> str:
        c = self.ctx
        if c is None:
            return ""
        return (
            f" ctx[company_map={len(c.company_id_map)} bot_map={len(c.bot_id_map)}"
            f" flow_map={len(c.flow_id_map)} profile_map={len(c.profile_id_map)}"
            f" story_map={len(c.story_id_map)} skipped_sessions={len(c.skipped_sessions)}"
            f" dry_run_sessions={len(c.dry_run_migrated_sessions)} errors={len(c.errors)}]"
        )

    def batch(self, label: str, index: int, rows: int):
        now = self._sample()
        traced = ""
        if self.trace_memory:
            cur, peak = tracemalloc.get_traced_memory()
            traced = f" traced={_mb(cur)} traced_peak={_mb(peak)}"
        logger.info(
            f"migrate_data[res] batch {label} #{index} rows={rows} rss={_mb(now['rss'])}"
            f" rss_step_delta={self._rss_delta(self._step_start, now)}"
            f" cpu={self._cpu_pct(self._batch_last, now):.0f}%{traced}"
        )
        self._batch_last = now

    def checkpoint(self, label: str):
        now = self._sample()
        start = self._step_start
        queries = {alias: len(connections[alias].queries_log) for alias in (SRC, "default")}
        logger.info(
            f"migrate_data[res] step {label} wall={now['wall'] - start['wall']:.1f}s"
            f" cpu_time={now['cpu'] - start['cpu']:.1f}s cpu={self._cpu_pct(start, now):.0f}%"
            f" rss={_mb(now['rss'])} rss_delta={self._rss_delta(start, now)}"
            f" peak_rss={_mb(_peak_rss_bytes())} gc_counts={gc.get_count()}"
            f" query_log={queries}{self._ctx_sizes()}"
        )
        if self.trace_memory:
            snapshot = self._take_snapshot()
            growth = [d for d in snapshot.compare_to(self._snapshot, "lineno") if d.size_diff > 0]
            for d in growth[:TRACEMALLOC_TOP_N]:
                logger.info(
                    f"migrate_data[res]   grew {label}: {d.size_diff / 1024:+.1f}KB"
                    f" (now {d.size / 1024:.1f}KB, {d.count_diff:+d} blocks) {d.traceback[0]}"
                )
            self._snapshot = snapshot
        self._step_start = self._batch_last = now

    def finish(self):
        now = self._sample()
        start = self._run_start
        logger.info(
            f"migrate_data[res] run total wall={now['wall'] - start['wall']:.1f}s"
            f" cpu_time={now['cpu'] - start['cpu']:.1f}s cpu={self._cpu_pct(start, now):.0f}%"
            f" rss={_mb(now['rss'])} rss_delta={self._rss_delta(start, now)}"
            f" peak_rss={_mb(_peak_rss_bytes())}"
        )
        if self.trace_memory:
            for stat in self._take_snapshot().statistics("lineno")[:TRACEMALLOC_TOP_N]:
                logger.info(
                    f"migrate_data[res]   live at end: {stat.size / 1024:.1f}KB"
                    f" ({stat.count} blocks) {stat.traceback[0]}"
                )
            tracemalloc.stop()


def _save_timestamps(model_class, pk, src_obj):
    """
    Overwrite auto_now_add / auto_now managed fields with source values.
    QuerySet.update() bypasses Django's auto_now logic entirely.
    """
    update = {}
    if hasattr(src_obj, "created_at") and src_obj.created_at:
        update["created_at"] = src_obj.created_at
    if hasattr(src_obj, "updated_at") and src_obj.updated_at:
        update["updated_at"] = src_obj.updated_at
    if update:
        model_class.objects.filter(pk=pk).update(**update)

def parse_bucket_arg(raw: str) -> str:
    """Accept a bare bucket name like 'mohini-static.shikshalokam.org' (no scheme, no path)."""
    if not BUCKET_NAME_RE.match(raw):
        raise argparse.ArgumentTypeError(
            f"Expected bare bucket name like 'mohini-static.shikshalokam.org', got '{raw}'"
        )
    return raw


def parse_csv_path_arg(raw: str) -> str:
    if not os.path.isfile(raw):
        raise argparse.ArgumentTypeError(f"CSV file not found: '{raw}'")
    return raw


def read_csv_sessions(path: str, column: str, stdout) -> list:
    """Unique, trimmed, non-blank values of `column` (by header name), in file order."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        if column not in headers:
            raise CommandError(f"Column '{column}' not in CSV headers: {headers}")
        total = blanks = 0
        sessions = {}  # dict keeps file order while deduping
        for row in reader:
            total += 1
            value = (row.get(column) or "").strip()
            if not value:
                blanks += 1
                continue
            sessions[value] = None
    stdout.write(
        f"CSV '{path}': {total} rows, {len(sessions)} unique sessions, {blanks} blank skipped"
    )
    if not sessions:
        raise CommandError(f"No session values in column '{column}' of '{path}'")
    return list(sessions)


class S3MigrationError(Exception):
    pass


def s3_key_exists(s3, bucket: str, key: str) -> bool:
    """HEAD bucket/key: True on 200, False on 404, raise ClientError on anything else (e.g. 403)."""
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in S3_NOT_FOUND_CODES:
            return False
        raise
    return True


def copy_s3_key(ctx, key: str, src_prefix: str, target_prefix: str) -> str:
    """
    Copy src_bucket/key to target_bucket/<target_prefix + rest of key>, return new key.
    Key must start with src_prefix. Dry run only HEAD-checks the source object.
    """
    if not key.startswith(src_prefix):
        ctx.stat("S3Object").errored += 1
        raise S3MigrationError(f"key '{key}' does not start with expected prefix '{src_prefix}'")
    new_key = target_prefix + key[len(src_prefix):]

    s = ctx.stat("S3Object")
    s.processed += 1
    try:
        exists = s3_key_exists(ctx.s3, ctx.target_bucket, new_key)
    except ClientError as exc:
        s.errored += 1
        raise S3MigrationError(f"head s3://{ctx.target_bucket}/{new_key} failed: {exc}") from exc
    if exists:
        s.existed += 1
        return new_key

    try:
        if ctx.dry_run:
            ctx.s3.head_object(Bucket=ctx.src_bucket, Key=key)
        else:
            ctx.s3.copy(
                {"Bucket": ctx.src_bucket, "Key": key},
                ctx.target_bucket,
                new_key,
                ExtraArgs={"MetadataDirective": "COPY"},
            )
    except Exception as exc:
        s.errored += 1
        action = "head" if ctx.dry_run else "copy"
        raise S3MigrationError(
            f"{action} s3://{ctx.src_bucket}/{key} -> s3://{ctx.target_bucket}/{new_key} failed: {exc}"
        ) from exc
    s.created += 1
    return new_key


def validate_and_upload_object(ctx, file_url: str, src_prefix: str, target_prefix: str) -> str:
    """
    If file_url is 'https://<src_bucket>/<key>' or 's3://<src_bucket>/<key>', copy the object
    to the target bucket and return the same URL pointing at the target bucket / new key.
    Anything else (empty, legacy base64, other hosts) is returned unchanged.
    """
    if not file_url:
        return file_url
    for scheme in S3_URL_SCHEMES:
        head = f"{scheme}{ctx.src_bucket}/"
        if file_url.startswith(head):
            new_key = copy_s3_key(ctx, file_url[len(head):], src_prefix, target_prefix)
            return f"{scheme}{ctx.target_bucket}/{new_key}"
    ctx.stat("S3Object").skipped += 1
    logger.info(f"migrate_data: file_url not in src bucket, kept as-is: {file_url[:100]}")
    return file_url


@dataclass
class Stats:
    processed: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errored: int = 0
    existed: int = 0


@dataclass
class MigrationContext:
    # S3 object migration
    src_bucket: str = ""
    target_bucket: str = ""
    s3: Any = None
    dry_run: bool = False
    # ID remaps: source_id → target_id
    company_id_map: dict = field(default_factory=dict)
    bot_id_map: dict = field(default_factory=dict)
    image_config_id_map: dict = field(default_factory=dict)
    flow_id_map: dict = field(default_factory=dict)
    profile_id_map: dict = field(default_factory=dict)
    story_id_map: dict = field(default_factory=dict)
    theme_id_map: dict = field(default_factory=dict)
    # Source IDs of CompanyBots created fresh in this run
    new_bot_source_ids: set = field(default_factory=set)
    # Session strings that already exist in target — skip downstream records
    skipped_sessions: set = field(default_factory=set)
    # Sessions that would be created in target (dry-run only) — used by CompanyChat counting
    dry_run_migrated_sessions: set = field(default_factory=set)
    stats: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    # CPU / memory diagnostics (None = off)
    monitor: Optional[ResourceMonitor] = None

    def stat(self, entity) -> Stats:
        if entity not in self.stats:
            self.stats[entity] = Stats()
        return self.stats[entity]

    def log_error(self, entity, source_id, exc):
        self.stat(entity).errored += 1
        self.errors.append({"entity": entity, "source_id": source_id, "error": str(exc)})

    def log_skip(self, entity, source_id, reason):
        self.stat(entity).skipped += 1
        self.errors.append({"entity": entity, "source_id": source_id, "skipped": reason})

    def print_summary(self, stdout):
        stdout.write("\n=== Migration Summary ===")
        for entity, s in self.stats.items():
            stdout.write(
                f"  {entity:<30} processed={s.processed:>6}  created={s.created:>6}"
                f"  updated={s.updated:>6}  skipped={s.skipped:>6}  errored={s.errored:>6}"
                f"  existed={s.existed:>6}"
            )


# ---------------------------------------------------------------------------
# Scope discovery (date range / bot route / sessions CSV)
# ---------------------------------------------------------------------------

@dataclass
class MigrationScope:
    """
    Scoped run: only migrate in-scope ChatSessions, the CompanyChat / Story rows of
    those sessions, and every entity they reference. None means "migrate all".
    """
    # Source ChatSession queryset in scope; CompanyChat / Story follow its sessions
    sessions_qs: Optional[QuerySet] = None
    # Source IDs to restrict each entity (None = all)
    company_ids: Optional[Set[int]] = None
    bot_ids: Optional[Set[int]] = None
    image_config_ids: Optional[Set[int]] = None
    flow_ids: Optional[Set[int]] = None
    profile_ids: Optional[Set[int]] = None
    # CSV session values with no ChatSession in source
    missing_csv_sessions: list = field(default_factory=list)


def build_scope(date_from: Optional[DateArg], date_to: Optional[DateArg],
                session_name: Optional[str], csv_sessions: Optional[list], stdout) -> MigrationScope:
    if csv_sessions is None and not date_from and not date_to and not session_name:
        return MigrationScope()

    route_bot_ids = None
    missing_csv_sessions = []
    if csv_sessions is not None:
        stdout.write(f"Building migration scope for {len(csv_sessions)} CSV sessions ...")
        sessions_qs = ChatSession.objects.using(SRC).filter(session__in=csv_sessions)
        found = set(sessions_qs.values_list("session", flat=True))
        missing_csv_sessions = [s for s in csv_sessions if s not in found]
        if missing_csv_sessions:
            stdout.write(
                f"  WARNING: {len(missing_csv_sessions)} CSV sessions not in source, "
                f"e.g. {missing_csv_sessions[:10]}"
            )
    else:
        stdout.write(
            f"Building migration scope for date_from={date_from} date_to={date_to} "
            f"session_name={session_name!r} ..."
        )
        sessions_qs = ChatSession.objects.using(SRC).filter(**_range_kwargs(date_from, date_to))

        # session_name is a CompanyBot route — resolve its source bot IDs
        if session_name:
            route_bot_ids = set(
                CompanyBot.objects.using(SRC).filter(route=session_name).values_list("id", flat=True)
            )
            if not route_bot_ids:
                stdout.write(f"  WARNING: no CompanyBot route='{session_name}' in source — scope empty")
            sessions_qs = sessions_qs.filter(company_bot_id__in=route_bot_ids)

    # Chats / stories belong to in-scope sessions, regardless of their own created_at
    session_subquery = sessions_qs.values("session")
    chats_qs = CompanyChat.objects.using(SRC).filter(session__in=session_subquery)
    stories_qs = Story.objects.using(SRC).filter(session__in=session_subquery)

    bot_ids = set(sessions_qs.values_list("company_bot_id", flat=True).distinct()) - {None}
    if route_bot_ids is not None:
        bot_ids |= route_bot_ids  # keep the named bot even if it has no sessions in range
    profile_ids = (
        set(sessions_qs.values_list("profile_id", flat=True).distinct())
        | set(chats_qs.values_list("sender_id", flat=True).distinct())
        | set(chats_qs.values_list("receiver_id", flat=True).distinct())
        | set(stories_qs.values_list("author_id", flat=True).distinct())
    ) - {None}

    # Company IDs from both bots and profiles
    company_ids_from_bots = set(
        CompanyBot.objects.using(SRC).filter(id__in=bot_ids).values_list("company_id", flat=True)
    )
    company_ids_from_profiles = set(
        Profile.objects.using(SRC).filter(id__in=profile_ids).values_list("company_id", flat=True)
    )
    company_ids = company_ids_from_bots | company_ids_from_profiles

    # Flow IDs referenced by those bots
    flow_ids = set(
        Flow.objects.using(SRC).filter(bot_id__in=bot_ids).values_list("id", flat=True)
    )
    # Also include flows referenced by profiles (latest_flow)
    flow_ids |= set(
        Profile.objects.using(SRC).filter(id__in=profile_ids, latest_flow_id__isnull=False)
        .values_list("latest_flow_id", flat=True)
    )

    # ImageConfiguration IDs from those flows
    image_config_ids = set(
        Flow.objects.using(SRC).filter(id__in=flow_ids, image_config_id__isnull=False)
        .values_list("image_config_id", flat=True)
    )

    stdout.write(
        f"  Scope: {len(company_ids)} companies, {len(bot_ids)} bots, "
        f"{len(flow_ids)} flows, {len(image_config_ids)} image configs, "
        f"{len(profile_ids)} profiles, {sessions_qs.count()} sessions"
    )

    return MigrationScope(
        sessions_qs=sessions_qs,
        company_ids=company_ids,
        bot_ids=bot_ids,
        image_config_ids=image_config_ids,
        flow_ids=flow_ids,
        profile_ids=profile_ids,
        missing_csv_sessions=missing_csv_sessions,
    )


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Migrate data from source_db to the default (target) DB"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--dry-run", action="store_true", help="Print counts only, no writes")
        parser.add_argument(
            "--date-from",
            type=parse_date_arg,
            default=None,
            help="Migrate transactional data on/after this date/datetime "
                 "('YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]')",
        )
        parser.add_argument(
            "--date-to",
            type=parse_date_arg,
            default=None,
            help="Migrate transactional data on/before this date/datetime "
                 "('YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]')",
        )
        parser.add_argument(
            "--session_name",
            type=str,
            default=None,
            help="Restrict migration to a single CompanyBot route (e.g. shiksha-samvad)",
        )
        parser.add_argument(
            "--sessions-csv",
            type=parse_csv_path_arg,
            default=None,
            help="CSV of session ids to migrate (excludes --date-from/--date-to/--session_name)",
        )
        parser.add_argument(
            "--sessions-csv-column",
            type=str,
            default=None,
            help="Header name of the session id column in --sessions-csv",
        )
        parser.add_argument(
            "--trace-memory",
            action="store_true",
            help="Enable tracemalloc per-line allocation logs (slower; for leak hunting)",
        )
        parser.add_argument(
            "--src-bucket",
            type=parse_bucket_arg,
            required=True,
            help="Source S3 bucket name, e.g. 'qa-mohini-static.shikshalokam.org'",
        )
        parser.add_argument(
            "--target-bucket",
            type=parse_bucket_arg,
            required=True,
            help="Target S3 bucket name, e.g. 'mohini-static.shikshalokam.org'",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        date_from = options["date_from"]
        date_to = options["date_to"]
        session_name = options["session_name"]
        src_bucket = options["src_bucket"]
        target_bucket = options["target_bucket"]
        sessions_csv = options["sessions_csv"]
        sessions_csv_column = options["sessions_csv_column"]
        monitor = ResourceMonitor(trace_memory=options["trace_memory"])

        if src_bucket == target_bucket:
            raise CommandError("--src-bucket and --target-bucket must differ")
        if bool(sessions_csv) != bool(sessions_csv_column):
            raise CommandError("--sessions-csv and --sessions-csv-column must be passed together")
        if sessions_csv and (date_from or date_to or session_name):
            raise CommandError(
                "--sessions-csv cannot be combined with --date-from / --date-to / --session_name"
            )

        s3 = boto3.client(
            "s3",
            region_name=os.getenv("AWS_REGION"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            config=S3_CLIENT_CONFIG,
        )
        for bucket in (src_bucket, target_bucket):
            try:
                s3.head_bucket(Bucket=bucket)
            except Exception as exc:
                raise CommandError(f"S3 bucket '{bucket}' not reachable: {exc}")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no writes will occur\n"))

        csv_sessions = (
            read_csv_sessions(sessions_csv, sessions_csv_column, self.stdout) if sessions_csv else None
        )
        monitor.checkpoint("startup")
        scope = build_scope(date_from, date_to, session_name, csv_sessions, self.stdout)
        monitor.checkpoint("build_scope")
        ctx = MigrationContext(
            src_bucket=src_bucket, target_bucket=target_bucket, s3=s3, dry_run=dry_run, monitor=monitor
        )
        monitor.ctx = ctx
        for session in scope.missing_csv_sessions:
            ctx.log_skip("CSVSession", session, "session not found in source ChatSession")

        steps = [
            ("Company", lambda: migrate_companies(ctx, scope, batch_size, dry_run, self.stdout)),
            ("CompanyBot", lambda: migrate_bots(ctx, scope, batch_size, dry_run, self.stdout)),
            ("ImageConfiguration", lambda: migrate_image_configs(ctx, scope, batch_size, dry_run, self.stdout)),
            ("Flow (pass 1)", lambda: migrate_flows(ctx, scope, batch_size, dry_run, self.stdout)),
            ("PDFTemplates", lambda: migrate_pdf_templates(ctx, scope, batch_size, dry_run, self.stdout)),
            ("Bot sub-models", lambda: migrate_bot_submodels(ctx, scope, batch_size, dry_run, self.stdout)),
            ("Profile", lambda: migrate_profiles(ctx, scope, batch_size, dry_run, self.stdout)),
            ("ChatSession", lambda: migrate_chat_sessions(ctx, scope, batch_size, dry_run, self.stdout)),
            ("CompanyChat", lambda: migrate_company_chats(ctx, scope, batch_size, dry_run, self.stdout)),
            ("Story", lambda: migrate_stories(ctx, scope, batch_size, dry_run, self.stdout)),
            ("StoryMedia", lambda: migrate_story_media(ctx, batch_size, dry_run, self.stdout)),
            ("StoryTranslation", lambda: migrate_story_translations(ctx, batch_size, dry_run, self.stdout)),
        ]

        for label, fn in steps:
            self.stdout.write(f"\n--- {label} ---")
            try:
                fn()
            finally:
                monitor.checkpoint(label)

        ctx.print_summary(self.stdout)
        monitor.finish()

        if ctx.errors and not dry_run:
            with open("migration_errors.jsonl", "w") as f:
                for entry in ctx.errors:
                    f.write(json.dumps(entry, default=str) + "\n")
            self.stdout.write(self.style.ERROR(f"\nErrors/skips logged to migration_errors.jsonl"))


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------

def migrate_companies(ctx, scope, batch_size, dry_run, stdout):
    s = ctx.stat("Company")
    qs = Company.objects.using(SRC)
    if scope.company_ids is not None:
        qs = qs.filter(id__in=scope.company_ids)
    for batch in iter_batches(ctx, "Company", qs, batch_size):
        for src in batch:
            s.processed += 1
            if dry_run:
                ctx.company_id_map[src.id] = src.id  # placeholder so downstream steps count correctly
                continue
            try:
                tgt, created = Company.objects.update_or_create(
                    slug=src.slug,
                    defaults={
                        "name": src.name,
                        "status": src.status,
                        "url": src.url,
                        "logo": src.logo,
                    },
                )
                _save_timestamps(Company, tgt.pk, src)
                ctx.company_id_map[src.id] = tgt.id
                s.created += 1 if created else 0
                s.updated += 0 if created else 1
            except Exception as exc:
                ctx.log_error("Company", src.id, exc)
    stdout.write(f"  {s.processed} processed")


# ---------------------------------------------------------------------------
# CompanyBot
# ---------------------------------------------------------------------------

def migrate_bots(ctx, scope, batch_size, dry_run, stdout):
    s = ctx.stat("CompanyBot")
    qs = CompanyBot.objects.using(SRC)
    if scope.bot_ids is not None:
        qs = qs.filter(id__in=scope.bot_ids)
    for batch in iter_batches(ctx, "CompanyBot", qs, batch_size):
        for src in batch:
            s.processed += 1
            tgt_company_id = ctx.company_id_map.get(src.company_id)
            if tgt_company_id is None:
                ctx.log_error("CompanyBot", src.id, f"company_id {src.company_id} not mapped")
                continue
            if dry_run:
                ctx.bot_id_map[src.id] = src.id  # placeholder so downstream steps count correctly
                ctx.new_bot_source_ids.add(src.id)
                continue
            try:
                tgt, created = CompanyBot.objects.update_or_create(
                    route=src.route,
                    defaults={
                        "name": src.name,
                        "company_id": tgt_company_id,
                        "context": src.context,
                        "max_token": src.max_token,
                        "provider": src.provider,
                        "provider_keys": src.provider_keys,
                        "bot_temperature": src.bot_temperature,
                        "top_k": src.top_k,
                        "llm_model": src.llm_model,
                        "filter_score": src.filter_score,
                        "end_context": src.end_context,
                        "introductory_message": src.introductory_message,
                        "tag_context": src.tag_context,
                        "bot_type": src.bot_type,
                        "strategy": src.strategy,
                        "llm_key": src.llm_key,
                        "dynamic_context": src.dynamic_context,
                        "dynamic_context_type": src.dynamic_context_type,
                        "pre_context": src.pre_context,
                        "tool_context": src.tool_context,
                        "other_params": src.other_params,
                        "connect_timeout": src.connect_timeout,
                        "read_timeout": src.read_timeout,
                        "chat_history_limit": src.chat_history_limit,
                        "stream": src.stream,
                    },
                )
                _save_timestamps(CompanyBot, tgt.pk, src)
                ctx.bot_id_map[src.id] = tgt.id
                if created:
                    s.created += 1
                    ctx.new_bot_source_ids.add(src.id)
                else:
                    s.updated += 1
            except Exception as exc:
                ctx.log_error("CompanyBot", src.id, exc)
    stdout.write(f"  {s.processed} processed, {len(ctx.new_bot_source_ids)} newly created")


# ---------------------------------------------------------------------------
# ImageConfiguration
# ---------------------------------------------------------------------------

def migrate_image_configs(ctx, scope, batch_size, dry_run, stdout):
    s = ctx.stat("ImageConfiguration")
    qs = ImageConfiguration.objects.using(SRC)
    if scope.image_config_ids is not None:
        qs = qs.filter(id__in=scope.image_config_ids)
    for batch in iter_batches(ctx, "ImageConfiguration", qs, batch_size):
        for src in batch:
            s.processed += 1
            if dry_run:
                ctx.image_config_id_map[src.id] = src.id  # placeholder so downstream steps count correctly
                continue
            try:
                tgt, created = ImageConfiguration.objects.update_or_create(
                    name=src.name,
                    defaults={
                        "max_images": src.max_images,
                        "image_size": src.image_size,
                    },
                )
                ctx.image_config_id_map[src.id] = tgt.id
                s.created += 1 if created else 0
                s.updated += 0 if created else 1
            except Exception as exc:
                ctx.log_error("ImageConfiguration", src.id, exc)
    stdout.write(f"  {s.processed} processed")


# ---------------------------------------------------------------------------
# Flow  (2-pass for parent_flow self-ref)
# ---------------------------------------------------------------------------

def migrate_flows(ctx, scope, batch_size, dry_run, stdout):
    s = ctx.stat("Flow")
    qs = Flow.objects.using(SRC)
    if scope.flow_ids is not None:
        qs = qs.filter(id__in=scope.flow_ids)
    src_flows = list(qs)

    for src in src_flows:
        s.processed += 1
        tgt_bot_id = ctx.bot_id_map.get(src.bot_id)
        if tgt_bot_id is None:
            ctx.log_error("Flow", src.id, f"bot_id {src.bot_id} not mapped")
            continue
        if dry_run:
            ctx.flow_id_map[src.id] = src.id  # placeholder so downstream steps count correctly
            continue
        try:
            tgt, created = Flow.objects.update_or_create(
                flow_route=src.flow_route,
                defaults={
                    "flow_name": src.flow_name,
                    "bot_id": tgt_bot_id,
                    "story_bot_id": ctx.bot_id_map.get(src.story_bot_id),
                    "story_validation_bot_id": ctx.bot_id_map.get(src.story_validation_bot_id),
                    "image_config_id": ctx.image_config_id_map.get(src.image_config_id),
                    "parent_flow": None,  # resolved in pass 2
                    "languages": src.languages,
                    "hidden": src.hidden,
                    "active": src.active,
                    "websocket_url": src.websocket_url,
                    "user_type": src.user_type,
                    "create_story": src.create_story,
                },
            )
            _save_timestamps(Flow, tgt.pk, src)
            ctx.flow_id_map[src.id] = tgt.id
            s.created += 1 if created else 0
            s.updated += 0 if created else 1
        except Exception as exc:
            ctx.log_error("Flow", src.id, exc)

    # Pass 2: resolve parent_flow self-reference
    if not dry_run:
        for src in src_flows:
            if (
                src.parent_flow_id
                and src.id in ctx.flow_id_map
                and src.parent_flow_id in ctx.flow_id_map
            ):
                Flow.objects.filter(pk=ctx.flow_id_map[src.id]).update(
                    parent_flow_id=ctx.flow_id_map[src.parent_flow_id]
                )

    stdout.write(f"  {s.processed} processed")


# ---------------------------------------------------------------------------
# PDFTemplates
# ---------------------------------------------------------------------------

def migrate_pdf_templates(ctx, scope, batch_size, dry_run, stdout):
    s = ctx.stat("PDFTemplates")
    qs = PDFTemplates.objects.using(SRC)
    # Filter by flows in scope if scoped run
    if scope.flow_ids is not None:
        qs = qs.filter(flow_id__in=scope.flow_ids)
    for batch in iter_batches(ctx, "PDFTemplates", qs, batch_size):
        for src in batch:
            s.processed += 1
            if dry_run:
                continue
            try:
                tgt, created = PDFTemplates.objects.update_or_create(
                    template_name=src.template_name,
                    defaults={
                        "template": src.template,
                        "user_type": src.user_type,
                        "constants_json": src.constants_json,
                        "flow_id": ctx.flow_id_map.get(src.flow_id),
                    },
                )
                _save_timestamps(PDFTemplates, tgt.pk, src)
                s.created += 1 if created else 0
                s.updated += 0 if created else 1
            except Exception as exc:
                ctx.log_error("PDFTemplates", src.id, exc)
    stdout.write(f"  {s.processed} processed")


# ---------------------------------------------------------------------------
# Bot sub-models  (only for newly created bots)
# ---------------------------------------------------------------------------

def migrate_bot_submodels(ctx, scope, batch_size, dry_run, stdout):
    new_src_ids = ctx.new_bot_source_ids
    all_src_ids = set(ctx.bot_id_map.keys())
    if not all_src_ids:
        stdout.write("  No bots processed — skipping sub-models")
        return
    _migrate_state_machines(ctx, all_src_ids, batch_size, dry_run, stdout)
    _migrate_voices(ctx, all_src_ids, batch_size, dry_run, stdout)
    _migrate_bot_vernacular(ctx, all_src_ids, batch_size, dry_run, stdout)
    if not new_src_ids:
        stdout.write("  No newly created bots — skipping theme and story vernacular sub-models")
        return
    _migrate_themes(ctx, new_src_ids, batch_size, dry_run, stdout)
    _migrate_story_vernacular(ctx, new_src_ids, batch_size, dry_run, stdout)


def _migrate_state_machines(ctx, src_ids, batch_size, dry_run, stdout):
    s = ctx.stat("CompanyStateMachine")
    qs = CompanyStateMachine.objects.using(SRC).filter(company_bot_id__in=src_ids)
    for batch in iter_batches(ctx, "CompanyStateMachine", qs, batch_size):
        for src in batch:
            s.processed += 1
            tgt_bot_id = ctx.bot_id_map.get(src.company_bot_id)
            if tgt_bot_id is None or dry_run:
                continue
            try:
                obj, created = CompanyStateMachine.objects.update_or_create(
                    company_bot_id=tgt_bot_id,
                    step=src.step,
                    defaults={
                        "name": src.name,
                        "use_stage_chats": src.use_stage_chats,
                        "type": src.type,
                        "text_conversion_type": src.text_conversion_type,
                        "bot_question": src.bot_question,
                        "completion_criteria": src.completion_criteria,
                        "context": src.context,
                        "tool_context": src.tool_context,
                        "preprocess_type": src.preprocess_type,
                        "preprocess_prompt": src.preprocess_prompt,
                        "preprocess_output_mode": src.preprocess_output_mode,
                        "postprocess_type": src.postprocess_type,
                        "postprocess_prompt": src.postprocess_prompt,
                        "postprocess_output_mode": src.postprocess_output_mode,
                        "skip_to_step": src.skip_to_step,
                        "operation_type": src.operation_type,
                        "skip_if_authenticated": src.skip_if_authenticated,
                        "preprocess_bot_id": ctx.bot_id_map.get(src.preprocess_bot_id),
                        "postprocess_bot_id": ctx.bot_id_map.get(src.postprocess_bot_id),
                    },
                )
                _save_timestamps(CompanyStateMachine, obj.pk, src)
                if created:
                    s.created += 1
                else:
                    s.updated += 1
            except Exception as exc:
                ctx.log_error("CompanyStateMachine", src.id, exc)
    stdout.write(f"  CompanyStateMachine: {s.processed} processed")


def _migrate_voices(ctx, src_ids, batch_size, dry_run, stdout):
    s = ctx.stat("Voice")
    qs = Voice.objects.using(SRC).filter(company_bot_id__in=src_ids)
    pre_existing_count = 0
    if not dry_run:
        # Voice has no unique natural key (multiple voices per bot+language are valid),
        # so delete all existing voices for these bots and recreate from source.
        tgt_bot_ids = [ctx.bot_id_map[sid] for sid in src_ids if sid in ctx.bot_id_map]
        pre_existing_count = Voice.objects.filter(company_bot_id__in=tgt_bot_ids).count()
        Voice.objects.filter(company_bot_id__in=tgt_bot_ids).delete()
    for batch in iter_batches(ctx, "Voice", qs, batch_size):
        for src in batch:
            s.processed += 1
            tgt_bot_id = ctx.bot_id_map.get(src.company_bot_id)
            if tgt_bot_id is None or dry_run:
                continue
            try:
                obj = Voice(
                    type=src.type,
                    provider=src.provider,
                    name=src.name,
                    sample_link=src.sample_link,
                    language=src.language,
                    provider_code=src.provider_code,
                    gender=src.gender,
                    voice_speed=src.voice_speed,
                    other_params=src.other_params,
                    company_bot_id=tgt_bot_id,
                )
                obj.save()
                _save_timestamps(Voice, obj.pk, src)
                s.created += 1
            except Exception as exc:
                ctx.log_error("Voice", src.id, exc)
    # Reclassify: voices that replaced pre-existing ones count as updated
    replaced = min(pre_existing_count, s.created)
    s.updated += replaced
    s.created -= replaced
    stdout.write(f"  Voice: {s.processed} processed")


def _migrate_themes(ctx, new_src_ids, batch_size, dry_run, stdout):
    s = ctx.stat("Theme")
    src_themes = list(Theme.objects.using(SRC).filter(bot_id__in=new_src_ids))
    for src in src_themes:
        s.processed += 1
        tgt_bot_id = ctx.bot_id_map.get(src.bot_id)
        if tgt_bot_id is None or dry_run:
            continue
        try:
            obj = Theme(
                themes=src.themes,
                theme_type=src.theme_type,
                bot_id=tgt_bot_id,
                master_theme=None,
            )
            obj.save()
            _save_timestamps(Theme, obj.pk, src)
            ctx.theme_id_map[src.id] = obj.id
            s.created += 1
        except Exception as exc:
            ctx.log_error("Theme", src.id, exc)
    # Pass 2: resolve master_theme self-reference
    if not dry_run:
        for src in src_themes:
            if (
                src.master_theme_id
                and src.id in ctx.theme_id_map
                and src.master_theme_id in ctx.theme_id_map
            ):
                Theme.objects.filter(pk=ctx.theme_id_map[src.id]).update(
                    master_theme_id=ctx.theme_id_map[src.master_theme_id]
                )
    stdout.write(f"  Theme: {s.processed} processed")


def _migrate_bot_vernacular(ctx, src_ids, batch_size, dry_run, stdout):
    s = ctx.stat("BotVernacular")
    qs = BotVernacular.objects.using(SRC).filter(company_bot_id__in=src_ids)
    for batch in iter_batches(ctx, "BotVernacular", qs, batch_size):
        for src in batch:
            s.processed += 1
            tgt_bot_id = ctx.bot_id_map.get(src.company_bot_id)
            if tgt_bot_id is None or dry_run:
                continue
            try:
                obj, created = BotVernacular.objects.update_or_create(
                    company_bot_id=tgt_bot_id,
                    language=src.language,
                    defaults={
                        "introductory_message": src.introductory_message,
                        "alt_introductory_message": src.alt_introductory_message,
                        "name": src.name,
                        "error_message": src.error_message,
                    },
                )
                _save_timestamps(BotVernacular, obj.pk, src)
                if created:
                    s.created += 1
                else:
                    s.updated += 1
            except Exception as exc:
                ctx.log_error("BotVernacular", src.id, exc)
    stdout.write(f"  BotVernacular: {s.processed} processed")


def _migrate_story_vernacular(ctx, new_src_ids, batch_size, dry_run, stdout):
    s = ctx.stat("StoryVernacular")
    qs = StoryVernacular.objects.using(SRC).filter(company_bot_id__in=new_src_ids)
    for batch in iter_batches(ctx, "StoryVernacular", qs, batch_size):
        for src in batch:
            s.processed += 1
            tgt_bot_id = ctx.bot_id_map.get(src.company_bot_id)
            if tgt_bot_id is None or dry_run:
                continue
            try:
                obj = StoryVernacular(
                    translation_json=src.translation_json,
                    language=src.language,
                    company_bot_id=tgt_bot_id,
                )
                obj.save()
                _save_timestamps(StoryVernacular, obj.pk, src)
                s.created += 1
            except Exception as exc:
                ctx.log_error("StoryVernacular", src.id, exc)
    stdout.write(f"  StoryVernacular: {s.processed} processed")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def migrate_profiles(ctx, scope, batch_size, dry_run, stdout):
    s = ctx.stat("Profile")
    qs = Profile.objects.using(SRC)
    if scope.profile_ids is not None:
        qs = qs.filter(id__in=scope.profile_ids)
    for batch in iter_batches(ctx, "Profile", qs, batch_size):
        for src in batch:
            s.processed += 1
            tgt_company_id = ctx.company_id_map.get(src.company_id)
            if tgt_company_id is None:
                ctx.log_error("Profile", src.id, f"company_id {src.company_id} not mapped")
                continue
            if dry_run:
                ctx.profile_id_map[src.id] = src.id  # placeholder so downstream steps count correctly
                continue
            try:
                tgt, created = Profile.objects.update_or_create(
                    email=src.email,
                    company_id=tgt_company_id,
                    defaults={
                        "first_name": src.first_name,
                        "userid": src.userid,
                        "last_name": src.last_name,
                        "phone": src.phone,
                        "alternate_phone": src.alternate_phone,
                        "country": src.country,
                        "status": src.status,
                        "company_id": tgt_company_id,
                        "password": src.password,
                        "profile_type": src.profile_type,
                        "profile_code": src.profile_code,
                        "location": src.location,
                        "caste": src.caste,
                        "gender": src.gender,
                        "designation": src.designation,
                        "org_associated": src.org_associated,
                        "product_interested": src.product_interested,
                        "company_spoc": src.company_spoc,
                        "other_params": src.other_params,
                        "source": src.source,
                        "preferred_route": src.preferred_route,
                        "latest_flow_used": src.latest_flow_used,
                        "latest_flow_id": ctx.flow_id_map.get(src.latest_flow_id) if src.latest_flow_id else None,
                    },
                )
                _save_timestamps(Profile, tgt.pk, src)
                ctx.profile_id_map[src.id] = tgt.id
                s.created += 1 if created else 0
                s.updated += 0 if created else 1
            except Exception as exc:
                ctx.log_error("Profile", src.id, exc)
    stdout.write(f"  {s.processed} processed")


# ---------------------------------------------------------------------------
# ChatSession
# ---------------------------------------------------------------------------

def migrate_chat_sessions(ctx, scope, batch_size, dry_run, stdout):
    s = ctx.stat("ChatSession")
    existing = set(ChatSession.objects.values_list("session", flat=True))

    qs = scope.sessions_qs if scope.sessions_qs is not None else ChatSession.objects.using(SRC).all()

    for batch in iter_batches(ctx, "ChatSession", qs, batch_size):
        for src in batch:
            s.processed += 1
            if src.session in existing:
                ctx.skipped_sessions.add(src.session)
                ctx.log_skip("ChatSession", src.id, f"session '{src.session}' exists in target")
                continue
            if dry_run:
                ctx.dry_run_migrated_sessions.add(src.session)
                continue
            try:
                obj = ChatSession(
                    session=src.session,
                    profile_id=ctx.profile_id_map.get(src.profile_id) if src.profile_id else None,
                    company_bot_id=ctx.bot_id_map.get(src.company_bot_id) if src.company_bot_id else None,
                    language=src.language,
                    title=src.title,
                    summary=src.summary,
                    current_step=src.current_step,
                    session_context=src.session_context,
                    session_status=src.session_status,
                    project_id=src.project_id,
                    user_id=src.user_id,
                    session_type=src.session_type,
                    other_params=src.other_params,
                )
                obj.save()
                _save_timestamps(ChatSession, obj.pk, src)
                s.created += 1
            except Exception as exc:
                ctx.log_error("ChatSession", src.id, exc)
    stdout.write(f"  {s.processed} processed, {s.skipped} skipped (already in target)")


# ---------------------------------------------------------------------------
# CompanyChat
# ---------------------------------------------------------------------------

def migrate_company_chats(ctx, scope, batch_size, dry_run, stdout):
    s = ctx.stat("CompanyChat")
    valid_sessions = ctx.dry_run_migrated_sessions if dry_run else set(ChatSession.objects.values_list("session", flat=True))
    qs = _apply_session_scope(CompanyChat.objects.using(SRC).all(), scope)

    for batch in iter_batches(ctx, "CompanyChat", qs, batch_size):
        for src in batch:
            s.processed += 1
            if src.session in ctx.skipped_sessions:
                s.skipped += 1
                continue
            if src.session not in valid_sessions:
                ctx.log_skip("CompanyChat", src.id, f"session '{src.session}' has no parent ChatSession in source")
                continue

            # Copy S3 objects before insert; any copy failure skips the row
            try:
                file_url = _migrate_chat_file_urls(ctx, src)
            except S3MigrationError as exc:
                ctx.log_error("CompanyChat", src.id, exc)
                continue
            if dry_run:
                continue
            try:
                obj = CompanyChat(
                    message=src.message,
                    translated_message=src.translated_message,
                    chunks=src.chunks,
                    sender_id=ctx.profile_id_map.get(src.sender_id) if src.sender_id else None,
                    receiver_id=ctx.profile_id_map.get(src.receiver_id) if src.receiver_id else None,
                    session=src.session,
                    created_at=src.created_at,  # not auto_now_add — settable directly
                    status=src.status,
                    feedback=src.feedback,
                    source=src.source,
                    source_msg_id=src.source_msg_id,
                    whatsapp_message_id=src.whatsapp_message_id,
                    message_type=src.message_type,
                    stage=src.stage,
                    other_params=src.other_params,
                    file_url=file_url,
                )
                obj.save()
                if src.updated_at:
                    CompanyChat.objects.filter(pk=obj.pk).update(updated_at=src.updated_at)
                s.created += 1
            except Exception as exc:
                ctx.log_error("CompanyChat", src.id, exc)
    stdout.write(f"  {s.processed} processed, {s.skipped} skipped")


def _migrate_chat_file_urls(ctx, src) -> Optional[str]:
    """file_url is comma-separated; each part is copied independently (non-S3 parts kept as-is)."""
    if not src.file_url:
        return src.file_url
    prefix = f"chatbot/companychat/{src.session}/"
    return ",".join(
        validate_and_upload_object(ctx, part, prefix, prefix) for part in src.file_url.split(",")
    )


# ---------------------------------------------------------------------------
# Story
# ---------------------------------------------------------------------------

def migrate_stories(ctx, scope, batch_size, dry_run, stdout):
    s = ctx.stat("Story")
    existing = set(Story.objects.values_list("session", flat=True))
    qs = _apply_session_scope(Story.objects.using(SRC).all(), scope)

    for batch in iter_batches(ctx, "Story", qs, batch_size):
        for src in batch:
            s.processed += 1
            if src.session in existing:
                ctx.skipped_sessions.add(src.session)
                ctx.log_skip("Story", src.id, f"session '{src.session}' exists in target")
                continue
            if dry_run:
                ctx.story_id_map[src.id] = src.id  # placeholder so downstream steps count correctly
                continue
            try:
                obj = Story(
                    title=src.title,
                    author_id=ctx.profile_id_map.get(src.author_id) if src.author_id else None,
                    content=src.content,
                    blurb=src.blurb,
                    tweet=src.tweet,
                    session=src.session,
                    objective=src.objective,
                    action_steps=src.action_steps,
                    impact=src.impact,
                    micro_improvement=src.micro_improvement,
                    location=src.location,
                    district=src.district,
                    state=src.state,
                    block=src.block,
                    formatted_content=src.formatted_content,
                    language=src.language,
                    source=src.source,
                    story_code=src.story_code,
                    stage=src.stage,
                    summary=src.summary,
                    other_params=src.other_params,
                    client_created_at=src.client_created_at,
                    client_updated_at=src.client_updated_at,
                    validation_logs=src.validation_logs,
                )
                obj.save()
                _save_timestamps(Story, obj.pk, src)
                ctx.story_id_map[src.id] = obj.id
                s.created += 1
            except Exception as exc:
                ctx.log_error("Story", src.id, exc)
    stdout.write(f"  {s.processed} processed, {s.skipped} skipped (already in target)")


# ---------------------------------------------------------------------------
# StoryMedia
# ---------------------------------------------------------------------------

def migrate_story_media(ctx, batch_size, dry_run, stdout):
    s = ctx.stat("StoryMedia")
    qs = StoryMedia.objects.using(SRC).filter(story_id__in=ctx.story_id_map.keys())
    for batch in iter_batches(ctx, "StoryMedia", qs, batch_size):
        for src in batch:
            s.processed += 1
            tgt_story_id = ctx.story_id_map.get(src.story_id)
            if tgt_story_id is None:
                continue

            # Copy S3 objects before insert; any copy failure skips the row
            src_prefix = f"chatbot/storymedia/{src.story_id}/"
            target_prefix = f"chatbot/storymedia/{tgt_story_id}/"
            try:
                file_key = copy_s3_key(ctx, src.file.name, src_prefix, target_prefix) if src.file else src.file
                file_url = validate_and_upload_object(ctx, src.file_url, src_prefix, target_prefix)
            except S3MigrationError as exc:
                ctx.log_error("StoryMedia", src.id, exc)
                continue
            if dry_run:
                continue

            try:
                obj = StoryMedia(
                    story_id=tgt_story_id,
                    name=src.name,
                    include_in_story=src.include_in_story,
                    base64_str=src.base64_str,
                    source_path=src.source_path,
                    media_type=src.media_type,
                    file=file_key,
                    file_url=file_url,
                )
                obj.save()
                _save_timestamps(StoryMedia, obj.pk, src)
                s.created += 1
            except Exception as exc:
                ctx.log_error("StoryMedia", src.id, exc)
    stdout.write(f"  {s.processed} processed")


# ---------------------------------------------------------------------------
# StoryTranslation
# ---------------------------------------------------------------------------

def migrate_story_translations(ctx, batch_size, dry_run, stdout):
    s = ctx.stat("StoryTranslation")
    qs = StoryTranslation.objects.using(SRC).filter(story_id__in=ctx.story_id_map.keys())
    for batch in iter_batches(ctx, "StoryTranslation", qs, batch_size):
        for src in batch:
            s.processed += 1
            tgt_story_id = ctx.story_id_map.get(src.story_id)
            if tgt_story_id is None:
                s.skipped += 1
                continue
            if dry_run:
                continue
            try:
                if StoryTranslation.objects.filter(story_id=tgt_story_id, language=src.language).exists():
                    s.skipped += 1
                    continue
                obj = StoryTranslation(
                    story_id=tgt_story_id,
                    language=src.language,
                    title=src.title,
                    content=src.content,
                    blurb=src.blurb,
                    tweet=src.tweet,
                    objective=src.objective,
                    action_steps=src.action_steps,
                    impact=src.impact,
                    micro_improvement=src.micro_improvement,
                    formatted_content=src.formatted_content,
                    location=src.location,
                    district=src.district,
                    state=src.state,
                    block=src.block,
                    other_params=src.other_params,
                )
                obj.save()
                _save_timestamps(StoryTranslation, obj.pk, src)
                s.created += 1
            except Exception as exc:
                ctx.log_error("StoryTranslation", src.id, exc)
    stdout.write(f"  {s.processed} processed, {s.skipped} skipped (already exists or parent story not migrated)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_session_scope(qs, scope: MigrationScope):
    """Restrict a source CompanyChat / Story queryset to the sessions of in-scope ChatSessions."""
    if scope.sessions_qs is not None:
        qs = qs.filter(session__in=scope.sessions_qs.values("session"))
    return qs

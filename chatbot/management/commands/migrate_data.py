"""
Migrate data from a source Postgres DB to the target DB using Django ORM.

Source DB must be configured as 'source_db' in DATABASES (via SOURCE_DATABASE_* env vars).

Usage:
    # Migrate everything
    python manage.py migrate_data

    # Migrate only transactional data within a date range, plus all referenced
    # Company / CompanyBot / Flow / ImageConfiguration / PDFTemplates / Profile
    python manage.py migrate_data --date-from 2024-01-01 --date-to 2024-12-31

    # Dry run (count rows, no writes)
    python manage.py migrate_data --dry-run [--date-from ...] [--date-to ...]

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
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import islice
from typing import Optional, Set

from django.core.management.base import BaseCommand

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
from chatbot.models.story_models import Story, StoryTranslation
from chatbot.models.story_vernacular_model import StoryVernacular
from chatbot.models.theme_models import Theme

SRC = "source_db"


def chunked(iterable, n):
    it = iter(iterable)
    while chunk := list(islice(it, n)):
        yield chunk


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


@dataclass
class Stats:
    processed: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errored: int = 0


@dataclass
class MigrationContext:
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
    stats: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

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
            )


# ---------------------------------------------------------------------------
# Date-range scope discovery
# ---------------------------------------------------------------------------

@dataclass
class MigrationScope:
    """
    When date range is provided, only migrate entities referenced by
    transactional records (ChatSession, CompanyChat, Story) in that range.
    None means "migrate all".
    """
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    # Source IDs to restrict each entity (None = all)
    company_ids: Optional[Set[int]] = None
    bot_ids: Optional[Set[int]] = None
    image_config_ids: Optional[Set[int]] = None
    flow_ids: Optional[Set[int]] = None
    profile_ids: Optional[Set[int]] = None


def build_scope(date_from: Optional[date], date_to: Optional[date], stdout) -> MigrationScope:
    if not date_from and not date_to:
        return MigrationScope()

    stdout.write(f"Building migration scope for {date_from} → {date_to} ...")

    date_filter = {}
    if date_from:
        date_filter["created_at__date__gte"] = date_from
    if date_to:
        date_filter["created_at__date__lte"] = date_to

    # Collect referenced source IDs from transactional models
    sessions_qs = ChatSession.objects.using(SRC).filter(**date_filter)
    chats_qs = CompanyChat.objects.using(SRC).filter(**date_filter)
    stories_qs = Story.objects.using(SRC).filter(**date_filter)

    bot_ids = set(sessions_qs.values_list("company_bot_id", flat=True).distinct()) - {None}
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
        f"{len(profile_ids)} profiles"
    )

    return MigrationScope(
        date_from=date_from,
        date_to=date_to,
        company_ids=company_ids,
        bot_ids=bot_ids,
        image_config_ids=image_config_ids,
        flow_ids=flow_ids,
        profile_ids=profile_ids,
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
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            default=None,
            help="Migrate transactional data on/after this date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--date-to",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            default=None,
            help="Migrate transactional data on/before this date (YYYY-MM-DD)",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        date_from = options["date_from"]
        date_to = options["date_to"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no writes will occur\n"))

        scope = build_scope(date_from, date_to, self.stdout)
        ctx = MigrationContext()

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
            ("StoryTranslation", lambda: migrate_story_translations(ctx, batch_size, dry_run, self.stdout)),
        ]

        for label, fn in steps:
            self.stdout.write(f"\n--- {label} ---")
            fn()

        ctx.print_summary(self.stdout)

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
    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
        for src in batch:
            s.processed += 1
            if dry_run:
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
    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
        for src in batch:
            s.processed += 1
            tgt_company_id = ctx.company_id_map.get(src.company_id)
            if tgt_company_id is None:
                ctx.log_error("CompanyBot", src.id, f"company_id {src.company_id} not mapped")
                continue
            if dry_run:
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
    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
        for src in batch:
            s.processed += 1
            if dry_run:
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
    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
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
    if not new_src_ids:
        stdout.write("  No newly created bots — skipping sub-models")
        return
    _migrate_state_machines(ctx, new_src_ids, batch_size, dry_run, stdout)
    _migrate_voices(ctx, new_src_ids, batch_size, dry_run, stdout)
    _migrate_themes(ctx, new_src_ids, batch_size, dry_run, stdout)
    _migrate_bot_vernacular(ctx, new_src_ids, batch_size, dry_run, stdout)
    _migrate_story_vernacular(ctx, new_src_ids, batch_size, dry_run, stdout)


def _migrate_state_machines(ctx, new_src_ids, batch_size, dry_run, stdout):
    s = ctx.stat("CompanyStateMachine")
    qs = CompanyStateMachine.objects.using(SRC).filter(company_bot_id__in=new_src_ids)
    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
        for src in batch:
            s.processed += 1
            tgt_bot_id = ctx.bot_id_map.get(src.company_bot_id)
            if tgt_bot_id is None or dry_run:
                continue
            try:
                obj = CompanyStateMachine(
                    name=src.name,
                    step=src.step,
                    use_stage_chats=src.use_stage_chats,
                    type=src.type,
                    text_conversion_type=src.text_conversion_type,
                    bot_question=src.bot_question,
                    completion_criteria=src.completion_criteria,
                    context=src.context,
                    tool_context=src.tool_context,
                    preprocess_type=src.preprocess_type,
                    preprocess_prompt=src.preprocess_prompt,
                    preprocess_output_mode=src.preprocess_output_mode,
                    postprocess_type=src.postprocess_type,
                    postprocess_prompt=src.postprocess_prompt,
                    postprocess_output_mode=src.postprocess_output_mode,
                    skip_to_step=src.skip_to_step,
                    operation_type=src.operation_type,
                    skip_if_authenticated=src.skip_if_authenticated,
                    company_bot_id=tgt_bot_id,
                    preprocess_bot_id=ctx.bot_id_map.get(src.preprocess_bot_id),
                    postprocess_bot_id=ctx.bot_id_map.get(src.postprocess_bot_id),
                )
                obj.save()
                _save_timestamps(CompanyStateMachine, obj.pk, src)
                s.created += 1
            except Exception as exc:
                ctx.log_error("CompanyStateMachine", src.id, exc)
    stdout.write(f"  CompanyStateMachine: {s.processed} processed")


def _migrate_voices(ctx, new_src_ids, batch_size, dry_run, stdout):
    s = ctx.stat("Voice")
    qs = Voice.objects.using(SRC).filter(company_bot_id__in=new_src_ids)
    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
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


def _migrate_bot_vernacular(ctx, new_src_ids, batch_size, dry_run, stdout):
    s = ctx.stat("BotVernacular")
    qs = BotVernacular.objects.using(SRC).filter(company_bot_id__in=new_src_ids)
    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
        for src in batch:
            s.processed += 1
            tgt_bot_id = ctx.bot_id_map.get(src.company_bot_id)
            if tgt_bot_id is None or dry_run:
                continue
            try:
                obj = BotVernacular(
                    language=src.language,
                    introductory_message=src.introductory_message,
                    alt_introductory_message=src.alt_introductory_message,
                    name=src.name,
                    error_message=src.error_message,
                    company_bot_id=tgt_bot_id,
                )
                obj.save()
                _save_timestamps(BotVernacular, obj.pk, src)
                s.created += 1
            except Exception as exc:
                ctx.log_error("BotVernacular", src.id, exc)
    stdout.write(f"  BotVernacular: {s.processed} processed")


def _migrate_story_vernacular(ctx, new_src_ids, batch_size, dry_run, stdout):
    s = ctx.stat("StoryVernacular")
    qs = StoryVernacular.objects.using(SRC).filter(company_bot_id__in=new_src_ids)
    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
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
    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
        for src in batch:
            s.processed += 1
            tgt_company_id = ctx.company_id_map.get(src.company_id)
            if tgt_company_id is None:
                ctx.log_error("Profile", src.id, f"company_id {src.company_id} not mapped")
                continue
            if dry_run:
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

    date_filter = _date_filter(scope)
    qs = ChatSession.objects.using(SRC).filter(**date_filter)

    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
        for src in batch:
            s.processed += 1
            if src.session in existing:
                ctx.skipped_sessions.add(src.session)
                ctx.log_skip("ChatSession", src.id, f"session '{src.session}' exists in target")
                continue
            if dry_run:
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
    valid_sessions = set(ChatSession.objects.values_list("session", flat=True))
    date_filter = _date_filter(scope)
    qs = CompanyChat.objects.using(SRC).filter(**date_filter)

    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
        for src in batch:
            s.processed += 1
            if src.session in ctx.skipped_sessions:
                s.skipped += 1
                continue
            if src.session not in valid_sessions:
                ctx.log_skip("CompanyChat", src.id, f"session '{src.session}' has no parent ChatSession in source")
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
                    file_url=src.file_url,
                )
                obj.save()
                if src.updated_at:
                    CompanyChat.objects.filter(pk=obj.pk).update(updated_at=src.updated_at)
                s.created += 1
            except Exception as exc:
                ctx.log_error("CompanyChat", src.id, exc)
    stdout.write(f"  {s.processed} processed, {s.skipped} skipped")


# ---------------------------------------------------------------------------
# Story
# ---------------------------------------------------------------------------

def migrate_stories(ctx, scope, batch_size, dry_run, stdout):
    s = ctx.stat("Story")
    existing = set(Story.objects.values_list("session", flat=True))
    date_filter = _date_filter(scope)
    qs = Story.objects.using(SRC).filter(**date_filter)

    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
        for src in batch:
            s.processed += 1
            if src.session in existing:
                ctx.skipped_sessions.add(src.session)
                ctx.log_skip("Story", src.id, f"session '{src.session}' exists in target")
                continue
            if dry_run:
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
# StoryTranslation
# ---------------------------------------------------------------------------

def migrate_story_translations(ctx, batch_size, dry_run, stdout):
    s = ctx.stat("StoryTranslation")
    qs = StoryTranslation.objects.using(SRC).filter(story_id__in=ctx.story_id_map.keys())
    for batch in chunked(qs.iterator(chunk_size=batch_size), batch_size):
        for src in batch:
            s.processed += 1
            tgt_story_id = ctx.story_id_map.get(src.story_id)
            if tgt_story_id is None:
                s.skipped += 1
                continue
            if dry_run:
                continue
            try:
                tgt, created = StoryTranslation.objects.update_or_create(
                    story_id=tgt_story_id,
                    language=src.language,
                    defaults={
                        "title": src.title,
                        "content": src.content,
                        "blurb": src.blurb,
                        "tweet": src.tweet,
                        "objective": src.objective,
                        "action_steps": src.action_steps,
                        "impact": src.impact,
                        "micro_improvement": src.micro_improvement,
                        "formatted_content": src.formatted_content,
                        "location": src.location,
                        "district": src.district,
                        "state": src.state,
                        "block": src.block,
                        "other_params": src.other_params,
                    },
                )
                _save_timestamps(StoryTranslation, tgt.pk, src)
                s.created += 1 if created else 0
                s.updated += 0 if created else 1
            except Exception as exc:
                ctx.log_error("StoryTranslation", src.id, exc)
    stdout.write(f"  {s.processed} processed, {s.skipped} skipped (parent story not migrated)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_filter(scope: MigrationScope) -> dict:
    f = {}
    if scope.date_from:
        f["created_at__date__gte"] = scope.date_from
    if scope.date_to:
        f["created_at__date__lte"] = scope.date_to
    return f

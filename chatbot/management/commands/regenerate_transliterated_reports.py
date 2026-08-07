"""
Re-transliterate stored chats for given state-machine stage(s), then delete +
regenerate the affected Story/StoryTranslation via create_story_object
(--report-version 1, default) or generate_story (--report-version 2).

Usage
-----
    python manage.py regenerate_transliterated_reports \
        --statemachine INTRODUCTION,ORGANIZATION \
        --route /shikshalokam_chaupal \
        --timestamp-from "2026-06-01" --timestamp-to "2026-06-30 23:59"

    # Preview only
    python manage.py regenerate_transliterated_reports \
        --statemachine INTRODUCTION --dry-run

    # Force v2 (/end-story/v2)
    python manage.py regenerate_transliterated_reports \
        --statemachine INTRODUCTION --report-version 2

See --help for the full argument list.
"""

import logging

from collections import namedtuple
from datetime import datetime, time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from chatbot.models import (
    CompanyBot,
    CompanyChat,
    ChatSession,
    ChatType,
    Flow,
    SessionFlowName,
    Story,
    StoryTranslation,
    Voice,
    VoiceType,
)
from chatbot.utils.transliterate_utils import (
    transliterate_text,
    get_transliteration_output,
)
from chatbot.utils.story_utils.story_utils import (
    create_story_object,
    generate_story,
    get_story_company_bot,
)


logger = logging.getLogger("django")

# shikshalokam_chaupal reports are generated with the GuestDiscussion flow.
SESSION_TYPE_TO_FLOW = {
    ChatType.shikshaChaupal.value: SessionFlowName.GuestDiscussion.value,
}

DateArg = namedtuple("DateArg", ["value", "has_time"])


def parse_date_arg(raw):
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
        raise CommandError(f"Use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]', got '{raw}'")


def _make_aware(dt):
    if getattr(settings, "USE_TZ", False) and timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _created_at_range(date_from, date_to):
    f = {}
    if date_from is not None:
        start = date_from.value if date_from.has_time else datetime.combine(date_from.value.date(), time.min)
        f["created_at__gte"] = _make_aware(start)
    if date_to is not None:
        end = date_to.value if date_to.has_time else datetime.combine(date_to.value.date(), time.max)
        f["created_at__lte"] = _make_aware(end)
    return f


class Command(BaseCommand):
    help = (
        "Re-transliterate stored chats for given state-machine stages, then "
        "delete and regenerate the affected reports."
    )

    MAX_REPORT_ATTEMPTS = 3

    def add_arguments(self, parser):
        parser.add_argument("--timestamp-from", type=str, default=None)
        parser.add_argument("--timestamp-to", type=str, default=None)
        parser.add_argument("--session-type", type=str, default=None)
        parser.add_argument("--session", type=str, default=None)
        parser.add_argument("--statemachine", type=str, required=True)
        parser.add_argument("--route", type=str, default="/shikshalokam_chaupal")
        parser.add_argument("--flow", type=str, default=None)
        parser.add_argument("--report-version", type=int, choices=[1, 2], default=1)
        parser.add_argument("--bot-profile-id", type=int, default=1)
        parser.add_argument("--skip-transliterate", action="store_true")
        parser.add_argument("--skip-report", action="store_true")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")

    # ------------------------------------------------------------------ #
    def handle(self, *args, **opts):
        stages = [s.strip() for s in (opts["statemachine"] or "").split(",") if s.strip()]
        if not stages:
            raise CommandError("--statemachine must list at least one stage name.")

        date_from = parse_date_arg(opts["timestamp_from"]) if opts["timestamp_from"] else None
        date_to = parse_date_arg(opts["timestamp_to"]) if opts["timestamp_to"] else None

        session_types = [s.strip() for s in (opts["session_type"] or "").split(",") if s.strip()]
        session_ids = [s.strip() for s in (opts["session"] or "").split(",") if s.strip()]
        routes = [r.strip() for r in (opts["route"] or "").split(",") if r.strip()]
        if not routes:
            raise CommandError("--route must list at least one bot route.")

        self.flow_override = opts["flow"]
        self.bot_profile_id = opts["bot_profile_id"]
        self.report_version = opts["report_version"]
        self.entry_label, self.entry_fn = (
            ("v1", create_story_object) if self.report_version == 1 else ("v2", generate_story)
        )
        self._story_voice_cache = {}
        self._flow_row_cache = {}
        skip_transliterate = opts["skip_transliterate"]
        skip_report = opts["skip_report"]
        limit = opts["limit"]
        dry_run = opts["dry_run"]

        logger.info(
            "[regen] START routes=%s stages=%s from=%s to=%s session_types=%s sessions=%s "
            "skip_transliterate=%s skip_report=%s limit=%s dry_run=%s bot_profile_id=%s report_version=%s",
            routes, stages, opts["timestamp_from"], opts["timestamp_to"],
            session_types or "ANY", session_ids or "ANY",
            skip_transliterate, skip_report, limit, dry_run, self.bot_profile_id, self.report_version,
        )

        g_affected = g_r_success = g_r_failed = 0
        for route in routes:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n### route {route}"))
            affected, r_success, r_failed = self._process_route(
                route=route, stages=stages, date_from=date_from, date_to=date_to,
                session_types=session_types, session_ids=session_ids,
                skip_transliterate=skip_transliterate, skip_report=skip_report,
                limit=limit, dry_run=dry_run,
            )
            g_affected += affected
            g_r_success += r_success
            g_r_failed += r_failed

        self._summary(g_affected, g_r_success, g_r_failed, dry_run)

    # ------------------------------------------------------------------ #
    def _process_route(self, route, stages, date_from, date_to, session_types,
                       session_ids, skip_transliterate, skip_report, limit, dry_run):
        """Scope + Step 1 + Step 2 for a single bot route. Returns
        (affected_sessions, reports_success, reports_failed)."""
        logger.info("[regen] route=%s scoping sessions", route)
        company_bot = CompanyBot.objects.filter(route=route).first()
        if not company_bot:
            self.stdout.write(self.style.ERROR(f"CompanyBot route='{route}' not found, skipping."))
            logger.error("[regen] route=%s CompanyBot not found, skipping route", route)
            return 0, 0, 0

        if session_ids:
            sessions_qs = ChatSession.objects.filter(session__in=session_ids).exclude(language="en")
        else:
            sessions_qs = ChatSession.objects.filter(company_bot=company_bot).exclude(language="en")
        if session_types:
            sessions_qs = sessions_qs.filter(session_type__in=session_types)
        sessions_qs = sessions_qs.order_by("created_at")
        if limit and limit > 0:
            sessions_qs = sessions_qs[:limit]

        session_language = {s.session: s.language for s in sessions_qs}
        if not session_language:
            self.stdout.write(self.style.WARNING("  No matching non-English sessions for this route."))
            logger.warning(
                "[regen] route=%s no non-English sessions (session_types=%s sessions=%s)",
                route, session_types or "ANY", session_ids or "ANY",
            )
            return 0, 0, 0

        chat_filter = {
            "session__in": list(session_language.keys()),
            "stage__in": stages,
            "translated_message__isnull": False,
        }
        chat_filter.update(_created_at_range(date_from, date_to))
        chats = (
            CompanyChat.objects.filter(**chat_filter)
            .exclude(sender_id=self.bot_profile_id)
            .order_by("created_at")
        )

        self.stdout.write(
            f"  Scope: session_type={session_types or 'ANY'}, "
            f"session={session_ids or 'ANY'}, stages={stages}, "
            f"sessions matched={len(session_language)}, chats matched={chats.count()}"
        )
        logger.info(
            "[regen] route=%s scoped sessions=%d chats_matched=%d stages=%s",
            route, len(session_language), chats.count(), stages,
        )

        voice_cache = {}

        def get_voice(lang):
            if lang not in voice_cache:
                voice_cache[lang] = Voice.objects.filter(
                    company_bot=company_bot, type=VoiceType.Transliterate, language=lang
                ).first()
            return voice_cache[lang]

        # =========================== STEP 1: re-transliterate =============== #
        affected_sessions = set()
        t_success = t_failed = t_skipped = 0

        if skip_transliterate:
            affected_sessions = {c.session for c in chats.only("session")}
            self.stdout.write("  Step 1 skipped (--skip-transliterate).")
        else:
            for chat in chats.iterator():
                lang = session_language.get(chat.session)
                if not lang:
                    t_skipped += 1
                    logger.warning(
                        "[regen] step1 chat_id=%s session=%s skipped: no language on ChatSession",
                        chat.id, chat.session,
                    )
                    continue
                voice_provider = get_voice(lang)
                if not voice_provider:
                    self.stdout.write(self.style.WARNING(
                        f"  No Transliterate Voice for language='{lang}', skipping chat {chat.id}"
                    ))
                    t_failed += 1
                    logger.error(
                        "[regen] step1 chat_id=%s session=%s lang=%s route=%s FAILED: "
                        "no Transliterate Voice for this language on the route bot",
                        chat.id, chat.session, lang, route,
                    )
                    continue

                if dry_run:
                    affected_sessions.add(chat.session)
                    t_success += 1
                    continue

                response = transliterate_text(
                    source_language=lang,
                    target_language="en",
                    message_body=chat.message,
                    is_sentence=True,
                    voice_provider=voice_provider,
                )
                output = get_transliteration_output(response)
                logger.info(
                    "[regen] step1 chat_id=%s session=%s lang=%s stage=%s source=%r old=%r new=%r",
                    chat.id, chat.session, lang, chat.stage, chat.message, chat.translated_message, output,
                )
                if output:
                    chat.translated_message = output
                    chat.save(update_fields=["translated_message"])
                    affected_sessions.add(chat.session)
                    t_success += 1
                else:
                    self.stdout.write(self.style.ERROR(f"  Transliteration failed for chat {chat.id}: {response}"))
                    t_failed += 1
                    logger.error(
                        "[regen] step1 chat_id=%s session=%s lang=%s FAILED: "
                        "empty transliteration output, raw_response=%r",
                        chat.id, chat.session, lang, response,
                    )

            self.stdout.write(
                f"  Step 1 (re-transliterate): success={t_success}, failed={t_failed}, skipped={t_skipped}"
            )
            logger.info(
                "[regen] step1 route=%s done success=%d failed=%d skipped=%d affected_sessions=%d",
                route, t_success, t_failed, t_skipped, len(affected_sessions),
            )

        # =========================== STEP 2: delete + regenerate ============= #
        if skip_report:
            self.stdout.write("  Step 2 skipped (--skip-report).")
            return len(affected_sessions), 0, 0

        r_success = r_failed = 0
        for session in sorted(affected_sessions):
            ok = self._regenerate_session(session, dry_run)
            if ok:
                r_success += 1
            else:
                r_failed += 1

        return len(affected_sessions), r_success, r_failed

    # ------------------------------------------------------------------ #
    def _resolve_flow(self, chat_session):
        if self.flow_override:
            return self.flow_override
        st = chat_session.session_type
        return SESSION_TYPE_TO_FLOW.get(st, st)

    def _flow_row(self, flow):
        """Active Flow row with a story_bot for `flow`, needed only for --report-version 2."""
        if flow not in self._flow_row_cache:
            self._flow_row_cache[flow] = Flow.objects.filter(
                flow_route=flow, active=True, story_bot__isnull=False
            ).select_related("story_bot").first()
        return self._flow_row_cache[flow]

    def _story_bot_can_transliterate(self, flow, language, flow_row):
        """True when the story bot for `flow` has a Transliterate Voice for `language`.

        save_story() builds the English Story.other_params by transliterating the
        LLM output via a Voice on the story bot; with no Voice it silently keeps
        the original script and dashboards reading other_params stop matching.
        """
        if language == "en":
            return True
        key = (self.entry_label, flow, language)
        if key not in self._story_voice_cache:
            try:
                if self.entry_label == "v2":
                    story_bot = flow_row.story_bot
                else:
                    story_bot, _ = get_story_company_bot(profile=None, flow=flow)
                self._story_voice_cache[key] = Voice.objects.filter(
                    company_bot=story_bot, type=VoiceType.Transliterate, language=language
                ).exists()
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.WARNING(f"  Could not resolve story bot for flow='{flow}': {exc}"))
                logger.error("[regen] could not resolve story bot for flow=%s: %s", flow, exc, exc_info=True)
                self._story_voice_cache[key] = False
        return self._story_voice_cache[key]

    def _regenerate_session(self, session, dry_run):
        """Guard, then delete + regenerate the report for one session.
        Returns True on success, False on failure/skip."""
        chat_session = ChatSession.objects.filter(session=session).first()
        if not chat_session:
            self.stdout.write(self.style.WARNING(f"  ChatSession '{session}' missing, skip."))
            logger.error("[regen] step2 session=%s FAILED: ChatSession row missing", session)
            return False

        profile_id = chat_session.profile_id
        language = chat_session.language or "en"
        flow = self._resolve_flow(chat_session)
        flow_row = self._flow_row(flow) if self.entry_label == "v2" else None

        logger.info(
            "[regen] step2 session=%s profile_id=%s flow=%s language=%s entrypoint=%s",
            session, profile_id, flow, language, self.entry_label,
        )

        # ---- Guards run BEFORE delete, so a session that can't be safely
        # regenerated is skipped untouched -- nothing is deleted. ------------
        if self.entry_label == "v2" and not flow_row:
            self.stdout.write(self.style.ERROR(
                f"  Skipping session={session}: no active Flow row with a story_bot for flow='{flow}'."
            ))
            logger.error("[regen] step2 session=%s flow=%s SKIPPED: no active Flow row with story_bot", session, flow)
            return False

        if self.entry_label == "v2" and not profile_id:
            self.stdout.write(self.style.ERROR(
                f"  Skipping session={session}: v2 regeneration needs a profile, but profile_id is empty."
            ))
            logger.error("[regen] step2 session=%s flow=%s SKIPPED: v2 requires profile_id", session, flow)
            return False

        if not self._story_bot_can_transliterate(flow, language, flow_row):
            self.stdout.write(self.style.ERROR(
                f"  Skipping session={session}: no Transliterate Voice for language='{language}' "
                f"on the story bot of flow='{flow}'."
            ))
            logger.error(
                "[regen] step2 session=%s flow=%s language=%s SKIPPED: no Transliterate Voice on story bot",
                session, flow, language,
            )
            return False

        if dry_run:
            self.stdout.write(
                f"  [dry-run] would delete Story/StoryTranslation and regenerate "
                f"session={session} flow={flow} language={language} entrypoint={self.entry_label}"
            )
            return True

        # ---- Delete + regenerate, atomically. A raised exception rolls back
        # the delete too, no retry; a returned error_msg does NOT roll back the
        # delete (Story is already gone), so on error_msg we retry entry_fn only,
        # up to MAX_REPORT_ATTEMPTS times, without re-deleting.
        try:
            with transaction.atomic():
                deleted_translations, _ = StoryTranslation.objects.filter(story__session=session).delete()
                deleted_stories, _ = Story.objects.filter(session=session).delete()
                logger.info(
                    "[regen] step2 session=%s deleted stories=%s story_translations=%s",
                    session, deleted_stories, deleted_translations,
                )

                for attempt in range(1, self.MAX_REPORT_ATTEMPTS + 1):
                    story_id, _content, error_msg, error_type = self.entry_fn(
                        profile_id=profile_id,
                        session=session,
                        access_token=None,
                        flow=flow,
                        language=language,
                    )
                    if not error_msg:
                        self.stdout.write(self.style.SUCCESS(
                            f"  Report regenerated session={session} story_id={story_id} "
                            f"({self.entry_label}, attempt {attempt})"
                        ))
                        logger.info(
                            "[regen] step2 session=%s regenerated story_id=%s flow=%s language=%s "
                            "entrypoint=%s attempt=%s",
                            session, story_id, flow, language, self.entry_label, attempt,
                        )
                        return True

                    logger.error(
                        "[regen] step2 session=%s profile_id=%s flow=%s language=%s entrypoint=%s "
                        "attempt=%s/%s FAILED: error_type=%s error_msg=%s",
                        session, profile_id, flow, language, self.entry_label,
                        attempt, self.MAX_REPORT_ATTEMPTS, error_type, error_msg,
                    )

                self.stdout.write(self.style.ERROR(
                    f"  Report failed session={session} ({self.entry_label}) after "
                    f"{self.MAX_REPORT_ATTEMPTS} attempts: {error_msg} ({error_type}). "
                    f"Story/StoryTranslation already deleted, not restored."
                ))
                return False
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f"  Exception session={session}: {exc}. Delete rolled back, original Story preserved."
            ))
            logger.error(
                "[regen] step2 session=%s profile_id=%s flow=%s language=%s entrypoint=%s "
                "UNHANDLED EXCEPTION (delete rolled back): %s",
                session, profile_id, flow, language, self.entry_label, exc, exc_info=True,
            )
            return False

    # ------------------------------------------------------------------ #
    def _summary(self, affected, r_success, r_failed, dry_run):
        logger.info(
            "[regen] DONE dry_run=%s affected_sessions=%d reports_ok=%d reports_failed=%d",
            dry_run, affected, r_success, r_failed,
        )
        self.stdout.write("\n" + "=" * 50)
        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(f"{prefix}Affected sessions: {affected}"))
        self.stdout.write(self.style.SUCCESS(f"{prefix}Reports regenerated: {r_success}"))
        if r_failed:
            self.stdout.write(self.style.ERROR(f"{prefix}Reports failed: {r_failed}"))
        self.stdout.write("=" * 50)

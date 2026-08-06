"""
Re-transliterate stored chat entries for one or more state-machine stages and
regenerate the affected reports from scratch.

Background
----------
Some state machines (e.g. INTRODUCTION, ORGANIZATION) were earlier configured
with text_conversion_type = TRANSLATE. Their user messages were therefore stored
translated (wrong) in ``CompanyChat.translated_message``. The config has since
been fixed to TRANSLITERATE, but the already-stored chats — and every report
built from them — still contain the translated text.

This command fixes historic data in two steps, per affected session:

  1. Re-transliterate the stored user chats for the given stage(s) so
     ``CompanyChat.translated_message`` holds the transliterated (not translated)
     text — exactly like chatbot/scripts/retransliterate_failed_chats.py does.
  2. Delete the session's existing ``Story`` (and, via cascade, its
     ``StoryTranslation`` rows), then regenerate the report from the freshly
     transliterated chats via the *same* entrypoint the session's own
     end-story endpoint uses:
       * ``/api/end-story/``    -> ``create_story_object`` (v1, default)
       * ``/api/end-story/v2/`` -> ``generate_story``      (v2, --version 2)
     The path is auto-detected per session from the ``Flow`` table unless
     ``--version`` forces one.

Usage
-----
    # Chaupal bot, revert INTRODUCTION + ORGANIZATION for a time window
    python manage.py regenerate_transliterated_reports \
        --timestamp-from "2026-06-01 00:00" --timestamp-to "2026-06-30 23:59" \
        --session-type shikshalokam_chaupal \
        --statemachine INTRODUCTION,ORGANIZATION \
        --route /shikshalokam_chaupal

    # Preview only — count what would change, no writes / no delete / no API calls
    python manage.py regenerate_transliterated_reports \
        --session-type shikshalokam_chaupal --statemachine INTRODUCTION --dry-run

    # Several bots/flows in ONE run — comma-separated routes, flow auto-resolved
    # per session (do NOT pass --flow when mixing flows):
    python manage.py regenerate_transliterated_reports \
        --route "/shikshalokam_chaupal,/guided_guest" \
        --statemachine INTRODUCTION,ORGANIZATION \
        --timestamp-from "2026-07-01" --timestamp-to "2026-07-31 23:59"

    # Force v2 (/end-story/v2) for every session in this run
    python manage.py regenerate_transliterated_reports \
        --route /shikshalokam_chaupal --statemachine INTRODUCTION --version 2

    # Re-run only the report regeneration (chats already fixed)
    python manage.py regenerate_transliterated_reports \
        --session-type shikshalokam_chaupal --statemachine INTRODUCTION \
        --skip-transliterate

Scoping is by --route + --statemachine + --timestamp + --session-type (the
primary mechanism). --session is an optional convenience to target exact ids.

Arguments
---------
    --timestamp-from / --timestamp-to
        Filter CompanyChat rows by created_at. Accept 'YYYY-MM-DD' (whole day) or
        'YYYY-MM-DD HH:MM[:SS]' (exact time). Both optional. Interpreted in the
        server timezone.
    --session-type
        Optional ChatSession.session_type filter. Comma-separated for several
        types (e.g. 'shikshalokam_chaupal,guest-mi-story').
    --statemachine
        One or more CompanyStateMachine names (== CompanyChat.stage), comma
        separated (e.g. 'INTRODUCTION,ORGANIZATION'). Required.
    --route
        One or more CompanyBot route(s), comma-separated, processed in one run
        (e.g. '/shikshalokam_chaupal,/guided_guest'). Each route is scoped and
        run independently. Default '/shikshalokam_chaupal'.
    --flow
        Optional SessionFlowName override applied to ALL routes. Leave unset to
        auto-resolve each session's own flow from Story.other_params['flow']
        (required when processing multiple routes/flows at once).
    --version
        Which report-generation path to use. Unset (default) auto-resolves per
        session from the Flow table — an active Flow row with a story_bot means
        the session is served by /end-story/v2 and is regenerated with
        generate_story; anything else keeps create_story_object. '1' or '2'
        force one path for every session in the run (testing/recovery).
    --bot-profile-id
        Profile id used as the bot sender (its messages are excluded from
        re-transliteration). Default 1.
    --skip-transliterate   Skip step 1 (only delete + regenerate reports).
    --skip-report          Skip step 2 (only re-transliterate chats).
    --limit                Process at most N sessions (0 = no limit).
    --dry-run              Report counts only; no DB writes, no delete, no report calls.

Report language
---------------
The report is always regenerated in the session's own language -- the same value
``/api/end-story/`` passes. ``Story.other_params`` is nevertheless stored in
English: ``save_story()`` transliterates the LLM output back to English using a
Transliterate ``Voice`` on the *story* bot. If that Voice is missing the app
silently keeps the original script, ``other_params`` ends up in Devanagari, and
dashboards reading ``other_params->>'location'`` stop matching the story. This
command therefore refuses to delete + regenerate such sessions instead of
leaving them with no Story at all.

Delete + regenerate safety
---------------------------
Step 2 deletes the session's ``Story``/``StoryTranslation`` rows and calls the
entrypoint inside a single ``transaction.atomic()`` block:
  * The guard above (Transliterate Voice on the story bot, valid Flow row for
    v2, a profile_id for v2) runs BEFORE the delete, so a session that can't be
    safely regenerated is skipped untouched — nothing is deleted.
  * If the entrypoint call *raises* (network/LLM/API exception), the whole
    block — including the delete — rolls back, so the original Story survives.
  * If the entrypoint call *returns* an error_msg without raising (e.g. LLM
    output failed validation), the delete has already happened and is NOT
    rolled back — the session is left with no Story row and is logged/counted
    as failed. Re-run the command for that session once the underlying issue
    is fixed.
Note: deleting Story cascades (on_delete=CASCADE) to StoryTranslation as well
as StoryMedia and StoryTag. StoryMedia's file field is not cleaned up by this
cascade — any previously stored PDF/media blob in storage is left orphaned.
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

# Session-type -> report flow fallback. shikshaChaupal reports are generated
# with the GuestDiscussion flow (see chatbot/utils/story_utils/story_utils.py).
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
    """created_at filter honouring time-of-day; date-only bounds cover the full day."""
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
        "delete and regenerate the affected reports via create_story_object "
        "(/end-story) or generate_story (/end-story/v2)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--timestamp-from", type=str, default=None)
        parser.add_argument("--timestamp-to", type=str, default=None)
        parser.add_argument(
            "--session-type",
            type=str,
            default=None,
            help="Optional ChatSession.session_type filter. Comma-separated for "
                 "several types, e.g. 'shikshalokam_chaupal,guest-mi-story'.",
        )
        parser.add_argument(
            "--session",
            type=str,
            default=None,
            help="Target one or more exact session id(s), comma separated. "
                 "When set, scoping is by these sessions (timestamp / session-type "
                 "act only as extra optional filters).",
        )
        parser.add_argument(
            "--statemachine",
            type=str,
            required=True,
            help="Comma-separated CompanyStateMachine name(s), e.g. 'INTRODUCTION,ORGANIZATION'.",
        )
        parser.add_argument(
            "--route",
            type=str,
            default="/shikshalokam_chaupal",
            help="One or more CompanyBot route(s), comma-separated, to process in a "
                 "single run, e.g. '/shikshalokam_chaupal,/guided_guest'. Each route "
                 "is scoped and processed independently; the flow is auto-resolved "
                 "per session unless --flow is given.",
        )
        parser.add_argument(
            "--flow",
            type=str,
            default=None,
            help="Optional SessionFlowName override for report regeneration applied to "
                 "ALL routes. Leave unset to auto-resolve each session's own flow "
                 "(required when processing multiple routes/flows at once).",
        )
        parser.add_argument(
            "--version",
            type=int,
            choices=[1, 2],
            default=None,
            help="Report-generation path. Unset (default) auto-resolves per session "
                 "from the Flow table: an active Flow row with a story_bot means the "
                 "session is served by /end-story/v2 and is regenerated with "
                 "generate_story; anything else uses create_story_object. "
                 "1 / 2 force one path for every session in the run.",
        )
        parser.add_argument("--bot-profile-id", type=int, default=1)
        parser.add_argument("--skip-transliterate", action="store_true")
        parser.add_argument("--skip-report", action="store_true")
        parser.add_argument("--limit", type=int, default=0)
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
        flow_override = opts["flow"]
        bot_profile_id = opts["bot_profile_id"]
        self.bot_profile_id = bot_profile_id
        self.version = opts["version"]
        self._story_voice_cache = {}
        self._entrypoint_cache = {}
        skip_transliterate = opts["skip_transliterate"]
        skip_report = opts["skip_report"]
        limit = opts["limit"]
        dry_run = opts["dry_run"]

        logger.info(
            "[regen] START routes=%s stages=%s from=%s to=%s session_types=%s sessions=%s "
            "skip_transliterate=%s skip_report=%s limit=%s dry_run=%s bot_profile_id=%s "
            "version=%s",
            routes, stages, opts["timestamp_from"], opts["timestamp_to"],
            session_types or "ANY", session_ids or "ANY",
            skip_transliterate, skip_report, limit, dry_run, bot_profile_id,
            self.version or "auto",
        )

        # --- process each route independently, then aggregate ---------------
        g_affected = g_r_success = g_r_failed = 0
        for route in routes:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n### route {route}"))
            affected, r_success, r_failed = self._process_route(
                route=route, stages=stages, date_from=date_from, date_to=date_to,
                session_types=session_types, session_ids=session_ids,
                flow_override=flow_override,
                skip_transliterate=skip_transliterate, skip_report=skip_report,
                limit=limit, dry_run=dry_run,
            )
            g_affected += affected
            g_r_success += r_success
            g_r_failed += r_failed

        self._summary(g_affected, g_r_success, g_r_failed, dry_run)

    # ------------------------------------------------------------------ #
    def _process_route(self, route, stages, date_from, date_to, session_types,
                       session_ids, flow_override, skip_transliterate, skip_report,
                       limit, dry_run):
        """Scope + Step 1 + Step 2 for a single bot route. Returns
        (affected_sessions, reports_success, reports_failed)."""
        logger.info("[regen] route=%s scoping sessions", route)
        company_bot = CompanyBot.objects.filter(route=route).first()
        if not company_bot:
            self.stdout.write(self.style.ERROR(f"CompanyBot route='{route}' not found, skipping."))
            logger.error("[regen] route=%s CompanyBot not found, skipping route", route)
            return 0, 0, 0

        # --- scope sessions --------------------------------------------------
        if session_ids:
            # Explicit session targeting — do not restrict by bot; the route bot
            # is still used only to locate the transliteration Voice provider.
            sessions_qs = ChatSession.objects.filter(session__in=session_ids).exclude(language="en")
        else:
            sessions_qs = ChatSession.objects.filter(company_bot=company_bot).exclude(language="en")
        if session_types:
            sessions_qs = sessions_qs.filter(session_type__in=session_types)
        session_language = {s.session: s.language for s in sessions_qs}
        if not session_language:
            self.stdout.write(self.style.WARNING("  No matching non-English sessions for this route."))
            logger.warning(
                "[regen] route=%s no non-English sessions (session_types=%s sessions=%s)",
                route, session_types or "ANY", session_ids or "ANY",
            )
            return 0, 0, 0

        # --- select candidate chats -----------------------------------------
        chat_filter = {
            "session__in": list(session_language.keys()),
            "stage__in": stages,
            "translated_message__isnull": False,
        }
        chat_filter.update(_created_at_range(date_from, date_to))
        chats = (
            CompanyChat.objects.filter(**chat_filter)
            .exclude(sender_id=self.bot_profile_id)   # user messages only; skip bot (Profile id=1)
            .order_by("created_at")
        )

        self.stdout.write(
            f"  Scope: session_type={session_types or 'ANY'}, "
            f"session={session_ids or 'ANY'}, stages={stages}, "
            f"chats matched={chats.count()}"
        )
        logger.info(
            "[regen] route=%s scoped sessions=%d chats_matched=%d stages=%s",
            route, len(session_language), chats.count(), stages,
        )

        # --- cache transliterate voice providers per language ----------------
        voice_cache = {}

        def get_voice(lang):
            if lang not in voice_cache:
                voice_cache[lang] = Voice.objects.filter(
                    company_bot=company_bot, type=VoiceType.Transliterate, language=lang
                ).first()
            return voice_cache[lang]

        # =========================== STEP 1 ================================== #
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
                    self.stdout.write(
                        self.style.WARNING(
                            f"  No Transliterate Voice for language='{lang}', "
                            f"skipping chat {chat.id}"
                        )
                    )
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
                    "[regen] step1 chat_id=%s session=%s lang=%s stage=%s "
                    "source=%r old=%r new=%r",
                    chat.id, chat.session, lang, chat.stage,
                    chat.message, chat.translated_message, output,
                )
                if output:
                    chat.translated_message = output
                    chat.save(update_fields=["translated_message"])
                    affected_sessions.add(chat.session)
                    t_success += 1
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  Transliteration failed for chat {chat.id}: {response}"
                        )
                    )
                    t_failed += 1
                    logger.error(
                        "[regen] step1 chat_id=%s session=%s lang=%s FAILED: "
                        "empty transliteration output, raw_response=%r",
                        chat.id, chat.session, lang, response,
                    )

            self.stdout.write(
                f"  Step 1 (re-transliterate): success={t_success}, "
                f"failed={t_failed}, skipped={t_skipped}"
            )
            logger.info(
                "[regen] step1 route=%s done success=%d failed=%d skipped=%d "
                "affected_sessions=%d",
                route, t_success, t_failed, t_skipped, len(affected_sessions),
            )

        # =========================== STEP 2 ================================== #
        if skip_report:
            self.stdout.write("  Step 2 skipped (--skip-report).")
            return len(affected_sessions), 0, 0

        ordered_sessions = sorted(affected_sessions)
        if limit and limit > 0:
            ordered_sessions = ordered_sessions[:limit]

        r_success = r_failed = 0
        for session in ordered_sessions:
            ok = self._regenerate_session(session, flow_override, get_voice, dry_run)
            if ok:
                r_success += 1
            else:
                r_failed += 1

        return len(affected_sessions), r_success, r_failed

    # ------------------------------------------------------------------ #
    def _regenerate_session(self, session, flow_override, get_voice, dry_run):
        """Guard, then delete + regenerate the report for one session.
        Returns True on success, False on failure/skip."""
        chat_session = ChatSession.objects.filter(session=session).first()
        if not chat_session:
            self.stdout.write(self.style.WARNING(f"  ChatSession '{session}' missing, skip."))
            logger.error("[regen] step2 session=%s FAILED: ChatSession row missing", session)
            return False

        profile_id = chat_session.profile_id
        flow = flow_override or self._resolve_flow(session, chat_session)
        language = self._resolve_language(chat_session)
        entry_label, entry_fn, entry_flow_obj = self._resolve_entrypoint(flow)
        logger.info(
            "[regen] step2 session=%s profile_id=%s flow=%s language=%s "
            "session_type=%s entrypoint=%s",
            session, profile_id, flow, language, chat_session.session_type, entry_label,
        )

        # ---- Guards: run BEFORE delete, so a session that can't be safely
        # regenerated is skipped untouched -- nothing is deleted. ---------
        if entry_label == "v2" and not entry_flow_obj:
            self.stdout.write(self.style.ERROR(
                f"  Skipping session={session}: --version 2 requested but no "
                f"active Flow row with a story_bot exists for flow='{flow}'."
            ))
            logger.error(
                "[regen] step2 session=%s flow=%s SKIPPED: no active Flow row with "
                "a story_bot; generate_story would raise NotFound",
                session, flow,
            )
            return False

        if entry_label == "v2" and not profile_id:
            # generate_story does Profile.objects...get(id=profile_id); the v1
            # path tolerated a missing profile, this one raises.
            self.stdout.write(self.style.ERROR(
                f"  Skipping session={session}: v2 regeneration needs a profile, "
                f"but ChatSession.profile_id is empty."
            ))
            logger.error(
                "[regen] step2 session=%s flow=%s SKIPPED: v2 entrypoint requires "
                "a profile_id, ChatSession.profile_id is %r",
                session, flow, profile_id,
            )
            return False

        if not self._story_bot_can_transliterate(flow, language):
            self.stdout.write(self.style.ERROR(
                f"  Skipping session={session}: no Transliterate Voice for "
                f"language='{language}' on the story bot of flow='{flow}'. "
                f"Regenerating would store '{language}' text in the English "
                f"Story.other_params and drop the story from the dashboard."
            ))
            logger.error(
                "[regen] step2 session=%s flow=%s language=%s SKIPPED: no Transliterate "
                "Voice on the story bot; regenerating would corrupt Story.other_params",
                session, flow, language,
            )
            return False

        if dry_run:
            self.stdout.write(
                f"  [dry-run] would delete Story/StoryTranslation and regenerate "
                f"session={session} flow={flow} language={language} entrypoint={entry_label}"
            )
            return True

        # ---- Delete + regenerate, atomically. A raised exception rolls back
        # the delete too; a returned error_msg does NOT (see module docstring
        # "Delete + regenerate safety"). ------------------------------------
        try:
            with transaction.atomic():
                StoryTranslation.objects.filter(story__session=session).delete()
                Story.objects.filter(session=session).delete()

                # Same signature and return contract for both entrypoints:
                # (story_id, content, error_msg, error_type).
                story_id, _content, error_msg, error_type = entry_fn(
                    profile_id=profile_id,
                    session=session,
                    access_token=None,
                    flow=flow,
                    language=language,
                )
                if error_msg:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  Report failed session={session} ({entry_label}): "
                            f"{error_msg} ({error_type}). Story/StoryTranslation were "
                            f"already deleted and are NOT restored."
                        )
                    )
                    logger.error(
                        "[regen] step2 session=%s profile_id=%s flow=%s language=%s "
                        "entrypoint=%s %s FAILED after delete (no rollback): "
                        "error_type=%s error_msg=%s",
                        session, profile_id, flow, language, entry_label,
                        entry_fn.__name__, error_type, error_msg,
                    )
                    return False

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Report regenerated session={session} story_id={story_id} "
                        f"({entry_label})"
                    )
                )
                logger.info(
                    "[regen] step2 session=%s regenerated story_id=%s flow=%s "
                    "language=%s entrypoint=%s",
                    session, story_id, flow, language, entry_label,
                )
                return True
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f"  Exception session={session}: {exc}. Delete rolled back, "
                f"original Story preserved."
            ))
            logger.error(
                "[regen] step2 session=%s profile_id=%s flow=%s language=%s "
                "entrypoint=%s UNHANDLED EXCEPTION (delete rolled back): %s",
                session, profile_id, flow, language, entry_label, exc, exc_info=True,
            )
            return False

    # ------------------------------------------------------------------ #
    def _resolve_flow(self, session, chat_session):
        """Reuse the flow the report was originally generated with."""
        try:
            story = Story.objects.filter(session=session).first()
            if story and isinstance(story.other_params, dict):
                flow = story.other_params.get("flow")
                if flow:
                    return flow
        except Exception:
            logger.error(
                "[regen] session=%s could not read flow from Story.other_params, "
                "falling back to session_type",
                session, exc_info=True,
            )
        st = chat_session.session_type
        return SESSION_TYPE_TO_FLOW.get(st, st)

    def _resolve_language(self, chat_session):
        """The report is regenerated in the conversation language -- the same value
        /api/end-story/ passes. Story.language is always 'en' (save_story hard-codes
        it), so it is not a useful fallback and is not consulted."""
        return (chat_session.language if chat_session else None) or "en"

    def _resolve_entrypoint(self, flow):
        """Pick the report-generation path for `flow`, mirroring the live endpoints.

        /end-story    -> create_story_object, story bot from get_story_company_bot()
                         (hard-coded routes per SessionFlowName).
        /end-story-v2 -> generate_story, story bot from Flow.story_bot.

        self.version: None -> auto (a flow with an active Flow row + story_bot is
        v2, else v1); 1 -> force v1; 2 -> force v2. Returns (label, callable,
        flow_obj) where flow_obj is None for v1. Cached per flow.
        """
        key = str(flow)
        if key not in self._entrypoint_cache:
            flow_obj = None
            if self.version in (None, 2):
                flow_obj = Flow.objects.filter(
                    flow_route=key, active=True, story_bot__isnull=False
                ).select_related("story_bot").first()

            if self.version == 1:
                resolved = ("v1", create_story_object, None)
            elif self.version == 2:
                # Forced v2: still requires a usable Flow row, otherwise
                # generate_story raises NotFound on every session.
                resolved = ("v2", generate_story, flow_obj)
            elif flow_obj:
                resolved = ("v2", generate_story, flow_obj)
            else:
                resolved = ("v1", create_story_object, None)

            self._entrypoint_cache[key] = resolved
            logger.info(
                "[regen] entrypoint for flow=%s resolved to %s (version=%s, "
                "flow_row=%s story_bot=%s)",
                key, resolved[0], self.version or "auto",
                bool(flow_obj), getattr(flow_obj.story_bot, "route", None) if flow_obj else None,
            )
        return self._entrypoint_cache[key]

    def _story_bot_can_transliterate(self, flow, language):
        """True when the story bot for `flow` has a Transliterate Voice for `language`.

        save_generic_story()/save_story() build the *English* Story.other_params by
        transliterating the LLM output using a Voice on the **story bot**; with no
        Voice they silently return the original script. The story bot must therefore
        be resolved exactly the way the chosen entrypoint resolves it -- v1 via
        get_story_company_bot(), v2 via Flow.story_bot -- otherwise this guard checks
        a bot that is never used and can pass while the real bot has no Voice row.
        """
        if language == "en":
            return True
        key = (str(flow), language)
        if key not in self._story_voice_cache:
            label, _entry, flow_obj = self._resolve_entrypoint(flow)
            try:
                if label == "v2":
                    if not flow_obj:
                        raise CommandError(
                            f"no active Flow row with a story_bot for flow_route='{flow}'"
                        )
                    story_bot = flow_obj.story_bot
                else:
                    story_bot, _validate_bot = get_story_company_bot(profile=None, flow=flow)
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.WARNING(
                    f"  Could not resolve story bot for flow='{flow}' ({label}): {exc}"
                ))
                logger.error(
                    "[regen] could not resolve story bot for flow=%s entrypoint=%s: %s",
                    flow, label, exc, exc_info=True,
                )
                self._story_voice_cache[key] = False
            else:
                self._story_voice_cache[key] = Voice.objects.filter(
                    company_bot=story_bot, type=VoiceType.Transliterate, language=language
                ).exists()
                logger.info(
                    "[regen] story bot for flow=%s (%s) is route=%s; Transliterate Voice "
                    "for language=%s present=%s",
                    flow, label, getattr(story_bot, "route", None), language,
                    self._story_voice_cache[key],
                )
        return self._story_voice_cache[key]

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

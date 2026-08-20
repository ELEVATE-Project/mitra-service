import csv
import io
from collections import Counter

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView

from chatbot.constants import api_responses
from chatbot.constants.india_states import get_canonical_state

CSV_REQUIRED_COLS = {"id"}   # only "id" column is mandatory

ERROR_REASON_COL = "error_reason"

MAPPING_REQUIRED_FIELDS = {"state", "district", "leader_category"}

def _get_valid_roles():
    # Roles come from the Role master table. ProfileType (USER/MODERATOR) describes admin
    # access levels, not reporter roles, so validating against it rejected every real
    # value a correction CSV could carry.
    from chatbot.models.story_models import Role
    return {n.strip().lower() for n in Role.objects.values_list("name", flat=True) if n}


def _get_valid_leader_categories():
    # Read from the LeaderCategory master table rather than scraping distinct strings out
    # of Story.other_params, which only ever knew about values already in use.
    from chatbot.models.story_models import LeaderCategory
    return {n.strip().lower() for n in LeaderCategory.objects.values_list("name", flat=True) if n}



def _extract_fields(row: dict) -> dict:
    return {
        "id":              (row.get("id") or "").strip(),
        "session":         (row.get("session") or "").strip(),
        "state":           (row.get("state") or "").strip(),
        "district":        (row.get("district") or "").strip(),
        "block":           (row.get("block") or "").strip(),
        "location":        (row.get("location") or "").strip(),
        "role":            (row.get("role") or "").strip(),
        "leader_category": (row.get("leader_category") or "").strip(),
        "theme_name":      (row.get("theme_name") or "").strip(),
        # Absent, empty and whitespace-only all mean "no action given", which defaults to
        # update. Without the trailing fallback a cell of "   " would strip to "" and be
        # rejected as an unsupported action.
        "action":          ((row.get("action") or "").strip().lower() or "update"),
    }



def _validate_row(fields: dict, roles: set, leader_categories: set) -> list:
    errors = []

    state_val = fields["state"]
    role_val  = fields["role"]
    lc_val    = fields["leader_category"]

    if state_val:
        if get_canonical_state(state_val) is None:
            errors.append(
                api_responses.CSV_ROW_INVALID_STATE_TEMPLATE.format(state=state_val)
            )

    if role_val and roles and role_val.lower() not in roles:
        errors.append(api_responses.CSV_ROW_UNKNOWN_ROLE_TEMPLATE.format(role=role_val))

    if lc_val and leader_categories and lc_val.lower() not in leader_categories:
        errors.append(
            api_responses.CSV_ROW_UNKNOWN_LEADER_CATEGORY_TEMPLATE.format(
                leader_category=lc_val
            )
        )

    return errors


def _apply_to_story(story, fields: dict) -> bool:
    """Apply only the values that differ. Return True if anything changed."""
    changed = False

    if fields["state"]:
        canonical = get_canonical_state(fields["state"])
        new_state = canonical if canonical else fields["state"]
        if story.state != new_state:
            story.state = new_state
            changed = True
    if fields["district"] and story.district != fields["district"]:
        story.district = fields["district"]
        changed = True
    if fields["block"] and story.block != fields["block"]:
        story.block = fields["block"]
        changed = True
    if fields["location"] and story.location != fields["location"]:
        story.location = fields["location"]
        changed = True

    op = story.other_params or {}
    if fields["role"] and op.get("role") != fields["role"]:
        op["role"] = fields["role"]
        changed = True
    if fields["leader_category"] and op.get("leader_category") != fields["leader_category"]:
        op["leader_category"] = fields["leader_category"]
        changed = True

    # Also resolve onto the model's foreign keys, which is what the dashboard reads.
    # The other_params copies above are kept as-is: _update_mapping_stage() derives the
    # story stage from op['leader_category'], so dropping them would change that result.
    from chatbot.models.story_models import LeaderCategory, Role

    if fields["role"]:
        role_obj = Role.objects.filter(name__iexact=fields["role"]).first()
        if role_obj and story.role_id != role_obj.id:
            story.role = role_obj
            changed = True
    if fields["leader_category"]:
        lc_obj = LeaderCategory.objects.filter(name__iexact=fields["leader_category"]).first()
        if lc_obj and story.leader_category_id != lc_obj.id:
            story.leader_category = lc_obj
            changed = True

    if fields["theme_name"] and op.get("theme_name") != fields["theme_name"]:
        op["theme_name"] = fields["theme_name"]
        changed = True
    story.other_params = op

    if changed:
        _update_mapping_stage(story)

    return changed


def _update_mapping_stage(story):
    from chatbot.models.enums import StoryStatusChoices
    op = story.other_params or {}

    def _has(f):
        if f in ("state", "district", "block", "location"):
            return bool(getattr(story, f, None))
        return bool(op.get(f))

    fully_mapped = all(_has(f) for f in MAPPING_REQUIRED_FIELDS)
    story.stage = StoryStatusChoices.COMPLETED if fully_mapped else StoryStatusChoices.PENDING


def _neutralise_formula(value):
    """
    Stop a spreadsheet from evaluating uploaded text as a formula.

    The rejection file echoes back cells the uploader supplied, so a value such as
    =cmd|'/c calc'!A1 would execute when the file is opened in Excel or Sheets. Prefixing
    with an apostrophe makes the cell literal text; the apostrophe is not displayed.
    """
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _build_rejection_csv(rejected_rows: list, original_headers: list) -> str:
    headers = [h for h in original_headers if h != ERROR_REASON_COL]
    headers.append(ERROR_REASON_COL)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    # Headers come from the uploaded file too, so they need the same treatment. The
    # fieldnames stay unchanged so DictWriter can still map each row's keys.
    writer.writerow({h: _neutralise_formula(h) for h in headers})
    for item in rejected_rows:
        row = {k: _neutralise_formula(v) for k, v in dict(item["row"]).items()}
        row[ERROR_REASON_COL] = _neutralise_formula(item["error"])
        writer.writerow(row)
    return output.getvalue()


@method_decorator(staff_member_required, name="dispatch")
class CsvCorrectionView(TemplateView):
    """
    Admin screen for correcting report metadata in bulk from an uploaded CSV.
    GET renders the upload page; POST validates every row against the master data before
    committing anything, then returns a summary and, where rows failed, a rejection file
    carrying the reason for each. Requires the Story change permission, not merely staff
    access, because a single upload can rewrite every report in the database.
    """

    template_name = "admin/csv_correction/csv_correction.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["model_name"] = "Story"
        return context

    def post(self, request, *args, **kwargs):
        # staff_member_required only proves the user can reach the admin. Bulk-rewriting
        # every Story needs the change permission for the model itself, checked before
        # anything is parsed or saved.
        if not request.user.has_perm("chatbot.change_story"):
            return JsonResponse(
                {"success": False, "error": api_responses.CSV_NO_PERMISSION},
                status=403,
            )

        uploaded_file = request.FILES.get("csv_file")

        if not uploaded_file:
            return JsonResponse({"success": False, "error": api_responses.CSV_NO_FILE_UPLOADED}, status=400)
        if not uploaded_file.name.lower().endswith(".csv"):
            return JsonResponse(
                {"success": False, "error": api_responses.CSV_INVALID_FILE_FORMAT},
                status=400,
            )

        try:
            content = uploaded_file.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(content))
            headers = list(reader.fieldnames or [])
            rows = list(reader)
        except Exception as exc:
            return JsonResponse({"success": False, "error": api_responses.CSV_PARSE_FAILED_TEMPLATE.format(error=exc)}, status=400)

        original_headers = [h for h in headers if h != ERROR_REASON_COL]

        missing = CSV_REQUIRED_COLS - set(original_headers)
        if missing:
            return JsonResponse(
                {"success": False,
                 "error": api_responses.CSV_MISSING_ID_COLUMN},
                status=400,
            )

        if not rows:
            return JsonResponse({"success": False, "error": api_responses.CSV_EMPTY_FILE}, status=400)

        # `or ""` rather than a get() default: csv.DictReader maps every column a short
        # row does not reach to None, so the key exists with a None value and the default
        # never applies. Calling .strip() on that raised an unhandled AttributeError.
        # Matches how _extract_fields reads the same column.
        ids = [(r.get("id") or "").strip() for r in rows]
        dupes = [rid for rid, cnt in Counter(ids).items() if cnt > 1 and rid]
        if dupes:
            return JsonResponse(
                {"success": False,
                 "error": api_responses.CSV_DUPLICATE_IDS_TEMPLATE.format(
                     ids=', '.join(dupes[:10])
                 )},
                status=400,
            )

        roles             = _get_valid_roles()
        leader_categories = _get_valid_leader_categories()

        from chatbot.models.story_models import Story

        processed = successful = unchanged = 0
        rejected_rows = []

        for row in rows:
            fields = _extract_fields(row)

            if fields["action"] == "ignore":
                processed += 1
                continue
            if fields["action"] != "update":
                # A typo such as 'updtae' used to be skipped silently - not counted, not
                # rejected - so the upload reported success while the correction was
                # never applied.
                processed += 1
                rejected_rows.append(
                    {"row": row, "error": api_responses.CSV_ROW_INVALID_ACTION}
                )
                continue

            processed += 1

            raw_id = fields["id"]
            if not raw_id:
                rejected_rows.append({"row": row, "error": api_responses.CSV_ROW_ID_EMPTY})
                continue

            errors = _validate_row(fields, roles, leader_categories)
            if errors:
                rejected_rows.append({"row": row, "error": "; ".join(errors)})
                continue

            story = None
            try:
                story = Story.objects.get(pk=int(raw_id))
            except (ValueError, TypeError, Story.DoesNotExist):
                pass

            if story is None:
                session_val = fields["session"] or raw_id
                try:
                    story = Story.objects.get(session=session_val)
                except Story.DoesNotExist:
                    rejected_rows.append(
                        {"row": row, "error": api_responses.CSV_ROW_STORY_NOT_FOUND_TEMPLATE.format(story_id=raw_id)}
                    )
                    continue
                except Exception as exc:
                    rejected_rows.append({"row": row, "error": api_responses.CSV_ROW_DB_ERROR_TEMPLATE.format(error=exc)})
                    continue

            if not _apply_to_story(story, fields):
                unchanged += 1
                continue

            try:
                story.save()
                successful += 1
            except Exception as exc:
                rejected_rows.append({"row": row, "error": api_responses.CSV_ROW_SAVE_FAILED_TEMPLATE.format(error=exc)})

        rejection_csv_b64 = None
        if rejected_rows:
            import base64
            rej = _build_rejection_csv(rejected_rows, original_headers)
            rejection_csv_b64 = base64.b64encode(rej.encode("utf-8")).decode("ascii")

        return JsonResponse({
            "success": True,
            "stats": {
                "total_processed": processed,
                "successful_updates": successful,
                "unchanged_rows": unchanged,
                "rejected_rows": len(rejected_rows),
            },
            "rejection_csv": rejection_csv_b64,
            "rejection_count": len(rejected_rows),
        })

import csv
import io
from collections import Counter

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView

from chatbot.constants.india_states import get_canonical_state

CSV_REQUIRED_COLS = {"id"}   # only "id" column is mandatory

ERROR_REASON_COL = "error_reason"

MAPPING_REQUIRED_FIELDS = {"state", "district", "leader_category"}

def _get_valid_roles():
    from chatbot.models.enums import ProfileType
    return {c[0].lower() for c in ProfileType.choices}


def _get_valid_leader_categories():
    from chatbot.models.story_models import Story
    cats = set()
    for params in Story.objects.exclude(other_params__isnull=True).values_list("other_params", flat=True):
        if isinstance(params, dict):
            lc = params.get("leader_category")
            if lc and isinstance(lc, str):
                cats.add(lc.strip().lower())
    return cats



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
        "action":          (row.get("action") or "update").strip().lower(),
    }



def _validate_row(fields: dict, roles: set, leader_categories: set) -> list:
    errors = []

    state_val = fields["state"]
    role_val  = fields["role"]
    lc_val    = fields["leader_category"]

    if state_val:
        if get_canonical_state(state_val) is None:
            errors.append(
                f"Invalid State '{state_val}' — not in the 29 recognised states of India"
            )


    if role_val and roles and role_val.lower() not in roles:
        errors.append(f"Role '{role_val}' does not exist in master system access configurations")

    if lc_val and leader_categories and lc_val.lower() not in leader_categories:
        errors.append(
            f"Leader Category '{lc_val}' does not exist in master system access configurations"
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


def _build_rejection_csv(rejected_rows: list, original_headers: list) -> str:
    headers = [h for h in original_headers if h != ERROR_REASON_COL]
    headers.append(ERROR_REASON_COL)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for item in rejected_rows:
        row = dict(item["row"])
        row[ERROR_REASON_COL] = item["error"]
        writer.writerow(row)
    return output.getvalue()


@method_decorator(staff_member_required, name="dispatch")
class CsvCorrectionView(TemplateView):
    template_name = "admin/csv_correction/csv_correction.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["model_name"] = "Story"
        return context

    def post(self, request, *args, **kwargs):
        uploaded_file = request.FILES.get("csv_file")

        if not uploaded_file:
            return JsonResponse({"success": False, "error": "No file uploaded."}, status=400)
        if not uploaded_file.name.lower().endswith(".csv"):
            return JsonResponse(
                {"success": False, "error": "Invalid file format. Please upload a .csv file."},
                status=400,
            )

        try:
            content = uploaded_file.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(content))
            headers = list(reader.fieldnames or [])
            rows = list(reader)
        except Exception as exc:
            return JsonResponse({"success": False, "error": f"Could not parse CSV: {exc}"}, status=400)

        original_headers = [h for h in headers if h != ERROR_REASON_COL]

        missing = CSV_REQUIRED_COLS - set(original_headers)
        if missing:
            return JsonResponse(
                {"success": False,
                 "error": "Missing required column: 'id'. The CSV must have an 'id' column."},
                status=400,
            )

        if not rows:
            return JsonResponse({"success": False, "error": "CSV file is empty."}, status=400)

        ids = [r.get("id", "").strip() for r in rows]
        dupes = [rid for rid, cnt in Counter(ids).items() if cnt > 1 and rid]
        if dupes:
            return JsonResponse(
                {"success": False,
                 "error": f"Duplicate id values detected — upload rejected. "
                          f"Duplicates: {', '.join(dupes[:10])}"},
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
                continue

            processed += 1

            raw_id = fields["id"]
            if not raw_id:
                rejected_rows.append({"row": row, "error": "id is empty"})
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
                        {"row": row, "error": f"No Story found with id='{raw_id}'"}
                    )
                    continue
                except Exception as exc:
                    rejected_rows.append({"row": row, "error": f"DB error: {exc}"})
                    continue

            if not _apply_to_story(story, fields):
                unchanged += 1
                continue

            try:
                story.save()
                successful += 1
            except Exception as exc:
                rejected_rows.append({"row": row, "error": f"Save failed: {exc}"})

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

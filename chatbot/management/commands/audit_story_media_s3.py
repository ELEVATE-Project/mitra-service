"""
Audit StoryMedia rows against the objects actually present in the S3 bucket.

Read-only. This command never writes to the database and never mutates S3.

Why this exists
---------------
Story images are NOT uploaded through Django. The client:

  1. POSTs to `get_presigned_url` (chatbot/views/aws_views.py), which builds the
     object key as `{folder_structure}{storyId}/{epoch_ms}-{fileName}` and hands
     back a presigned PUT URL.
  2. PUTs the bytes straight to S3.
  3. POSTs to `/api/storymedia/` (StoryMediaListCreateView) with `file_url` to
     create the StoryMedia row.

Steps 2 and 3 are not atomic. When step 3 never lands - client dropped, request
timed out, tab closed - the object sits in S3 with no row pointing at it, and
the report renders without the photo. `pdf/story_images_page.py` builds the
image page from `StoryMedia.objects.filter(story=..., include_in_story=True)`,
so a missing row is invisible to report generation.

Statuses
--------
Findings, in the order they usually matter:

  ORPHAN_IN_S3     object present in S3, no StoryMedia row references it.
                   The photo exists and is unreachable: the row must be created
                   and the report regenerated. It is NOT re-uploaded - the bytes
                   are already in the bucket.
  NO_FILE_REF      row has neither `file` nor `file_url`, so get_public_url()
                   returns "" and the report renders <img src="">. The mirror
                   image of ORPHAN_IN_S3 (PUT failed, POST succeeded); no image
                   exists to restore, so regeneration cannot fix it.
  MISSING_IN_S3    row references a key that is absent from the bucket.
  STALE_REPORT     image row is newer than the stored PDF row, i.e. the report
                   was rendered before the photo was recorded. Needs
                   regeneration only.
  HOST_MISMATCH    key matches, but file_url points at a different host than the
                   bucket being audited. Matching is host-agnostic by design, so
                   without this a row referencing another environment would look
                   healthy while rendering from somewhere else.
  EXCLUDED         row and object both exist, but include_in_story is False.
  NO_MEDIA         --db-only mode only: the story has no non-PDF media rows at
                   all. A candidate set, never a finding: without the S3 pass it
                   cannot be told apart from "no photo was ever uploaded".

Not findings - reported so they cannot be mistaken for findings:

  OK / OK_BASENAME    row and object agree (the latter matched on filename only)
  OK_FOREIGN_PATH     object exists under a different story id than the row's.
                      Rows migrated between environments keep the source
                      environment's id in the stored path. Do not backfill these.
  STORY_NOT_IN_DB     object filed under a story id absent from this database -
                      deleted story or partial dump, not an upload failure.
  OUT_OF_SCOPE        object belongs to a story excluded by the current filters.
  UNATTRIBUTED_IN_S3  identifier matches no story; CompanyChat.file_url is tried
                      as a last bridge back to a session.

Usage
-----
    # 0. Learn the real key layout. Do not guess a prefix.
    python manage.py audit_story_media_s3 --discover

    # 1. Characterise a prefix and check its identifiers resolve to Stories.
    python manage.py audit_story_media_s3 --inspect chatbot/storymedia/

    # 2. Every flow and cycle, photos only.
    python manage.py audit_story_media_s3 --prefix chatbot/storymedia/ \
        --images-only --scan-unattributed --out orphans.csv

    # 3. One flow over a date window.
    #    NOTE: --flow matches Story.other_params['flow'], which holds
    #    SessionFlowName values ('guest-discussion', 'guest-mi-story',
    #    'listening-activity') - NOT Flow.flow_route ('/shikshalokam_chaupal').
    #    Run --list-flows for the values present in a given database.
    python manage.py audit_story_media_s3 --prefix chatbot/storymedia/ \
        --flow guest-discussion --from 2026-06-01 --to 2026-08-26 \
        --images-only --out chaupal.csv

    # 4. Specific sessions reported from the field.
    python manage.py audit_story_media_s3 --prefix chatbot/storymedia/ \
        --session abc-123,def-456 --all-rows --out field_reports.csv

    # 5. No S3 at all - NO_FILE_REF and STALE_REPORT need only the database.
    python manage.py audit_story_media_s3 --db-only --out blank_rows.csv

Before trusting a full run
--------------------------
Run --inspect first. It reports what fraction of the bucket's identifiers
resolve to a Story. A low rate means the database and the bucket are from
different environments, or the database is a partial dump - and every
unresolved identifier would otherwise be reported as an orphan.

Environment
-----------
Reads the same variables the app uses: STORAGE_CLOUD_PROVIDER, S3_BUCKET_NAME,
AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_MEDIA_URL. The S3
client is taken from AWSS3StorageHandler so credentials resolve exactly as they
do in the running app; --bucket overrides the bucket for cross-env checks.
"""

import csv
import os
from datetime import datetime, time as dtime
from urllib.parse import urlparse, unquote

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max, Min, Q
from django.utils import timezone

from chatbot.models import Story, StoryMedia, MediaTypeChoices
from chatbot.models.company_models import CompanyChat


CSV_COLUMNS = [
    "status",
    "story_id",
    "session",
    "flow",
    "report_type",
    "state",
    "district",
    "block",
    "story_created_at",
    "s3_key",
    "s3_size_bytes",
    "s3_last_modified",
    "story_media_id",
    "story_media_name",
    "media_type",
    "include_in_story",
    "media_created_at",
    "pdf_updated_at",
    "public_url",
    "notes",
]


def parse_date(raw, end_of_day=False):
    """Accept 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM[:SS]'. Returns an aware datetime."""
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d":
            parsed = datetime.combine(
                parsed.date(), dtime.max if end_of_day else dtime.min
            )
        return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
    raise CommandError(f"Unparseable date: {raw!r} (use YYYY-MM-DD or 'YYYY-MM-DD HH:MM')")


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif",
    ".gif", ".bmp", ".tif", ".tiff", ".svg",
}


def url_host(raw):
    """Host of a full URL, or None for keys and blanks."""
    if not raw:
        return None
    raw = str(raw).strip()
    if raw.startswith("s3://"):
        return raw[len("s3://"):].split("/", 1)[0] or None
    if raw.startswith("http://") or raw.startswith("https://"):
        return urlparse(raw).netloc or None
    return None


def is_image_key(key):
    return os.path.splitext(key or "")[1].lower() in IMAGE_EXTENSIONS


def csv_list(raw):
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def to_object_key(raw, bucket, media_base):
    """
    Normalise anything that identifies an object into a bare S3 key.

    Handles the four shapes that reach the DB:
      s3://bucket/key                     (what the presigned endpoint returns)
      https://bucket/key                  (AWSS3StorageHandler.get_public_url)
      https://cdn.example.com/key         (S3_MEDIA_URL + FileField name)
      chatbot/storymedia/12/1699-a.jpg    (FileField.name, already a key)
    """
    if not raw:
        return None
    raw = str(raw).strip()
    if not raw:
        return None

    if raw.startswith("s3://"):
        rest = raw[len("s3://"):]
        parts = rest.split("/", 1)
        return unquote(parts[1]) if len(parts) == 2 else None

    if raw.startswith("http://") or raw.startswith("https://"):
        key = unquote(urlparse(raw).path).lstrip("/")
        # Path-style URLs put the bucket in the first path segment; virtual-host
        # and CDN URLs do not. Strip it only when it is actually there.
        if bucket and key.startswith(bucket.rstrip("/") + "/"):
            key = key[len(bucket.rstrip("/")) + 1:]
        return key or None

    if media_base:
        base_path = unquote(urlparse(media_base).path).strip("/")
        if base_path and raw.lstrip("/").startswith(base_path + "/"):
            return raw.lstrip("/")

    return unquote(raw).lstrip("/") or None


class Command(BaseCommand):
    help = "Audit StoryMedia rows against objects in S3 and report the mismatches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--prefix",
            help="Object key prefix that story uploads live under, e.g. "
                 "'chatbot/storymedia/'. Run --discover first if unsure.",
        )
        parser.add_argument(
            "--discover", action="store_true",
            help="Do not audit. List the bucket's top two prefix levels with "
                 "object counts so the real folder_structure is visible.",
        )
        parser.add_argument("--bucket", help="Override S3_BUCKET_NAME.")
        parser.add_argument(
            "--max-children", type=int, default=40,
            help="--discover: sub-prefixes to list per top-level prefix. Truncation "
                 "is always reported, never silent.",
        )
        parser.add_argument(
            "--samples", type=int, default=3,
            help="--discover / --inspect: example full keys to print per prefix.",
        )
        parser.add_argument(
            "--inspect",
            help="Print sample keys, identifier shapes and file types under one "
                 "prefix, and check how many identifiers actually resolve to a "
                 "Story - then exit. Run this before committing to a --prefix.",
        )

        # Scoping
        parser.add_argument(
            "--flow",
            help="Comma-separated Story.other_params['flow'] values, e.g. "
                 "'guest-discussion'. These are SessionFlowName values, not "
                 "Flow.flow_route paths - run --list-flows to see them.",
        )
        parser.add_argument("--report-type", help="Comma-separated Story.report_type values.")
        parser.add_argument("--state", help="Comma-separated states (case-insensitive).")
        parser.add_argument("--district", help="Comma-separated districts (case-insensitive).")
        parser.add_argument("--session", help="Comma-separated session ids.")
        parser.add_argument("--story-id", help="Comma-separated Story ids.")
        parser.add_argument("--from", dest="date_from", help="Story.created_at >= this.")
        parser.add_argument("--to", dest="date_to", help="Story.created_at <= this.")
        parser.add_argument("--limit", type=int, help="Cap the number of stories examined.")

        # Behaviour
        parser.add_argument(
            "--scan-mode", choices=["prefix", "per-story"], default="prefix",
            help="'prefix' (default) sweeps the whole prefix once and indexes the "
                 "objects by the story id in the key - a few hundred LIST calls for "
                 "any scope. 'per-story' issues one LIST per story, which is only "
                 "cheaper when auditing a handful of sessions out of a large bucket.",
        )
        parser.add_argument(
            "--max-objects", type=int, default=2_000_000,
            help="Abort the prefix sweep past this many objects rather than "
                 "building an unbounded in-memory index.",
        )
        parser.add_argument(
            "--scan-unattributed", action="store_true",
            help="Also sweep the whole prefix for objects whose key carries no "
                 "numeric story id, and try to attribute them via CompanyChat.file_url.",
        )
        parser.add_argument(
            "--no-basename-fallback", action="store_true",
            help="Match strictly on the full object key. By default a key that "
                 "does not match exactly is retried on basename, which catches "
                 "rows written with a different prefix (reported as OK_BASENAME).",
        )
        parser.add_argument(
            "--images-only", action="store_true",
            help="Consider only image objects (jpg/png/webp/heic/...), ignoring "
                 "PDFs. The ticket is about missing PHOTOS, and every report "
                 "regeneration writes another PDF into the same folder, so old "
                 "PDFs pile up with no row pointing at them. Without this flag "
                 "those stale PDFs are counted as orphans and can outnumber the "
                 "real finding.",
        )
        parser.add_argument(
            "--all-rows", action="store_true",
            help="Write OK rows to the CSV too, not just the problems.",
        )
        parser.add_argument("--out", help="CSV output path. Defaults to stdout summary only.")

        # Local / offline modes - no S3, no boto3, no credentials.
        parser.add_argument(
            "--db-only", action="store_true",
            help="Never touch S3. Report what the database alone knows about each "
                 "story's media. Use this to pull entries for a flow locally.",
        )
        parser.add_argument(
            "--list-flows", action="store_true",
            help="Never touch S3. Print the distinct other_params['flow'] values "
                 "with story counts, so --flow can be given a real value.",
        )

    # ------------------------------------------------------------------ setup

    def get_s3(self, bucket_override):
        try:
            from chatbot.services.storage.aws_storage_handler import AWSS3StorageHandler
        except ImportError as exc:  # pragma: no cover
            raise CommandError(f"Could not import the S3 handler: {exc}")

        config = {}
        if bucket_override:
            config["bucket_name"] = bucket_override
        try:
            handler = AWSS3StorageHandler(config)
        except ValueError as exc:
            raise CommandError(
                f"S3 not configured ({exc}). Set S3_BUCKET_NAME and AWS_REGION, "
                f"or pass --bucket."
            )
        return handler.client, handler.bucket_name

    # --------------------------------------------------------------- discover

    def discover(self, client, bucket, max_children=40, samples=3):
        """
        Show the bucket's top two prefix levels, with sample keys.

        S3 returns CommonPrefixes lexicographically, so a prefix like
        'chatbot/storymedia/' sorts after any numeric- or letter-leading sibling.
        Truncation is therefore always announced rather than silent: a capped
        listing can hide the very prefix being looked for. Sample keys are
        printed alongside the counts, because the shape of a real key settles
        the layout far faster than a count does.
        """
        self.stdout.write(f"Bucket: {bucket}\n")
        paginator = client.get_paginator("list_objects_v2")

        def children(prefix):
            found = []
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
                for common in page.get("CommonPrefixes", []):
                    found.append(common["Prefix"])
            return found

        def sample_keys(prefix, count):
            response = client.list_objects_v2(
                Bucket=bucket, Prefix=prefix, MaxKeys=max(count, 1)
            )
            return [obj["Key"] for obj in response.get("Contents", [])][:count]

        for level_one in children(""):
            count = self.count_objects(client, bucket, level_one, cap=20000)
            self.stdout.write(f"  {level_one:<50} ~{count} objects")

            for key in sample_keys(level_one, samples):
                self.stdout.write(f"      e.g. {key}")

            subs = children(level_one)
            for level_two in subs[:max_children]:
                sub_count = self.count_objects(client, bucket, level_two, cap=20000)
                self.stdout.write(f"    {level_two:<48} ~{sub_count} objects")
            if len(subs) > max_children:
                self.stdout.write(self.style.WARNING(
                    f"    ... and {len(subs) - max_children} MORE sub-prefixes not "
                    f"shown (raise --max-children to see them)"
                ))

        self.stdout.write(
            "\nRead the 'e.g.' sample keys, not just the counts. The segment after "
            "the prefix identifies the story - it may be a numeric Story.id or a "
            "Story.session token; the audit matches either.\n"
        )

    def inspect_prefix(self, client, bucket, prefix, samples):
        """
        Characterise one prefix before trusting it as --prefix.

        Answers the three questions that decide whether the audit can work:
        what the identifier segment looks like, what file types are stored, and
        - the one that actually matters - how many of those identifiers resolve
        to a real Story by id or session. A prefix whose identifiers resolve to
        nothing will produce a bucketful of false orphans.
        """
        from collections import Counter

        if not prefix.endswith("/"):
            prefix += "/"

        shapes, extensions = Counter(), Counter()
        identifiers = set()
        examples = []
        total = 0

        for key, size, _ in self.list_prefix(client, bucket, prefix):
            total += 1
            tail = key[len(prefix):]
            if "/" not in tail:
                shapes["file directly under the prefix (no identifier segment)"] += 1
            else:
                segment = tail.split("/", 1)[0]
                identifiers.add(segment)
                if segment.isdigit():
                    shapes["numeric (Story.id shaped)"] += 1
                elif len(segment) == 32 and segment.isalnum():
                    shapes["32-char alphanumeric (session token shaped)"] += 1
                else:
                    shapes[f"other ({len(segment)} chars)"] += 1
            extensions[(os.path.splitext(key)[1] or "<none>").lower()] += 1
            if len(examples) < samples:
                examples.append((key, size))

        self.stdout.write(f"\nPrefix: {prefix}   ({total} objects)\n")
        self.stdout.write("sample keys:")
        for key, size in examples:
            self.stdout.write(f"  {size:>10}  {key}")

        self.stdout.write("\nidentifier segment shapes:")
        for shape, count in shapes.most_common():
            self.stdout.write(f"  {count:>7}  {shape}")

        self.stdout.write("\nfile types:")
        for ext, count in extensions.most_common(15):
            self.stdout.write(f"  {count:>7}  {ext}")

        if not identifiers:
            self.stdout.write(self.style.WARNING(
                "\nNo identifier segments at all - objects sit directly under this "
                "prefix, so no key-based join to a Story is possible here.\n"
            ))
            return

        segments = list(identifiers)
        numeric = [int(s) for s in segments if s.isdigit()]
        by_session = set(
            Story.objects.filter(session__in=segments).values_list("session", flat=True)
        )
        by_id = set(
            str(i) for i in
            Story.objects.filter(id__in=numeric).values_list("id", flat=True)
        )
        resolved = by_session | by_id
        unresolved = len(identifiers) - len(resolved)

        rate = len(resolved) / len(identifiers)
        self.stdout.write(
            f"\n{len(identifiers)} distinct identifiers under this prefix:\n"
            f"  {len(by_session):>7}  resolve to a Story.session\n"
            f"  {len(by_id):>7}  resolve to a Story.id\n"
            f"  {unresolved:>7}  resolve to neither   ({rate:.0%} resolved)"
        )

        # An id range comparison separates the two ways this goes wrong: a
        # partial dump overlaps the bucket's range but sparsely, while a
        # different environment tends to occupy a different range entirely.
        if numeric:
            db_range = Story.objects.aggregate(lo=Min("id"), hi=Max("id"))
            self.stdout.write(
                f"\n  numeric ids in bucket : {min(numeric)} .. {max(numeric)}\n"
                f"  Story.id in database  : {db_range['lo']} .. {db_range['hi']}"
            )
        missing = sorted(set(segments) - resolved)[:10]
        if missing:
            self.stdout.write(f"  examples not in the DB: {', '.join(missing)}")

        if rate >= 0.8:
            self.stdout.write(self.style.SUCCESS(
                "\nThe join holds for most objects: this prefix is usable as --prefix.\n"
            ))
        elif rate >= 0.2:
            self.stdout.write(self.style.WARNING(
                "\nOnly a minority of identifiers resolve. The prefix looks right, but\n"
                "the database is missing most of the stories these objects belong to.\n"
                "Every unresolved identifier would be reported as an orphan, so fix\n"
                "the data before believing any count from a full run.\n"
            ))
        else:
            self.stdout.write(self.style.ERROR(
                "\nAlmost nothing resolves. The prefix itself may be correct, but the\n"
                "bucket and the database are very likely from DIFFERENT ENVIRONMENTS,\n"
                "or the dump is a small subset. Compare the id ranges above: a partial\n"
                "dump overlaps the bucket's range sparsely, a different environment\n"
                "usually sits in a different range. Do NOT run a full audit on this\n"
                "pairing - it would report almost every object as an orphan.\n"
            ))

    def count_objects(self, client, bucket, prefix, cap=5000):
        paginator = client.get_paginator("list_objects_v2")
        total = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            total += page.get("KeyCount", 0)
            if total >= cap:
                return f"{cap}+"
        return total

    def list_prefix(self, client, bucket, prefix):
        """Yield (key, size, last_modified) for every object under prefix."""
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith("/"):
                    continue  # folder placeholder
                yield obj["Key"], obj["Size"], obj["LastModified"]

    def build_object_index(self, client, bucket, prefix, max_objects):
        """
        Sweep the prefix once and group every object by the identifier segment in
        its key. One LIST per 1000 objects, instead of one LIST per story.

        Returns (by_segment, total). Keys are the raw segment strings, kept as
        text rather than coerced to ints: the presign endpoint writes whatever
        the client passed as `storyId`, which is sometimes a numeric Story.id and
        sometimes a Story.session token. Deciding which is which is the caller's
        job, done by matching against real rows instead of guessing from shape.
        """
        by_segment = {}
        total = 0

        self.stdout.write(f"Indexing objects under {prefix} ...")
        for key, size, last_modified in self.list_prefix(client, bucket, prefix):
            total += 1
            if total > max_objects:
                raise CommandError(
                    f"Prefix holds more than {max_objects} objects. Narrow --prefix, "
                    f"raise --max-objects, or use --scan-mode per-story."
                )
            if total % 50_000 == 0:
                self.stdout.write(f"  ... {total} objects indexed")

            segment = key[len(prefix):].split("/", 1)[0]
            by_segment.setdefault(segment, []).append((key, size, last_modified))

        numeric = sum(1 for seg in by_segment if seg.isdigit())
        self.stdout.write(
            f"Indexed {total} objects across {len(by_segment)} distinct identifiers "
            f"({numeric} numeric, {len(by_segment) - numeric} non-numeric)\n"
        )
        return by_segment, total

    # ------------------------------------------------------------------ query

    def build_queryset(self, opts):
        qs = Story.objects.all()

        story_ids = csv_list(opts.get("story_id"))
        if story_ids:
            qs = qs.filter(id__in=[int(sid) for sid in story_ids])

        sessions = csv_list(opts.get("session"))
        if sessions:
            qs = qs.filter(session__in=sessions)

        flows = csv_list(opts.get("flow"))
        if flows:
            flow_q = Q()
            for flow in flows:
                flow_q |= Q(other_params__flow=flow)
            qs = qs.filter(flow_q)

        report_types = csv_list(opts.get("report_type"))
        if report_types:
            qs = qs.filter(report_type__in=report_types)

        states = csv_list(opts.get("state"))
        if states:
            state_q = Q()
            for state in states:
                state_q |= Q(state__iexact=state)
            qs = qs.filter(state_q)

        districts = csv_list(opts.get("district"))
        if districts:
            district_q = Q()
            for district in districts:
                district_q |= Q(district__iexact=district)
            qs = qs.filter(district_q)

        date_from = parse_date(opts.get("date_from"))
        if date_from:
            qs = qs.filter(created_at__gte=date_from)
        date_to = parse_date(opts.get("date_to"), end_of_day=True)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)

        return qs.order_by("id")

    # ----------------------------------------------------------------- handle

    def preflight(self):
        """
        A restored dump that omitted the storymedia table looks exactly like a
        catastrophic data-loss bug: every story reports NO_MEDIA. Print the raw
        table counts up front so that case is obvious before anyone reads the
        summary, and say so explicitly when media coverage is implausibly low.
        """
        total_stories = Story.objects.count()
        total_media = StoryMedia.objects.count()
        with_media = StoryMedia.objects.values("story_id").distinct().count()

        self.stdout.write(
            f"preflight: {total_stories} stories, {total_media} StoryMedia rows, "
            f"{with_media} stories with at least one media row"
        )

        if total_stories and (with_media / total_stories) < 0.05:
            self.stdout.write(self.style.ERROR(
                "\n  Fewer than 5% of stories have ANY StoryMedia row - including the\n"
                "  PDF row that update_story_pdf requires to already exist. That is not\n"
                "  a plausible production state, so the storymedia table in this\n"
                "  database is very likely incomplete or was never loaded.\n"
                "\n"
                "  Every classification below is therefore untrustworthy:\n"
                "    --db-only  -> NO_MEDIA will be inflated to ~100%\n"
                "    S3 mode    -> ORPHAN_IN_S3 will be inflated to ~100%, because\n"
                "                  every real object has no row to match against.\n"
                "  Use this run to prove the plumbing works (prefix correct, keys\n"
                "  parsed, matching logic sound). Do not read the counts as findings.\n"
            ))
        return total_media

    def warn_if_empty(self, opts, total):
        """
        A filter that matches nothing looks identical to a clean audit: zeros
        everywhere. Say so loudly instead, and name the filters that were applied.
        Returns False when the caller should stop.
        """
        if total:
            return True

        applied = {
            key: opts.get(key)
            for key in ("flow", "report_type", "state", "district", "session",
                        "story_id", "date_from", "date_to")
            if opts.get(key)
        }
        if not applied:
            self.stdout.write(self.style.WARNING(
                "No stories in this database at all - restore a dump before auditing."
            ))
            return False

        self.stdout.write(self.style.ERROR(
            "0 stories matched. This is a filter miss, not a clean audit."
        ))
        for key, value in applied.items():
            self.stdout.write(f"    --{key.replace('_', '-')} = {value}")
        if "flow" in applied:
            self.stdout.write(self.style.WARNING(
                "\n--flow matches Story.other_params['flow'] (SessionFlowName values "
                "such as 'guest-discussion'), not Flow.flow_route paths such as "
                "'/shikshalokam_chaupal'. Run --list-flows for the values actually present."
            ))
        return False

    def iterate(self, stories, limit, chunk_size=500):
        """
        Yield stories in primary-key batches with story_media prefetched.

        Two reasons this is not a plain .iterator():

        * `story.story_media.all()` inside the loop is one query per story. On
          ~10k stories that is ~10k round trips at the database - fine locally,
          rude against production. prefetch_related collapses each batch to one
          extra query.
        * prefetch_related is silently ignored by .iterator() before Django 4.1,
          so combining them would reintroduce the N+1 without any warning.
          Keyset pagination sidesteps the version question entirely.

        Keyset (pk > last) rather than OFFSET, so page N does not get slower as
        N grows.
        """
        qs = stories.prefetch_related("story_media")
        if limit:
            yield from qs[:limit]
            return

        last_pk = 0
        while True:
            batch = list(qs.filter(pk__gt=last_pk)[:chunk_size])
            if not batch:
                return
            for story in batch:
                yield story
            last_pk = batch[-1].pk

    def handle(self, *args, **opts):
        media_base = os.getenv("S3_MEDIA_URL") or ""

        # These two modes never construct an S3 client, so they run on a laptop
        # with no credentials and no boto3 installed.
        if opts["list_flows"]:
            self.list_flows()
            return
        if opts["db_only"]:
            self.run_db_only(opts, media_base)
            return

        client, bucket = self.get_s3(opts.get("bucket"))

        if opts["discover"]:
            self.discover(client, bucket, opts["max_children"], opts["samples"])
            return
        if opts["inspect"]:
            self.inspect_prefix(client, bucket, opts["inspect"], opts["samples"])
            return

        prefix = opts.get("prefix")
        if not prefix:
            raise CommandError("--prefix is required (or run --discover first).")
        if not prefix.endswith("/"):
            prefix += "/"

        basename_fallback = not opts["no_basename_fallback"]
        rows = []
        counters = {
            "stories": 0,
            "OK": 0,
            "OK_BASENAME": 0,
            "ORPHAN_IN_S3": 0,
            "MISSING_IN_S3": 0,
            "EXCLUDED": 0,
            "STALE_REPORT": 0,
            "UNATTRIBUTED_IN_S3": 0,
            "NO_FILE_REF": 0,
            "HOST_MISMATCH": 0,
        }

        self.preflight()
        stories = self.build_queryset(opts)
        total = stories.count()
        if not self.warn_if_empty(opts, total):
            return
        self.stdout.write(f"Bucket {bucket}, prefix {prefix}, scan-mode {opts['scan_mode']}")
        self.stdout.write(f"Auditing {total} stories ...\n")

        allowed_hosts = {bucket}
        media_host = url_host(media_base)
        if media_host:
            allowed_hosts.add(media_host)

        object_index = None
        all_keys = set()
        if opts["scan_mode"] == "prefix":
            object_index, _ = self.build_object_index(
                client, bucket, prefix, opts["max_objects"]
            )
            # Flat set of every key under the prefix. Needed because the id
            # segment in a row's stored URL does not always equal that row's
            # story_id - migrated rows keep the SOURCE environment's story id in
            # the path. Looking only inside this story's own folder would call
            # such a row MISSING_IN_S3 even though the object is right there
            # under another folder.
            for objs in object_index.values():
                all_keys.update(key for key, _, _ in objs)
        matched_segments = set()

        for story in self.iterate(stories, opts.get("limit")):
            counters["stories"] += 1
            if counters["stories"] % 200 == 0:
                self.stdout.write(f"  ... {counters['stories']}/{total}")

            media_rows = list(story.story_media.all())
            pdf_row = next(
                (m for m in media_rows if m.media_type == MediaTypeChoices.PDF), None
            )

            # Map every key this story's rows claim, from both file_url and file.
            key_to_media = {}
            basename_to_media = {}
            for media in media_rows:
                for raw in (media.file_url, media.file.name if media.file else None):
                    key = to_object_key(raw, bucket, media_base)
                    if not key:
                        continue
                    key_to_media.setdefault(key, media)
                    basename_to_media.setdefault(key.rsplit("/", 1)[-1], media)

            seen_media_ids = set()

            # The presign endpoint puts whatever the client sent as `storyId` into
            # the key. In practice that is sometimes the numeric Story.id and
            # sometimes the session token, so both are treated as identifiers.
            identifiers = [str(story.id)]
            if story.session:
                identifiers.append(story.session)

            if object_index is not None:
                story_objects = []
                for ident in identifiers:
                    if ident in object_index:
                        matched_segments.add(ident)
                        story_objects.extend(object_index[ident])
            else:
                story_objects = []
                for ident in identifiers:
                    story_objects.extend(
                        self.list_prefix(client, bucket, f"{prefix}{ident}/")
                    )

            for key, size, last_modified in story_objects:
                if opts["images_only"] and not is_image_key(key):
                    continue

                media = key_to_media.get(key)
                status = "OK"
                notes = ""

                if media is None and basename_fallback:
                    media = basename_to_media.get(key.rsplit("/", 1)[-1])
                    if media is not None:
                        status = "OK_BASENAME"
                        notes = "matched on filename only - stored path differs from the S3 key"

                if media is None:
                    status = "ORPHAN_IN_S3"
                    notes = (
                        "object uploaded to S3 but no StoryMedia row references it - "
                        "the /api/storymedia/ POST never completed"
                    )
                else:
                    seen_media_ids.add(media.id)
                    if not media.include_in_story and media.media_type != MediaTypeChoices.PDF:
                        status = "EXCLUDED"
                        notes = "row exists and object exists, but include_in_story=False so the report skips it"
                    else:
                        # Matching is host-agnostic by design - the same key is
                        # written with s3://, https://bucket/ and CDN forms. That
                        # means a row pointing at ANOTHER environment's host still
                        # matches a key here and looks OK, while the report
                        # actually renders from that other host. Catch it.
                        host = url_host(media.file_url)
                        if host and host not in allowed_hosts:
                            status = "HOST_MISMATCH"
                            notes = (
                                f"key matches, but file_url points at {host} rather "
                                f"than {bucket} - the report renders from that host, "
                                f"so the photo appears only if it serves the file"
                            )

                if status.startswith("OK") and not opts["all_rows"]:
                    counters[status] += 1
                    continue

                counters[status] = counters.get(status, 0) + 1
                rows.append(self.row(story, key, size, last_modified, media, pdf_row, status, notes))

            # Rows whose object is not in S3 at all.
            for media in media_rows:
                if media.id in seen_media_ids:
                    continue
                claimed = to_object_key(
                    media.file_url or (media.file.name if media.file else None),
                    bucket, media_base,
                )
                if not claimed:
                    # Neither file nor file_url. get_public_url() returns "" for
                    # these, so story_images_page emits <img src=""> and the
                    # report shows nothing - a rendering failure that is invisible
                    # to any S3 comparison, because there is no key to compare.
                    # Previously these rows were skipped entirely and vanished
                    # from the audit.
                    if opts["images_only"] and media.media_type == MediaTypeChoices.PDF:
                        continue
                    counters["NO_FILE_REF"] = counters.get("NO_FILE_REF", 0) + 1
                    rows.append(self.row(
                        story, "", "", "", media, pdf_row, "NO_FILE_REF",
                        "row has neither file nor file_url, so get_public_url() "
                        "returns an empty string and the report renders a blank "
                        "image - likely a legacy base64-era row; check base64_str",
                    ))
                    continue
                if opts["images_only"] and not is_image_key(claimed):
                    continue
                if not claimed.startswith(prefix):
                    continue  # belongs to another prefix (e.g. server-side PDF upload)

                if claimed in all_keys:
                    # The object exists, just not under this story's own id.
                    # Real case: rows migrated between environments keep the
                    # source env's story id in the stored path.
                    foreign = claimed[len(prefix):].split("/", 1)[0]
                    counters["OK_FOREIGN_PATH"] = counters.get("OK_FOREIGN_PATH", 0) + 1
                    if opts["all_rows"]:
                        rows.append(self.row(
                            story, claimed, "", "", media, pdf_row, "OK_FOREIGN_PATH",
                            f"object exists, but filed under id {foreign} rather than "
                            f"this row's story_id {story.id} - typically a row migrated "
                            f"from another environment; renders fine, do not backfill",
                        ))
                    continue

                counters["MISSING_IN_S3"] += 1
                rows.append(self.row(
                    story, claimed, "", "", media, pdf_row, "MISSING_IN_S3",
                    "StoryMedia row points at a key that is absent from the bucket - "
                    "row created but the PUT never landed",
                ))

            # Report rendered before the image was recorded.
            if pdf_row is not None:
                for media in media_rows:
                    if media.media_type == MediaTypeChoices.PDF:
                        continue
                    if not media.include_in_story:
                        continue
                    if media.created_at and pdf_row.updated_at and media.created_at > pdf_row.updated_at:
                        counters["STALE_REPORT"] += 1
                        rows.append(self.row(
                            story,
                            to_object_key(media.file_url or (media.file.name if media.file else None),
                                          bucket, media_base) or "",
                            "", "", media, pdf_row, "STALE_REPORT",
                            "image row is newer than the stored PDF - the report was "
                            "rendered before this photo was recorded; needs regeneration",
                        ))

        if opts["scan_unattributed"]:
            if object_index is None:
                self.stdout.write(self.style.WARNING(
                    "\n--scan-unattributed needs the full prefix index; it is skipped "
                    "under --scan-mode per-story."
                ))
            else:
                rows.extend(self.scan_unattributed(
                    object_index, matched_segments, media_base, counters,
                    images_only=opts["images_only"],
                ))

        self.write_out(rows, opts.get("out"))
        self.summarise(counters)

    # ------------------------------------------------------------ db-only

    def list_flows(self):
        """
        Distinct flow values with counts. Read straight off other_params rather
        than through a JSON lookup, so it behaves the same on SQLite and Postgres.
        """
        from collections import Counter

        flows = Counter()
        states = Counter()
        total = 0
        for params, state in Story.objects.values_list("other_params", "state").iterator(
            chunk_size=2000
        ):
            total += 1
            flows[(params or {}).get("flow") or "<no flow>"] += 1
            states[state or "<no state>"] += 1

        self.stdout.write(f"{total} stories in this database\n")
        self.stdout.write("flow values:")
        for flow, count in flows.most_common():
            self.stdout.write(f"  {count:>7}  {flow}")
        self.stdout.write("\nstates:")
        for state, count in states.most_common(25):
            self.stdout.write(f"  {count:>7}  {state}")
        self.stdout.write(
            "\nPass one of the flow values to --flow. If this prints 0 stories, "
            "the local database has no data to audit - restore a dump first.\n"
        )

    def run_db_only(self, opts, media_base):
        """
        Everything the database alone can say, with no S3 call. This cannot
        distinguish 'photo never uploaded' from 'photo uploaded but the row was
        lost' - only the S3 pass can. It does fully resolve the rows that exist
        but cannot render, and the reports rendered before their photos landed.
        """
        rows = []
        counters = {
            "stories": 0, "OK": 0, "NO_MEDIA": 0,
            "NO_FILE_REF": 0, "EXCLUDED": 0, "STALE_REPORT": 0,
        }

        self.preflight()
        stories = self.build_queryset(opts)
        total = stories.count()
        if not self.warn_if_empty(opts, total):
            return
        self.stdout.write(f"DB-only mode (no S3). Examining {total} stories ...\n")

        for story in self.iterate(stories, opts.get("limit")):
            counters["stories"] += 1
            if counters["stories"] % 500 == 0:
                self.stdout.write(f"  ... {counters['stories']}/{total}")

            media_rows = list(story.story_media.all())
            pdf_row = next(
                (m for m in media_rows if m.media_type == MediaTypeChoices.PDF), None
            )
            images = [m for m in media_rows if m.media_type != MediaTypeChoices.PDF]

            if not images:
                counters["NO_MEDIA"] += 1
                rows.append(self.row(
                    story, "", "", "", None, pdf_row, "NO_MEDIA",
                    "no non-PDF StoryMedia rows at all - either no photo was ever "
                    "uploaded, or the row was lost; only the S3 pass can tell which",
                ))
                continue

            for media in images:
                key = to_object_key(
                    media.file_url or (media.file.name if media.file else None),
                    None, media_base,
                )
                if not key:
                    status = "NO_FILE_REF"
                    notes = ("row exists but neither file nor file_url is set - "
                             "nothing for the report to render")
                elif not media.include_in_story:
                    status = "EXCLUDED"
                    notes = "include_in_story=False, so story_images_page skips it"
                elif (pdf_row and media.created_at and pdf_row.updated_at
                      and media.created_at > pdf_row.updated_at):
                    status = "STALE_REPORT"
                    notes = ("image row is newer than the stored PDF - the report was "
                             "rendered before this photo was recorded")
                else:
                    status = "OK"
                    notes = ""

                counters[status] = counters.get(status, 0) + 1
                if status == "OK" and not opts["all_rows"]:
                    continue
                rows.append(self.row(story, key, "", "", media, pdf_row, status, notes))

        self.write_out(rows, opts.get("out"))

        self.stdout.write("\n--- summary (DB only, S3 not consulted) ---")
        self.stdout.write(f"stories examined      : {counters['stories']}")
        self.stdout.write(f"OK                    : {counters['OK']}")
        self.stdout.write(self.style.WARNING(
            f"NO_MEDIA              : {counters['NO_MEDIA']}"))
        self.stdout.write(self.style.ERROR(
            f"NO_FILE_REF           : {counters['NO_FILE_REF']}"))
        self.stdout.write(f"EXCLUDED              : {counters['EXCLUDED']}")
        self.stdout.write(self.style.WARNING(
            f"STALE_REPORT          : {counters['STALE_REPORT']}"))
        self.stdout.write(
            "\nNO_MEDIA is the candidate set for the orphan bug, but it is only a "
            "candidate set: confirming an object is actually sitting in S3 for "
            "those stories needs a run without --db-only.\n"
        )

    # -------------------------------------------------------- unattributed

    def scan_unattributed(self, object_index, matched_segments, media_base, counters,
                          images_only=False):
        """
        Identifiers in the bucket that no audited story claimed.

        Rather than guessing from the key shape, this works by subtraction: every
        segment the story pass matched is removed, and what remains is checked
        against the whole Story table. A leftover that does belong to a story
        outside the current filter is reported as OUT_OF_SCOPE, not as a finding -
        conflating the two would manufacture orphans out of a narrow --flow.

        Whatever matches no story at all is genuinely unplaceable by key, so
        CompanyChat.file_url is tried as the last bridge back to a session.
        """
        leftovers = {}
        for seg, objs in object_index.items():
            if seg in matched_segments:
                continue
            # Apply the same image filter the story pass used, so the CSV does
            # not silently mix PDFs into these buckets while excluding them
            # everywhere else.
            if images_only:
                objs = [o for o in objs if is_image_key(o[0])]
                if not objs:
                    continue
            leftovers[seg] = objs
        if not leftovers:
            return []

        self.stdout.write(
            f"\nResolving {len(leftovers)} identifiers in the bucket that no "
            f"audited story claimed ..."
        )

        # One query instead of one per segment.
        segments = list(leftovers)
        numeric = [int(s) for s in segments if s.isdigit()]
        known = Story.objects.filter(Q(session__in=segments) | Q(id__in=numeric))
        known_by_session = {s.session: s for s in known if s.session}
        known_by_id = {str(s.id): s for s in known}

        rows = []
        candidates = []
        for segment, objects in leftovers.items():
            owner = known_by_session.get(segment) or known_by_id.get(segment)
            if owner is not None:
                counters["OUT_OF_SCOPE"] = counters.get("OUT_OF_SCOPE", 0) + len(objects)
                continue

            # A key naming a story id that simply is not in the database is a
            # different animal from the orphan bug: nothing was lost at upload
            # time, the Story row itself is absent - deleted, purged, or never
            # included in this dump. Counting these as orphans would inflate the
            # finding enormously, so they get their own status.
            if segment.isdigit():
                counters["STORY_NOT_IN_DB"] = counters.get("STORY_NOT_IN_DB", 0) + len(objects)
                for key, size, last_modified in objects:
                    rows.append({
                        **{col: "" for col in CSV_COLUMNS},
                        "status": "STORY_NOT_IN_DB",
                        "story_id": segment,
                        "s3_key": key,
                        "s3_size_bytes": size,
                        "s3_last_modified": last_modified.isoformat() if last_modified else "",
                        "notes": (
                            "object filed under a Story.id that does not exist in this "
                            "database - deleted story or incomplete dump, NOT the "
                            "upload-orphan bug"
                        ),
                    })
                continue

            candidates.extend(objects)

        for key, size, last_modified in candidates:
            basename = key.rsplit("/", 1)[-1]
            if StoryMedia.objects.filter(
                Q(file_url__endswith=key) | Q(file__endswith=basename)
            ).exists():
                continue

            chat = (
                CompanyChat.objects
                .filter(file_url__icontains=basename)
                .order_by("created_at")
                .first()
            )
            session = chat.session if chat else ""
            story = Story.objects.filter(session=session).first() if session else None

            counters["UNATTRIBUTED_IN_S3"] += 1
            rows.append({
                **{col: "" for col in CSV_COLUMNS},
                "status": "UNATTRIBUTED_IN_S3",
                "s3_key": key,
                "s3_size_bytes": size,
                "s3_last_modified": last_modified.isoformat() if last_modified else "",
                "session": session,
                "story_id": story.id if story else "",
                "flow": (story.other_params or {}).get("flow", "") if story else "",
                "state": story.state if story else "",
                "district": story.district if story else "",
                "public_url": f"{(media_base or '').rstrip('/')}/{key}" if media_base else "",
                "notes": (
                    "identifier in the key matches no Story; attributed via "
                    "CompanyChat.file_url"
                    if chat else
                    "identifier in the key matches no Story and no CompanyChat row - "
                    "not attributable from stored data, needs the S3 access log"
                ),
            })
        return rows

    # ------------------------------------------------------------------ output

    def row(self, story, key, size, last_modified, media, pdf_row, status, notes):
        params = story.other_params or {}
        return {
            "status": status,
            "story_id": story.id,
            "session": story.session,
            "flow": params.get("flow", ""),
            "report_type": story.report_type or "",
            "state": story.state or "",
            "district": story.district or "",
            "block": story.block or "",
            "story_created_at": story.created_at.isoformat() if story.created_at else "",
            "s3_key": key,
            "s3_size_bytes": size,
            "s3_last_modified": last_modified.isoformat() if hasattr(last_modified, "isoformat") else last_modified,
            "story_media_id": media.id if media else "",
            "story_media_name": media.name if media else "",
            "media_type": media.media_type if media else "",
            "include_in_story": media.include_in_story if media else "",
            "media_created_at": media.created_at.isoformat() if media and media.created_at else "",
            "pdf_updated_at": pdf_row.updated_at.isoformat() if pdf_row and pdf_row.updated_at else "",
            "public_url": media.get_public_url() if media else "",
            "notes": notes,
        }

    def write_out(self, rows, out_path):
        if not out_path:
            return
        with open(out_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        self.stdout.write(f"\nWrote {len(rows)} rows to {out_path}")

    def summarise(self, counters):
        self.stdout.write("\n--- summary ---")
        self.stdout.write(f"stories examined      : {counters['stories']}")
        self.stdout.write(f"OK                    : {counters['OK']}")
        self.stdout.write(f"OK_BASENAME           : {counters['OK_BASENAME']}")
        self.stdout.write(
            f"OK_FOREIGN_PATH       : {counters.get('OK_FOREIGN_PATH', 0)} "
            f"(object exists under a different story id - migrated row, not a finding)"
        )
        self.stdout.write(self.style.ERROR(
            f"ORPHAN_IN_S3          : {counters['ORPHAN_IN_S3']}"))
        self.stdout.write(self.style.WARNING(
            f"MISSING_IN_S3         : {counters['MISSING_IN_S3']}"))
        self.stdout.write(f"EXCLUDED              : {counters['EXCLUDED']}")
        self.stdout.write(self.style.WARNING(
            f"STALE_REPORT          : {counters['STALE_REPORT']}"))
        self.stdout.write(self.style.ERROR(
            f"NO_FILE_REF           : {counters.get('NO_FILE_REF', 0)} "
            f"(row renders a blank image - no file and no file_url)"))
        self.stdout.write(self.style.WARNING(
            f"HOST_MISMATCH         : {counters.get('HOST_MISMATCH', 0)} "
            f"(key matches but file_url points at another environment's host)"))
        self.stdout.write(f"UNATTRIBUTED_IN_S3    : {counters['UNATTRIBUTED_IN_S3']}")
        if counters.get("STORY_NOT_IN_DB"):
            self.stdout.write(
                f"STORY_NOT_IN_DB       : {counters['STORY_NOT_IN_DB']} "
                f"(story id absent from the DB - deleted or not dumped, not a finding)"
            )
        if counters.get("OUT_OF_SCOPE"):
            self.stdout.write(
                f"OUT_OF_SCOPE          : {counters['OUT_OF_SCOPE']} "
                f"(objects belonging to stories outside the filter - not a finding)"
            )
        self.stdout.write(
            "\nORPHAN_IN_S3 and STALE_REPORT are the two sets that need "
            "remediation: the first needs a StoryMedia row created, both need "
            "the report regenerated afterwards.\n"
        )

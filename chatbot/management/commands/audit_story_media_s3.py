"""
Audit StoryMedia rows against the objects actually present in S3, and
(unless --dry-run) backfill the missing rows + regenerate reports.

Why this exists
----------------
Story images are NOT uploaded through Django. The client PUTs bytes straight
to S3, then POSTs to `/api/storymedia/` to create the StoryMedia row. Those
two steps are not atomic: when the POST never lands, the object sits in S3
with no row pointing at it, and the report renders without the photo.

How it works
------------
For every Story (optionally scoped by --story-id / --from / --to):

  1. LIST `chatbot/storymedia/<story_id>/` in S3.
  2. For each image object found, check whether any of the story's
     StoryMedia.file_url values end with `chatbot/storymedia/<story_id>/<file_name>`.
     Matching is host-agnostic (StoryMedia.file_url is built from
     S3_MEDIA_URL, not the bucket name, so only the path is compared).
  3. No match -> flag as ORPHAN_IN_S3, written to the --out CSV
     (columns: story_id, s3_key).

Story rows are streamed with `.iterator(chunk_size=500)` - the table is large
and nothing about a single story's audit needs the rest of the table in
memory.

Without --dry-run, once the CSV is written this command calls
`regenerate_reports_from_s3_audit` (--csv <out>) directly, which creates the
missing StoryMedia rows and regenerates the affected reports. See that
command for the backfill/regeneration logic.

Usage
-----
    python manage.py audit_story_media_s3 --out orphans.csv --dry-run
    python manage.py audit_story_media_s3 --out orphans.csv
    python manage.py audit_story_media_s3 --out orphans.csv \
        --story-id 12,45 --from 2026-06-01 --to 2026-08-26
"""

import csv
import os
from datetime import datetime, time as dtime

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from chatbot.models import Story

CSV_COLUMNS = ["story_id", "s3_key"]

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif",
    ".gif", ".bmp", ".tif", ".tiff", ".svg",
}


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


def csv_list(raw):
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def is_image_key(key):
    return os.path.splitext(key or "")[1].lower() in IMAGE_EXTENSIONS


class Command(BaseCommand):
    help = "Flag S3 story-media objects with no StoryMedia row, backfill + regenerate unless --dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--story-id", help="Comma-separated Story ids to scope to.")
        parser.add_argument("--from", dest="date_from", help="Story.created_at >= this.")
        parser.add_argument("--to", dest="date_to", help="Story.created_at <= this.")
        parser.add_argument("--out", required=True, help="CSV output path for flagged (ORPHAN_IN_S3) rows.")
        parser.add_argument("--dry-run", action="store_true", help="Write the CSV only; skip backfill + regen.")

    # ------------------------------------------------------------------ setup

    def get_storage_client(self):
        try:
            from chatbot.services.storage import StorageFactory
        except ImportError as exc:  # pragma: no cover
            raise CommandError(f"Could not import the storage factory: {exc}")
        try:
            handler = StorageFactory.get_storage_handler(config={})
        except ValueError as exc:
            raise CommandError(f"S3 not configured ({exc}). Set S3_BUCKET_NAME and AWS_REGION.")
        return handler.client, handler.bucket_name

    def list_prefix(self, client, bucket, prefix):
        """Yield (key, size, last_modified) for every object under prefix."""
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith("/"):
                    continue  # folder placeholder
                yield obj["Key"], obj["Size"], obj["LastModified"]

    # ------------------------------------------------------------------ query

    def build_queryset(self, opts):
        qs = Story.objects.all()

        story_ids = csv_list(opts.get("story_id"))
        if story_ids:
            qs = qs.filter(id__in=[int(sid) for sid in story_ids])

        date_from = parse_date(opts.get("date_from"))
        if date_from:
            qs = qs.filter(created_at__gte=date_from)
        date_to = parse_date(opts.get("date_to"), end_of_day=True)
        if date_to:
            qs = qs.filter(created_at__lte=date_to)

        return qs.order_by("id")

    # ----------------------------------------------------------------- handle

    def handle(self, *args, **opts):
        client, bucket = self.get_storage_client()
        stories = self.build_queryset(opts)

        rows = []
        examined = 0
        flagged = 0

        self.stdout.write(f"bucket: {bucket}")

        for story in stories.iterator(chunk_size=500):
            examined += 1
            if examined % 200 == 0:
                self.stdout.write(f"  ... {examined} stories examined")

            prefix = f"chatbot/storymedia/{story.id}/"
            objects = [
                (key, size, last_modified)
                for key, size, last_modified in self.list_prefix(client, bucket, prefix)
                if is_image_key(key)
            ]
            if not objects:
                continue

            file_urls = [
                fu for fu in story.story_media.values_list("file_url", flat=True) if fu
            ]

            for key, _size, _last_modified in objects:
                file_name = key.rsplit("/", 1)[-1]
                suffix = f"chatbot/storymedia/{story.id}/{file_name}"
                if any(fu.endswith(suffix) for fu in file_urls):
                    continue  # OK: some StoryMedia row already claims this object

                flagged += 1
                rows.append({"story_id": story.id, "s3_key": key})

        self.write_out(rows, opts["out"])
        self.stdout.write(f"stories examined: {examined}")
        self.stdout.write(self.style.WARNING(f"ORPHAN_IN_S3: {flagged}"))

        if opts["dry_run"]:
            self.stdout.write("[dry-run] skipping backfill + regeneration.")
            return

        if not rows:
            self.stdout.write("Nothing to backfill.")
            return

        call_command("regenerate_reports_from_s3_audit", csv=opts["out"], column="story_id")

    def write_out(self, rows, out_path):
        with open(out_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        self.stdout.write(f"Wrote {len(rows)} rows to {out_path}")

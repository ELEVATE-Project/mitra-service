#!/usr/bin/env python3
"""
Check or delete S3 objects listed in a CSV.

Modes:
  read  : check objects only
  write : dry-run by default; add --confirm to delete existing objects

Configuration:
  S3_BUCKET_NAME (or S3_BUCKET) is the bucket used for custom media URLs.
  S3_MEDIA_URL and S3_BASE_URL are optional public media URL prefixes.
  Other HTTP(S) URLs are mapped to the configured bucket using their path.
  AWS credentials use boto3's standard credential chain.

Every non-empty CSV row is included in the output report.
"""

import argparse
import csv
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"

# Use settings from the project .env rather than stale shell values.
for name in (
    "S3_MEDIA_URL",
    "S3_BASE_URL",
    "S3_BUCKET_NAME",
    "S3_BUCKET",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
):
    os.environ.pop(name, None)

if not ENV_FILE.is_file():
    print(f"ERROR: Project .env file not found: {ENV_FILE}", file=sys.stderr)
    sys.exit(1)

load_dotenv(dotenv_path=ENV_FILE, override=True)


def clean_setting(name):
    """Read a setting and remove surrounding quotes and trailing slashes."""
    return os.getenv(name, "").strip().strip("\"'").rstrip("/")


S3_MEDIA_URL = clean_setting("S3_MEDIA_URL")
S3_BASE_URL = clean_setting("S3_BASE_URL")
S3_BUCKET_NAME = clean_setting("S3_BUCKET_NAME") or clean_setting("S3_BUCKET")

AWS_REGION = (
    os.getenv("AWS_REGION", "").strip()
    or os.getenv("AWS_DEFAULT_REGION", "").strip()
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# URL normalization and parsing
# ---------------------------------------------------------------------------

def normalize_csv_url(value):
    """
    Normalize a CSV cell into a URL.

    Supports:
      - Plain HTTP(S) URLs containing spaces in the path or filename.
      - Percent-encoded paths such as %20.
      - Markdown links such as [label](https://host/path with spaces).

    Spaces are allowed in URL paths because they can be part of a filename.
    This function does not guess missing filename characters.
    """
    value = (value or "").strip().strip("\ufeff")

    if not value:
        raise ValueError("URL is empty")

    # Extract a URL from a Markdown link while preserving spaces.
    markdown = re.fullmatch(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        value,
    )

    if markdown:
        value = markdown.group(2).strip()

    elif value.startswith("[") and "](" in value:
        raise ValueError("Malformed Markdown URL in CSV cell")

    # Do NOT reject whitespace in the path.
    # urlsplit() can parse spaces in a path; the path is later decoded
    # into the original S3 object key.
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError(f"Unable to parse URL: {exc}") from exc

    if parsed.scheme == "s3":
        if not parsed.netloc:
            raise ValueError("Invalid s3:// URL: bucket is missing")
        return value

    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http://, https://, or s3://")

    if not parsed.hostname:
        raise ValueError("URL hostname is missing or invalid")

    # Reject whitespace in the hostname, not in the filename/path.
    if any(char.isspace() for char in parsed.netloc):
        raise ValueError("URL hostname or authority contains whitespace")

    return value


def parse_s3_url(raw_url, default_bucket):
    """
    Convert a URL into (bucket, key).

    Supports:
      - s3://bucket/key
      - S3 path-style URLs
      - S3 virtual-hosted URLs
      - Public CDN/custom media URLs

    URL path percent-encoding is decoded so that %20 becomes a space
    in the S3 key. Spaces in filenames are preserved.
    """
    url = normalize_csv_url(raw_url)

    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValueError(f"Unable to parse URL: {exc}") from exc

    # Native S3 URL.
    if parsed.scheme == "s3":
        bucket = parsed.netloc
        key = unquote(parsed.path.lstrip("/"))

        if not bucket or not key:
            raise ValueError("Invalid s3:// URL; bucket and key are required")

        return bucket, key

    hostname = parsed.hostname.lower()
    path = parsed.path.lstrip("/")

    if not path:
        raise ValueError("URL does not contain an object key path")

    # S3 path-style URL:
    # https://s3.amazonaws.com/bucket/key
    # https://s3.us-east-1.amazonaws.com/bucket/key
    if (
        hostname == "s3.amazonaws.com"
        or (
            hostname.startswith("s3.")
            and hostname.endswith(".amazonaws.com")
        )
    ):
        bucket, separator, encoded_key = path.partition("/")

        if not separator or not bucket or not encoded_key:
            raise ValueError("Invalid path-style S3 URL")

        return bucket, unquote(encoded_key)

    # S3 virtual-hosted URL:
    # https://bucket.s3.amazonaws.com/key
    # https://bucket.s3.us-east-1.amazonaws.com/key
    if ".s3." in hostname or hostname.endswith(".s3.amazonaws.com"):
        bucket = hostname.split(".s3", 1)[0]

        if not bucket or not path:
            raise ValueError("Invalid virtual-hosted S3 URL")

        return bucket, unquote(path)

    # Public CDN/custom media URL.
    # Map its path to the configured bucket.
    if not default_bucket:
        raise ValueError(
            "No S3 bucket configured. "
            "Set S3_BUCKET_NAME or S3_BUCKET in .env"
        )

    # Remove a configured URL base-path prefix when applicable.
    # Example:
    # Base URL: https://example.com/public
    # URL:      https://example.com/public/folder/image.png
    # Key:      folder/image.png
    for base_url in (S3_MEDIA_URL, S3_BASE_URL):
        if not base_url:
            continue

        base = urlsplit(base_url)

        if (
            base.hostname
            and hostname == base.hostname.lower()
            and parsed.scheme == base.scheme
            and (parsed.port == base.port)
        ):
            base_path = base.path.strip("/")

            if base_path:
                prefix = base_path + "/"

                if not path.startswith(prefix):
                    # This configured base does not match the path.
                    continue

                path = path[len(prefix):]

            break

    # Decode URL escapes only after parsing the URL structure.
    # This restores the actual S3 key, including spaces.
    key = unquote(path)

    if not key:
        raise ValueError("URL does not contain an object key")

    return default_bucket, key


# ---------------------------------------------------------------------------
# CSV input
# ---------------------------------------------------------------------------

def read_csv_entries(csv_path, column, limit=None):
    """
    Read non-empty URL cells from the requested CSV column.

    CSV fields may contain spaces. Spaces are not CSV delimiters.
    Quoted CSV fields can also contain commas and other characters.
    """
    entries = []

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)

        if not reader.fieldnames or column not in reader.fieldnames:
            raise ValueError(
                f"Column {column!r} not found. "
                f"Available columns: {reader.fieldnames}"
            )

        for row in reader:
            raw_url = row.get(column) or ""

            if not raw_url.strip():
                continue

            entries.append({
                "source_line": reader.line_num,
                "url": raw_url.strip(),
            })

            if limit is not None and len(entries) >= limit:
                break

    return entries


# ---------------------------------------------------------------------------
# S3 operations
# ---------------------------------------------------------------------------

def create_s3_client():
    """Create an S3 client using the configured AWS region and credentials."""
    kwargs = {}

    if AWS_REGION:
        kwargs["region_name"] = AWS_REGION

    return boto3.client("s3", **kwargs)


def check_object(s3, bucket, key):
    """
    Check whether an object exists.

    Returns:
      EXISTS, NOT_FOUND, ACCESS_DENIED, or ERROR.

    A 403 response does not prove that an object is missing.
    """
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return "EXISTS", "S3 object exists"

    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = str(error.get("Code", ""))
        http_status = exc.response.get("ResponseMetadata", {}).get(
            "HTTPStatusCode"
        )

        if code in ("404", "NoSuchKey", "NotFound") or http_status == 404:
            return "NOT_FOUND", "S3 object does not exist"

        if code in ("403", "AccessDenied") or http_status == 403:
            return (
                "ACCESS_DENIED",
                "S3 denied access; cannot verify object existence",
            )

        return "ERROR", f"AWS error {code}: {error.get('Message', str(exc))}"

    except BotoCoreError as exc:
        return "ERROR", f"AWS/client error: {exc}"


def write_report(results, output_path):
    """Write one report row for every non-empty CSV entry."""
    fields = [
        "source_line",
        "url",
        "bucket",
        "key",
        "status",
        "details",
        "checked_at_utc",
    ]

    with open(output_path, "w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(results)

    logger.info("Report written: %s", output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Check or delete S3 objects referenced in a CSV file."
    )

    parser.add_argument(
        "--mode",
        choices=("read", "write"),
        required=True,
    )
    parser.add_argument("--csv", required=True, help="Input CSV file")
    parser.add_argument(
        "--column",
        default="file_url",
        help="URL column name",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--allowed-bucket",
        default=None,
        help="Safety guard for write mode; must match the parsed bucket",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="Safety guard for write mode, e.g. chatbot/storymedia/",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete existing objects; otherwise write mode is dry-run",
    )

    args = parser.parse_args()
    csv_path = Path(args.csv).expanduser()

    if not csv_path.is_file():
        logger.error("CSV file does not exist: %s", csv_path)
        return 1

    if args.limit is not None and args.limit < 1:
        logger.error("--limit must be a positive integer")
        return 1

    logger.info("Mode: %s", args.mode)
    logger.info("CSV: %s", csv_path)
    logger.info("Project .env: %s", ENV_FILE)
    logger.info("S3_MEDIA_URL: %s", S3_MEDIA_URL or "(not configured)")
    logger.info("S3_BASE_URL: %s", S3_BASE_URL or "(not configured)")
    logger.info("Configured bucket: %s", S3_BUCKET_NAME or "(not configured)")
    logger.info("AWS region: %s", AWS_REGION or "(default credential chain)")

    # Require explicit safety guards for write mode.
    if args.mode == "write":
        if not args.allowed_bucket:
            logger.error("Write mode requires --allowed-bucket")
            return 1

        if not args.prefix or not args.prefix.endswith("/"):
            logger.error("Write mode requires --prefix ending with '/'")
            return 1

        if not S3_BUCKET_NAME:
            logger.error("No S3_BUCKET_NAME or S3_BUCKET configured in .env")
            return 1

        if args.allowed_bucket != S3_BUCKET_NAME:
            logger.error(
                "--allowed-bucket must match the configured bucket: %s",
                S3_BUCKET_NAME,
            )
            return 1

    try:
        entries = read_csv_entries(csv_path, args.column, args.limit)
    except (OSError, ValueError, csv.Error) as exc:
        logger.error("Unable to read CSV: %s", exc)
        return 1

    logger.info("Non-empty CSV entries: %d", len(entries))

    if not entries:
        logger.warning("No non-empty URLs found")
        return 0

    # Prepare and validate every row before performing any deletion.
    prepared = []
    results = []

    for entry in entries:
        now = datetime.now(timezone.utc).isoformat()

        try:
            bucket, key = parse_s3_url(entry["url"], S3_BUCKET_NAME)

            if args.mode == "write":
                if bucket != args.allowed_bucket:
                    raise ValueError(
                        f"Bucket {bucket!r} does not match "
                        f"--allowed-bucket {args.allowed_bucket!r}"
                    )

                if not key.startswith(args.prefix):
                    raise ValueError(
                        f"Key {key!r} is outside allowed prefix "
                        f"{args.prefix!r}"
                    )

            prepared.append({
                **entry,
                "bucket": bucket,
                "key": key,
            })

        except ValueError as exc:
            results.append({
                **entry,
                "bucket": "",
                "key": "",
                "status": "INVALID_URL",
                "details": str(exc),
                "checked_at_utc": now,
            })

    # Do not initialize S3 if no URLs were successfully parsed.
    if not prepared:
        results.sort(key=lambda row: row["source_line"])

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = Path.cwd() / f"delete_s3_objects_report_{timestamp}.csv"

        write_report(results, output)
        logger.info("Summary: %s", {"INVALID_URL": len(results)})
        return 0

    try:
        s3 = create_s3_client()
    except Exception as exc:
        logger.error("Unable to initialize S3 client: %s", exc)
        return 1

    for item in prepared:
        bucket = item["bucket"]
        key = item["key"]
        now = datetime.now(timezone.utc).isoformat()

        status, details = check_object(s3, bucket, key)

        if status == "NOT_FOUND":
            result_status = "NOT_FOUND"
            result_details = details + "; skipped"

        elif status != "EXISTS":
            result_status = status
            result_details = details + "; no deletion attempted"

        elif args.mode == "read":
            result_status = "EXISTS"
            result_details = details + "; read mode does not delete"

        elif not args.confirm:
            result_status = "DRY_RUN_WOULD_DELETE"
            result_details = details + "; dry run only, pass --confirm to delete"

        else:
            try:
                s3.delete_object(Bucket=bucket, Key=key)
                result_status = "DELETE_REQUESTED"
                result_details = (
                    "Delete request sent; versioned buckets may retain "
                    "older versions"
                )

            except (ClientError, BotoCoreError) as exc:
                result_status = "DELETE_ERROR"
                result_details = str(exc)

        results.append({
            **item,
            "status": result_status,
            "details": result_details,
            "checked_at_utc": now,
        })

        logger.info(
            "Line %s | %s | bucket=%s | key=%s",
            item["source_line"],
            result_status,
            bucket,
            key,
        )

    results.sort(key=lambda row: row["source_line"])

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path.cwd() / f"delete_s3_objects_report_{timestamp}.csv"

    write_report(results, output)

    summary = {}
    for result in results:
        status = result["status"]
        summary[status] = summary.get(status, 0) + 1

    logger.info("Summary: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3

"""
Read, verify, and safely delete S3 objects listed in a CSV file.

Configuration is loaded from:
1. Environment variables
2. Project .env
3. config/secrets.json

Environment variables take precedence over secrets.json.
Deletion requires --mode write, --allowed-bucket, --prefix, and --confirm.
"""

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import boto3
from botocore.exceptions import ClientError, BotoCoreError
from dotenv import load_dotenv


# ============================================================
# PATHS AND CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SECRETS_FILE = PROJECT_ROOT / "config" / "secrets.json"

# Load .env without overwriting existing environment variables.
load_dotenv(PROJECT_ROOT / ".env", override=False)


def flatten_config(data):
    """Flatten nested JSON configuration into key/value pairs."""
    result = {}

    if not isinstance(data, dict):
        return result

    for key, value in data.items():
        if isinstance(value, dict):
            result.update(flatten_config(value))
        else:
            result[key] = value

    return result


SECRETS = {}

if SECRETS_FILE.exists():
    try:
        with SECRETS_FILE.open("r", encoding="utf-8") as file:
            loaded = json.load(file)

        SECRETS = flatten_config(loaded)

        # Keep existing environment variables as the higher priority.
        for key, value in SECRETS.items():
            if value is not None and not isinstance(value, (dict, list)):
                os.environ.setdefault(key, str(value))

    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: Cannot load {SECRETS_FILE}: {exc}", file=sys.stderr)
        sys.exit(1)
else:
    print(
        f"WARNING: Secrets file not found: {SECRETS_FILE}",
        file=sys.stderr,
    )


def config_value(*names, default=""):
    """Return the first non-empty value from the environment or secrets."""
    for name in names:
        value = os.getenv(name)

        if value is not None and str(value).strip():
            return str(value).strip()

        value = SECRETS.get(name)

        if value is not None and str(value).strip():
            return str(value).strip()

    return default



S3_MEDIA_URL = config_value("S3_MEDIA_URL").strip().strip("\"'").rstrip("/")
S3_BASE_URL = config_value("S3_BASE_URL").strip().strip("\"'").rstrip("/")
AWS_REGION = config_value("AWS_REGION", "AWS_DEFAULT_REGION", default="")
S3_BUCKET_NAME = config_value("S3_BUCKET_NAME").strip().strip("\"'").rstrip("/")

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# S3 CLIENT
# ============================================================

def create_s3_client():
    """Use boto3's standard credential chain: env, profile, or IAM role."""
    options = {}

    if AWS_REGION:
        options["region_name"] = AWS_REGION

    return boto3.client("s3", **options)


# ============================================================
# URL PARSING
# ============================================================

def parse_s3_url(url, default_bucket=None):
    """
    Convert an S3 URL or configured public media URL to (bucket, key).

    Supported examples:
      s3://bucket-name/folder/file.png
      https://bucket-name.s3.amazonaws.com/folder/file.png
      https://s3.amazonaws.com/bucket-name/folder/file.png
      https://devqa-mohini-static.shikshalokam.org/folder/file.png

    For custom media domains, the bucket must be configured explicitly.
    """
    url = (url or "").strip()

    if not url:
        raise ValueError("URL is empty")

    # Direct S3 URI.
    if url.startswith("s3://"):
        parsed = urlsplit(url)
        bucket = parsed.netloc
        key = unquote(parsed.path.lstrip("/"))

        if not bucket or not key:
            raise ValueError("Invalid s3:// URL")

        return bucket, key

    parsed = urlsplit(url)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("URL must be a valid HTTP(S) or s3:// URL")

    hostname = parsed.hostname.lower()
    path = parsed.path.lstrip("/")

    # S3 path-style URL:
    # https://s3.amazonaws.com/bucket/key
    # https://s3.us-east-1.amazonaws.com/bucket/key
    if hostname == "s3.amazonaws.com" or (
        hostname.startswith("s3.")
        and hostname.endswith(".amazonaws.com")
    ):
        bucket, separator, key = path.partition("/")

        if not separator or not bucket or not key:
            raise ValueError("Invalid path-style S3 URL")

        return bucket, unquote(key)

    # S3 virtual-hosted URL:
    # https://bucket.s3.amazonaws.com/key
    # https://bucket.s3.us-east-1.amazonaws.com/key
    if ".s3." in hostname or hostname.endswith(".s3.amazonaws.com"):
        bucket = hostname.split(".s3", 1)[0]
        key = unquote(path)

        if bucket and key:
            return bucket, key

        raise ValueError("Invalid virtual-hosted S3 URL")

    # Custom public media domains configured by the application.
    media_bases = [
        S3_MEDIA_URL,
        S3_BASE_URL,
    ]

    for media_base in media_bases:
        if not media_base:
            continue

        base = urlsplit(media_base)

        if (
            base.hostname
            and hostname == base.hostname.lower()
            and parsed.scheme == base.scheme
        ):
            base_path = base.path.strip("/")

            if base_path:
                expected_prefix = base_path + "/"

                if not path.startswith(expected_prefix):
                    continue

                key = path[len(expected_prefix):]
            else:
                key = path

            key = unquote(key)
            bucket = default_bucket or S3_BUCKET_NAME

            if not bucket:
                raise ValueError(
                    "Media URL matched, but no bucket is configured. "
                    "Set S3_BUCKET_NAME/S3_BUCKET or pass --default-bucket."
                )

            if not key:
                raise ValueError("Media URL does not contain an object key")

            return bucket, key

    raise ValueError(
        f"Unable to parse URL: {url}. "
        f"Configured S3_MEDIA_URL={S3_MEDIA_URL!r}, "
        f"S3_BASE_URL={S3_BASE_URL!r}"
    )


# ============================================================
# CSV INPUT
# ============================================================

def read_csv_entries(csv_path, column, limit=None):
    """Read non-empty URLs from the requested CSV column."""
    entries = []

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames or column not in reader.fieldnames:
            raise ValueError(
                f"Column {column!r} not found. "
                f"Available columns: {reader.fieldnames}"
            )

        for row in reader:
            source_line = reader.line_num
            url = (row.get(column) or "").strip()

            if not url:
                continue

            entries.append({
                "source_line": source_line,
                "url": url,
            })

            if limit is not None and len(entries) >= limit:
                break

    return entries


# ============================================================
# S3 CHECKS
# ============================================================

def check_object(s3, bucket, key):
    """Check whether an object exists without downloading its contents."""
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return "EXISTS", "S3 object exists"

    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = str(error.get("Code", ""))
        status_code = exc.response.get(
            "ResponseMetadata", {}
        ).get("HTTPStatusCode")

        if code in ("404", "NoSuchKey", "NotFound") or status_code == 404:
            return "NOT_FOUND", "S3 object does not exist"

        if code in ("403", "AccessDenied"):
            return "ACCESS_DENIED", (
                "S3 access denied. Verify permissions and bucket mapping."
            )

        return "ERROR", f"AWS error {code}: {error.get('Message', str(exc))}"

    except BotoCoreError as exc:
        return "ERROR", str(exc)


def write_report(results, output_path):
    """Write a CSV report of all processed entries."""
    fieldnames = [
        "source_line",
        "url",
        "bucket",
        "key",
        "status",
        "details",
        "checked_at_utc",
    ]

    with open(output_path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    logger.info("Report written: %s", output_path)


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Read, verify, or delete S3 objects from a CSV."
    )

    parser.add_argument(
        "--mode",
        choices=["read", "write"],
        required=True,
        help="read = inspect only; write = prepare deletion",
    )
    parser.add_argument("--csv", required=True, help="Input CSV path")
    parser.add_argument(
        "--column",
        default="file_url",
        help="CSV column containing S3/public media URLs",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--default-bucket",
        default=None,
        help="Override bucket used for custom media URLs",
    )
    parser.add_argument(
        "--allowed-bucket",
        default=None,
        help="Required in write mode; bucket that may be deleted from",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="Required in write mode; permitted key prefix, ending in /",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete objects in write mode",
    )

    args = parser.parse_args()

    csv_path = Path(args.csv).expanduser()

    if not csv_path.is_file():
        logger.error("CSV file does not exist: %s", csv_path)
        return 1

    if args.limit is not None and args.limit < 1:
        logger.error("--limit must be a positive integer")
        return 1

    default_bucket = S3_BUCKET_NAME

    logger.info("Mode: %s", args.mode)
    logger.info("CSV: %s", csv_path)
    logger.info("S3_MEDIA_URL: %s", S3_MEDIA_URL or "(not configured)")
    logger.info("S3_BASE_URL: %s", S3_BASE_URL or "(not configured)")
    logger.info(
        "Default bucket: %s",
        default_bucket or "(not configured)",
    )

    if args.mode == "write":
        if not args.allowed_bucket:
            logger.error("Write mode requires --allowed-bucket")
            return 1

        if not args.prefix or not args.prefix.endswith("/"):
            logger.error(
                "Write mode requires --prefix ending with '/', "
                "for example chatbot/storymedia/"
            )
            return 1

    try:
        entries = read_csv_entries(csv_path, args.column, args.limit)
    except (OSError, ValueError, csv.Error) as exc:
        logger.error("Unable to read CSV: %s", exc)
        return 1

    logger.info("CSV entries: %d", len(entries))

    if not entries:
        logger.warning("No non-empty URLs found")
        return 0

    # Parse and validate every entry before any possible deletion.
    prepared = []
    validation_errors = []

    for entry in entries:
        try:
            bucket, key = parse_s3_url(
                entry["url"],
                default_bucket=default_bucket,
            )

            if args.mode == "write":
                if bucket != args.allowed_bucket:
                    raise ValueError(
                        f"Bucket {bucket!r} does not match "
                        f"--allowed-bucket {args.allowed_bucket!r}"
                    )

                if not key.startswith(args.prefix):
                    raise ValueError(
                        f"Key is outside the allowed prefix {args.prefix!r}"
                    )

            prepared.append({
                **entry,
                "bucket": bucket,
                "key": key,
            })

        except ValueError as exc:
            validation_errors.append({
                **entry,
                "bucket": "",
                "key": "",
                "status": "INVALID_URL",
                "details": str(exc),
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            })

    if args.mode == "write" and validation_errors:
        logger.error(
            "%d URL(s) failed validation. No objects will be deleted.",
            len(validation_errors),
        )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = Path.cwd() / f"delete_s3_objects_report_{timestamp}.csv"
        write_report(validation_errors, output_path)
        return 1

    s3 = None

    try:
        s3 = create_s3_client()
    except Exception as exc:
        logger.error("Unable to initialize S3 client: %s", exc)
        return 1

    results = list(validation_errors)

    for item in prepared:
        bucket = item["bucket"]
        key = item["key"]
        now = datetime.now(timezone.utc).isoformat()

        # Do not delete an object unless it can be checked first.
        status, details = check_object(s3, bucket, key)

        if status != "EXISTS":
            results.append({
                "source_line": item["source_line"],
                "url": item["url"],
                "bucket": bucket,
                "key": key,
                "status": status,
                "details": details,
                "checked_at_utc": now,
            })
            logger.info(
                "Line %s | %s | bucket=%s | key=%s",
                item["source_line"], status, bucket, key,
            )
            continue

        if args.mode == "read":
            result_status = "EXISTS"
            result_details = details

        elif not args.confirm:
            result_status = "DRY_RUN_WOULD_DELETE"
            result_details = (
                "Object exists and matches the allowed bucket/prefix. "
                "No deletion performed; rerun with --confirm to delete."
            )

        else:
            try:
                s3.delete_object(Bucket=bucket, Key=key)
                result_status = "DELETE_REQUESTED"
                result_details = (
                    "Delete request sent. Verify deletion separately; "
                    "versioned buckets may retain previous versions."
                )
            except (ClientError, BotoCoreError) as exc:
                result_status = "DELETE_ERROR"
                result_details = str(exc)

        results.append({
            "source_line": item["source_line"],
            "url": item["url"],
            "bucket": bucket,
            "key": key,
            "status": result_status,
            "details": result_details,
            "checked_at_utc": now,
        })

        logger.info(
            "Line %s | %s | bucket=%s | key=%s",
            item["source_line"], result_status, bucket, key,
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path.cwd() / f"delete_s3_objects_report_{timestamp}.csv"
    write_report(results, output_path)

    summary = {}
    for result in results:
        status = result["status"]
        summary[status] = summary.get(status, 0) + 1

    logger.info("Results: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
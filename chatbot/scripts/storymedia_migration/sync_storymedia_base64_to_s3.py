import argparse
import base64
import binascii
import json
import logging
import os
import sys
import time
from urllib.parse import urlparse

import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor


# ============================================================
# ENV
# ============================================================

load_dotenv()


DB_HOST = os.getenv("DATABASE_HOST")
DB_PORT = int(os.getenv("DATABASE_PORT", "5432"))
DB_NAME = os.getenv("DATABASE_NAME")
DB_USER = os.getenv("DATABASE_USER")
DB_PASSWORD = os.getenv("DATABASE_PASSWORD")

S3_BASE_URL = os.getenv(
    "S3_BASE_URL",
    "https://qa-mohini-static.shikshalokam.org",
)

S3_MEDIA_URL = os.getenv(
    "S3_MEDIA_URL",
    "https://qa-mohini-static.shikshalokam.org",
)

# Remove accidental quotes/trailing slash from .env values.
S3_BASE_URL = S3_BASE_URL.strip().strip('"').strip("'").rstrip("/")
S3_MEDIA_URL = S3_MEDIA_URL.strip().strip('"').strip("'").rstrip("/")


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE
# ============================================================

class Database:
    def __init__(self):
        self.connection = None

    def connect(self):
        logger.info(
            "Connecting to PostgreSQL: %s:%s/%s",
            DB_HOST,
            DB_PORT,
            DB_NAME,
        )

        self.connection = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )

        self.connection.autocommit = False

        logger.info("Database connected successfully")

    def close(self):
        if self.connection:
            self.connection.close()
            logger.info("Database connection closed")

    def fetch_batch(self, last_id, batch_size):
        """
        Fetch only lightweight columns first.
        Base64 is fetched separately to avoid loading huge Base64
        values for the entire batch into memory.
        """

        query = """
            SELECT
                id,
                file,
                file_url
            FROM chatbot_storymedia
            WHERE id > %s
              AND base64_str IS NOT NULL
              AND base64_str <> ''
            ORDER BY id
            LIMIT %s
        """

        with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, (last_id, batch_size))
            return cursor.fetchall()

    def fetch_base64(self, media_id):
        query = """
            SELECT base64_str
            FROM chatbot_storymedia
            WHERE id = %s
              AND base64_str IS NOT NULL
              AND base64_str <> ''
        """

        with self.connection.cursor() as cursor:
            cursor.execute(query, (media_id,))
            row = cursor.fetchone()

            if not row:
                return None

            return row[0]

    def clear_base64(self, ids):
        """
        Clear Base64 only for verified IDs.
        """

        if not ids:
            return 0

        query = """
            UPDATE chatbot_storymedia
            SET
                base64_str = NULL,
                updated_at = NOW()
            WHERE id = ANY(%s)
              AND base64_str IS NOT NULL
              AND base64_str <> ''
        """

        with self.connection.cursor() as cursor:
            cursor.execute(query, (ids,))
            updated = cursor.rowcount

        self.connection.commit()

        return updated

    def rollback(self):
        if self.connection:
            self.connection.rollback()

    def read_statistics(self):
        query = """
            SELECT
                COUNT(*) AS total_rows,

                COUNT(*) FILTER (
                    WHERE base64_str IS NOT NULL
                      AND base64_str <> ''
                ) AS rows_with_base64,

                COUNT(*) FILTER (
                    WHERE
                        (file IS NOT NULL AND file <> '')
                        OR
                        (file_url IS NOT NULL AND file_url <> '')
                ) AS rows_with_file,

                COUNT(*) FILTER (
                    WHERE
                        base64_str IS NOT NULL
                        AND base64_str <> ''
                        AND
                        (
                            (file IS NOT NULL AND file <> '')
                            OR
                            (file_url IS NOT NULL AND file_url <> '')
                        )
                ) AS base64_with_file,

                COUNT(*) FILTER (
                    WHERE
                        base64_str IS NOT NULL
                        AND base64_str <> ''
                        AND
                        (file IS NULL OR file = '')
                        AND
                        (file_url IS NULL OR file_url = '')
                ) AS base64_without_file,

                COALESCE(
                    SUM(pg_column_size(base64_str))
                    FILTER (
                        WHERE base64_str IS NOT NULL
                          AND base64_str <> ''
                    ),
                    0
                ) AS base64_bytes

            FROM chatbot_storymedia
        """

        with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query)
            return cursor.fetchone()


# ============================================================
# MEDIA CHECKER
# ============================================================

class MediaChecker:
    def __init__(self, timeout=15):
        self.timeout = timeout

        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": "MITRA-StoryMedia-Cleanup/1.0",
            }
        )

    @staticmethod
    def normalize_path(value):
        if not value:
            return None

        value = str(value).strip()

        if not value:
            return None

        return value

    def build_url_from_file(self, file_path):
        file_path = self.normalize_path(file_path)

        if not file_path:
            return None

        # Absolute URL
        if file_path.startswith("http://") or file_path.startswith("https://"):
            return file_path

        # Remove leading slash
        file_path = file_path.lstrip("/")

        return f"{S3_MEDIA_URL}/{file_path}"

    def build_url_from_file_url(self, file_url):
        file_url = self.normalize_path(file_url)

        if not file_url:
            return None

        # Absolute URL
        if file_url.startswith("http://") or file_url.startswith("https://"):
            return file_url

        file_url = file_url.lstrip("/")

        return f"{S3_MEDIA_URL}/{file_url}"

    def get_candidate_urls(self, row):
        """
        Build URLs from both file and file_url.

        We intentionally check both because one may be stale/broken
        while the other points to the valid remote object.
        """

        candidates = []

        file_path = row.get("file")
        file_url = row.get("file_url")

        url_from_file = self.build_url_from_file(file_path)

        if url_from_file:
            candidates.append(
                {
                    "column": "file",
                    "url": url_from_file,
                }
            )

        url_from_file_url = self.build_url_from_file_url(file_url)

        if url_from_file_url:
            if not any(
                item["url"] == url_from_file_url
                for item in candidates
            ):
                candidates.append(
                    {
                        "column": "file_url",
                        "url": url_from_file_url,
                    }
                )

        return candidates

    def check_head(self, url):
        """
        Check object existence and size using HEAD.
        """

        try:
            response = self.session.head(
                url,
                timeout=self.timeout,
                allow_redirects=True,
            )

            if response.status_code == 200:
                content_length = response.headers.get("Content-Length")

                if content_length is not None:
                    try:
                        content_length = int(content_length)
                    except ValueError:
                        content_length = None

                return {
                    "exists": True,
                    "size": content_length,
                    "status_code": response.status_code,
                    "method": "HEAD",
                    "error": None,
                }

            if response.status_code == 404:
                return {
                    "exists": False,
                    "size": None,
                    "status_code": 404,
                    "method": "HEAD",
                    "error": None,
                }

            return {
                "exists": False,
                "size": None,
                "status_code": response.status_code,
                "method": "HEAD",
                "error": f"HTTP {response.status_code}",
            }

        except requests.RequestException as exc:
            return {
                "exists": False,
                "size": None,
                "status_code": None,
                "method": "HEAD",
                "error": str(exc),
            }

    def check_range_get(self, url):
        """
        Fallback check using:
            Range: bytes=0-0

        CloudFront/S3 normally returns:
            Content-Range: bytes 0-0/TOTAL_SIZE

        or Content-Length when the server returns 200.
        """

        try:
            response = self.session.get(
                url,
                headers={
                    "Range": "bytes=0-0",
                },
                timeout=self.timeout,
                allow_redirects=True,
                stream=True,
            )

            if response.status_code not in (200, 206):
                return {
                    "exists": False,
                    "size": None,
                    "status_code": response.status_code,
                    "method": "RANGE_GET",
                    "error": (
                        None
                        if response.status_code == 404
                        else f"HTTP {response.status_code}"
                    ),
                }

            total_size = None

            content_range = response.headers.get("Content-Range")

            if content_range:
                # Example:
                # bytes 0-0/619811
                if "/" in content_range:
                    total_part = content_range.split("/")[-1]

                    if total_part != "*":
                        try:
                            total_size = int(total_part)
                        except ValueError:
                            total_size = None

            if total_size is None:
                content_length = response.headers.get("Content-Length")

                if content_length is not None:
                    try:
                        total_size = int(content_length)
                    except ValueError:
                        total_size = None

            response.close()

            return {
                "exists": True,
                "size": total_size,
                "status_code": response.status_code,
                "method": "RANGE_GET",
                "error": None,
            }

        except requests.RequestException as exc:
            return {
                "exists": False,
                "size": None,
                "status_code": None,
                "method": "RANGE_GET",
                "error": str(exc),
            }

    def check_url(self, url):
        """
        HEAD first.
        If HEAD doesn't provide usable information,
        fallback to Range GET.
        """

        head_result = self.check_head(url)

        if head_result["exists"] and head_result["size"] is not None:
            return head_result

        range_result = self.check_range_get(url)

        if range_result["exists"]:
            return range_result

        # Preserve useful error information
        if head_result.get("error"):
            range_error = range_result.get("error")

            if range_error:
                combined_error = (
                    f"HEAD: {head_result['error']}; "
                    f"RANGE_GET: {range_error}"
                )
            else:
                combined_error = head_result["error"]
        else:
            combined_error = range_result.get("error")

        return {
            "exists": False,
            "size": None,
            "status_code": range_result.get(
                "status_code"
            ) or head_result.get("status_code"),
            "method": "HEAD+RANGE_GET",
            "error": combined_error,
        }

    def find_existing_object(self, row):
        """
        Try every available URL.

        A failed URL must NOT stop checking the other URL.
        """

        candidates = self.get_candidate_urls(row)

        if not candidates:
            return {
                "status": "no_file",
                "url": None,
                "source": None,
                "size": None,
                "error": "No file or file_url",
                "attempts": [],
            }

        attempts = []
        errors = []

        for candidate in candidates:
            url = candidate["url"]

            logger.info(
                "Checking remote object: id=%s source=%s url=%s",
                row["id"],
                candidate["column"],
                url,
            )

            result = self.check_url(url)

            attempt = {
                "source": candidate["column"],
                "url": url,
                "exists": result.get("exists"),
                "size": result.get("size"),
                "status_code": result.get("status_code"),
                "method": result.get("method"),
                "error": result.get("error"),
            }

            attempts.append(attempt)

            if result["exists"]:
                return {
                    "status": "found",
                    "url": url,
                    "source": candidate["column"],
                    "size": result["size"],
                    "error": None,
                    "attempts": attempts,
                }

            if result.get("error"):
                errors.append(
                    f"{candidate['column']}: {result['error']}"
                )

        # No URL worked.
        if errors:
            return {
                "status": "error",
                "url": None,
                "source": None,
                "size": None,
                "error": "; ".join(errors),
                "attempts": attempts,
            }

        return {
            "status": "missing",
            "url": None,
            "source": None,
            "size": None,
            "error": None,
            "attempts": attempts,
        }


# ============================================================
# BASE64 HELPERS
# ============================================================

def clean_base64(value):
    """
    Remove:
      data:application/pdf;base64,
      whitespace
      newlines
    """

    if value is None:
        return ""

    value = str(value).strip()

    # Handle data URI:
    #
    # data:application/pdf;base64,JVBERi0x...
    #
    if value.startswith("data:") and "," in value:
        value = value.split(",", 1)[1]

    # Remove whitespace/newlines.
    value = "".join(value.split())

    return value


def get_decoded_base64_size(value):
    """
    Strict Base64 validation and actual decoded binary size.
    """

    cleaned = clean_base64(value)

    if not cleaned:
        raise ValueError("Empty Base64 value")

    try:
        decoded = base64.b64decode(
            cleaned,
            validate=True,
        )

        return len(decoded)

    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            f"Invalid Base64: {exc}"
        ) from exc


# ============================================================
# CLEANER
# ============================================================

class StoryMediaCleaner:
    def __init__(
        self,
        db,
        media_checker,
        dry_run=False,
        delay=0,
    ):
        self.db = db
        self.media_checker = media_checker
        self.dry_run = dry_run
        self.delay = delay

        self.results = []

        # Grouped IDs for final JSON output.
        self.id_groups = {
            "cleared_ids": [],
            "failed_ids": [],
            "size_mismatch_ids": [],
            "remote_missing_ids": [],
            "invalid_base64_ids": [],
            "no_file_ids": [],
            "remote_error_ids": [],
        }

        self.stats = {
            "rows_scanned": 0,
            "rows_with_file": 0,
            "rows_without_file": 0,
            "remote_found": 0,
            "remote_missing": 0,
            "remote_errors": 0,
            "base64_invalid": 0,
            "size_verified": 0,
            "size_mismatch": 0,
            "rows_cleared": 0,
            "bytes_cleared": 0,
            "errors": 0,
        }

    def add_result(
        self,
        media_id,
        status,
        reason,
        **details,
    ):
        """
        Add detailed result and update grouped ID lists.
        """

        result = {
            "id": media_id,
            "status": status,
            "reason": reason,
            **details,
        }

        self.results.append(result)

        # IDs successfully cleared, or IDs that would be cleared
        # during dry-run.
        if status in (
            "cleared",
            "verified",
        ):
            self.id_groups["cleared_ids"].append(media_id)

        # Specific failure categories.
        if reason == "size_mismatch":
            self.id_groups["size_mismatch_ids"].append(media_id)

        elif reason == "invalid_base64":
            self.id_groups["invalid_base64_ids"].append(media_id)

        elif reason == "no_file_or_file_url":
            self.id_groups["no_file_ids"].append(media_id)

        elif reason == "remote_missing":
            self.id_groups["remote_missing_ids"].append(media_id)

        elif reason in (
            "remote_error",
            "all_urls_failed",
        ):
            self.id_groups["remote_error_ids"].append(media_id)

        # Any kept/non-cleared row is considered failed.
        if status == "kept":
            self.id_groups["failed_ids"].append(media_id)

    def process_row(self, row):
        media_id = row["id"]

        self.stats["rows_scanned"] += 1

        has_file = bool(
            row.get("file")
            and str(row.get("file")).strip()
        )

        has_file_url = bool(
            row.get("file_url")
            and str(row.get("file_url")).strip()
        )

        if has_file or has_file_url:
            self.stats["rows_with_file"] += 1
        else:
            self.stats["rows_without_file"] += 1

        # --------------------------------------------------------
        # 1. Check file/file_url
        # --------------------------------------------------------

        if not has_file and not has_file_url:
            logger.warning(
                "id=%s -> no file or file_url. Keeping Base64.",
                media_id,
            )

            self.add_result(
                media_id,
                "kept",
                "no_file_or_file_url",
            )

            return None

        # --------------------------------------------------------
        # 2. Find remote object
        # --------------------------------------------------------

        remote = self.media_checker.find_existing_object(row)

        if remote["status"] == "missing":
            self.stats["remote_missing"] += 1

            logger.warning(
                "id=%s -> remote object not found. Keeping Base64.",
                media_id,
            )

            self.add_result(
                media_id,
                "kept",
                "remote_missing",
                attempts=remote.get("attempts", []),
            )

            return None

        if remote["status"] == "error":
            self.stats["remote_errors"] += 1
            self.stats["errors"] += 1

            logger.error(
                "id=%s -> remote check failed: %s",
                media_id,
                remote.get("error"),
            )

            self.add_result(
                media_id,
                "kept",
                "remote_error",
                error=remote.get("error"),
                attempts=remote.get("attempts", []),
            )

            return None

        self.stats["remote_found"] += 1

        remote_size = remote.get("size")

        if remote_size is None:
            self.stats["remote_errors"] += 1
            self.stats["errors"] += 1

            logger.error(
                "id=%s -> remote object exists but size unavailable.",
                media_id,
            )

            self.add_result(
                media_id,
                "kept",
                "remote_error",
                error="Remote size unavailable",
                url=remote.get("url"),
                source=remote.get("source"),
            )

            return None

        # --------------------------------------------------------
        # 3. Fetch Base64
        # --------------------------------------------------------

        try:
            base64_value = self.db.fetch_base64(media_id)

            if not base64_value:
                logger.warning(
                    "id=%s -> Base64 no longer exists. Skipping.",
                    media_id,
                )

                self.add_result(
                    media_id,
                    "kept",
                    "base64_missing",
                )

                return None

        except Exception as exc:
            self.stats["errors"] += 1

            logger.exception(
                "id=%s -> failed to fetch Base64.",
                media_id,
            )

            self.add_result(
                media_id,
                "kept",
                "database_error",
                error=str(exc),
            )

            return None

        # --------------------------------------------------------
        # 4. Decode Base64 and calculate binary size
        # --------------------------------------------------------

        try:
            decoded_size = get_decoded_base64_size(
                base64_value
            )

        except ValueError as exc:
            self.stats["base64_invalid"] += 1
            self.stats["errors"] += 1

            logger.error(
                "id=%s -> invalid Base64: %s",
                media_id,
                exc,
            )

            self.add_result(
                media_id,
                "kept",
                "invalid_base64",
                error=str(exc),
                url=remote.get("url"),
                remote_size=remote_size,
            )

            return None

        # --------------------------------------------------------
        # 5. Compare sizes
        # --------------------------------------------------------

        logger.info(
            "id=%s -> Base64 decoded size=%s bytes, "
            "remote size=%s bytes",
            media_id,
            decoded_size,
            remote_size,
        )

        if decoded_size != remote_size:
            self.stats["size_mismatch"] += 1

            logger.warning(
                "id=%s -> SIZE MISMATCH. Keeping Base64.",
                media_id,
            )

            self.add_result(
                media_id,
                "kept",
                "size_mismatch",
                base64_decoded_size=decoded_size,
                remote_size=remote_size,
                url=remote.get("url"),
                source=remote.get("source"),
            )

            return None

        # --------------------------------------------------------
        # 6. Size verified
        # --------------------------------------------------------

        self.stats["size_verified"] += 1

        logger.info(
            "id=%s -> SIZE VERIFIED.",
            media_id,
        )

        # --------------------------------------------------------
        # DRY RUN
        # --------------------------------------------------------

        if self.dry_run:
            logger.info(
                "id=%s -> DRY RUN. Would clear Base64.",
                media_id,
            )

            self.add_result(
                media_id,
                "verified",
                "size_verified",
                base64_decoded_size=decoded_size,
                remote_size=remote_size,
                url=remote.get("url"),
                source=remote.get("source"),
                dry_run=True,
            )

            return {
                "id": media_id,
                "bytes": decoded_size,
            }

        # --------------------------------------------------------
        # REAL RUN
        #
        # Actual DB clearing is handled in run().
        # We return the verified row here.
        # --------------------------------------------------------

        return {
            "id": media_id,
            "bytes": decoded_size,
            "remote_size": remote_size,
            "url": remote.get("url"),
            "source": remote.get("source"),
        }

    def run(self, limit=None, batch_size=50):
        last_id = 0
        verified_for_clear = []

        while True:
            if limit is not None:
                remaining = limit - self.stats["rows_scanned"]

                if remaining <= 0:
                    break

                current_batch_size = min(
                    batch_size,
                    remaining,
                )
            else:
                current_batch_size = batch_size

            rows = self.db.fetch_batch(
                last_id,
                current_batch_size,
            )

            if not rows:
                break

            logger.info(
                "Processing batch: %s rows",
                len(rows),
            )

            verified_for_clear = []

            for row in rows:
                last_id = row["id"]

                try:
                    result = self.process_row(row)

                    if result and not self.dry_run:
                        verified_for_clear.append(result)

                    elif result and self.dry_run:
                        self.stats["rows_cleared"] += 1
                        self.stats["bytes_cleared"] += result[
                            "bytes"
                        ]

                except Exception as exc:
                    self.stats["errors"] += 1

                    logger.exception(
                        "Unexpected error processing id=%s",
                        row["id"],
                    )

                    self.add_result(
                        row["id"],
                        "kept",
                        "unexpected_error",
                        error=str(exc),
                    )

                if self.delay:
                    time.sleep(self.delay)

            # ----------------------------------------------------
            # Clear verified IDs in DB
            # ----------------------------------------------------

            if not self.dry_run and verified_for_clear:
                verified_ids = [
                    item["id"]
                    for item in verified_for_clear
                ]

                try:
                    updated_count = self.db.clear_base64(
                        verified_ids
                    )

                    logger.info(
                        "Cleared Base64 for %s rows.",
                        updated_count,
                    )

                    # IMPORTANT:
                    # Only mark IDs as cleared AFTER successful
                    # database UPDATE + COMMIT.
                    for item in verified_for_clear:
                        media_id = item["id"]

                        # In case the UPDATE matched fewer rows,
                        # we conservatively only mark all returned
                        # verified IDs as cleared if the count
                        # matches the expected count.
                        if updated_count == len(verified_ids):
                            self.stats["rows_cleared"] += 1
                            self.stats["bytes_cleared"] += item[
                                "bytes"
                            ]

                            self.add_result(
                                media_id,
                                "cleared",
                                "size_verified",
                                base64_decoded_size=item[
                                    "bytes"
                                ],
                                remote_size=item[
                                    "remote_size"
                                ],
                                url=item["url"],
                                source=item["source"],
                                dry_run=False,
                            )

                        else:
                            # Conservative handling if DB updated
                            # fewer rows than expected.
                            self.add_result(
                                media_id,
                                "kept",
                                "database_update_count_mismatch",
                                expected_count=len(
                                    verified_ids
                                ),
                                updated_count=updated_count,
                            )

                except Exception as exc:
                    self.db.rollback()

                    self.stats["errors"] += 1

                    logger.exception(
                        "Failed to clear verified Base64 IDs."
                    )

                    for item in verified_for_clear:
                        self.add_result(
                            item["id"],
                            "kept",
                            "database_update_error",
                            error=str(exc),
                        )

            # Stop after processing requested limit.
            if limit is not None:
                if self.stats["rows_scanned"] >= limit:
                    break

        return self.stats


# ============================================================
# SAVE RESULTS
# ============================================================

def save_results(
    output_file,
    stats,
    results,
    id_groups,
):
    if not output_file:
        return

    data = {
        "summary": stats,

        "ids": {
            key: sorted(set(value))
            for key, value in id_groups.items()
        },

        "results": results,
    }

    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            indent=2,
            default=str,
        )

    logger.info(
        "Results written to %s",
        output_file,
    )


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Verify chatbot_storymedia Base64 against "
            "remote CloudFront/S3 objects and clear "
            "verified Base64 values."
        )
    )

    parser.add_argument(
        "--mode",
        choices=["read", "write"],
        default="read",
        help="read = scan only, write = allow DB updates",
    )

    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required for write mode",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify but do not modify the database",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of rows to process",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of rows processed per batch",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="HTTP request timeout in seconds",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0,
        help="Delay between rows in seconds",
    )

    parser.add_argument(
        "--output-file",
        default="storymedia_cleanup_results.json",
        help="JSON output file",
    )

    return parser.parse_args()


# ============================================================
# MAIN
# ============================================================

def main():
    args = parse_args()

    # --------------------------------------------------------
    # Validate environment
    # --------------------------------------------------------

    required_env = {
        "DATABASE_HOST": DB_HOST,
        "DATABASE_PORT": DB_PORT,
        "DATABASE_NAME": DB_NAME,
        "DATABASE_USER": DB_USER,
        "DATABASE_PASSWORD": DB_PASSWORD,
    }

    missing = [
        key
        for key, value in required_env.items()
        if value is None or value == ""
    ]

    if missing:
        logger.error(
            "Missing required environment variables: %s",
            ", ".join(missing),
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Validate mode
    # --------------------------------------------------------

    if args.mode == "write":
        if not args.confirm:
            logger.error(
                "Write mode requires --confirm."
            )

            logger.error(
                "Example:"
            )

            logger.error(
                "python sync_storymedia_base64_to_s3.py "
                "--mode write --confirm --dry-run"
            )

            sys.exit(1)

    # --------------------------------------------------------
    # Determine actual dry-run behavior
    # --------------------------------------------------------

    dry_run = args.dry_run

    if args.mode == "read":
        dry_run = True

    # --------------------------------------------------------
    # Print configuration
    # --------------------------------------------------------

    logger.info("==============================================")
    logger.info("StoryMedia Base64 Cleanup")
    logger.info("==============================================")

    logger.info(
        "Database: %s:%s/%s",
        DB_HOST,
        DB_PORT,
        DB_NAME,
    )

    logger.info(
        "Media URL: %s",
        S3_MEDIA_URL,
    )

    logger.info(
        "Mode: %s",
        args.mode,
    )

    logger.info(
        "Dry run: %s",
        dry_run,
    )

    if args.limit:
        logger.info(
            "Limit: %s rows",
            args.limit,
        )

    logger.info(
        "Batch size: %s",
        args.batch_size,
    )

    logger.info("==============================================")

    # --------------------------------------------------------
    # Connect
    # --------------------------------------------------------

    db = Database()

    try:
        db.connect()

        # ----------------------------------------------------
        # Before statistics
        # ----------------------------------------------------

        before_stats = db.read_statistics()

        logger.info("Database statistics before cleanup:")

        logger.info(
            "Total rows: %s",
            before_stats["total_rows"],
        )

        logger.info(
            "Rows with Base64: %s",
            before_stats["rows_with_base64"],
        )

        logger.info(
            "Rows with file/file_url: %s",
            before_stats["rows_with_file"],
        )

        logger.info(
            "Base64 without file: %s",
            before_stats["base64_without_file"],
        )

        logger.info(
            "Base64 storage: %.2f MB",
            int(before_stats["base64_bytes"])
            / 1024
            / 1024,
        )

        # ----------------------------------------------------
        # Cleaner
        # ----------------------------------------------------

        media_checker = MediaChecker(
            timeout=args.timeout,
        )

        cleaner = StoryMediaCleaner(
            db=db,
            media_checker=media_checker,
            dry_run=dry_run,
            delay=args.delay,
        )

        # ----------------------------------------------------
        # Run
        # ----------------------------------------------------

        stats = cleaner.run(
            limit=args.limit,
            batch_size=args.batch_size,
        )

        # ----------------------------------------------------
        # After statistics
        # ----------------------------------------------------

        after_stats = db.read_statistics()

        logger.info("")
        logger.info("==============================================")
        logger.info("Cleanup Summary")
        logger.info("==============================================")

        for key, value in stats.items():
            logger.info(
                "%s: %s",
                key,
                value,
            )

        logger.info("")
        logger.info("Database statistics after cleanup:")

        logger.info(
            "Rows with Base64: %s",
            after_stats["rows_with_base64"],
        )

        logger.info(
            "Base64 storage: %.2f MB",
            int(after_stats["base64_bytes"])
            / 1024
            / 1024,
        )

        # ----------------------------------------------------
        # Grouped IDs
        # ----------------------------------------------------

        logger.info("")
        logger.info("Grouped IDs:")
        logger.info(
            "cleared_ids: %s",
            len(cleaner.id_groups["cleared_ids"]),
        )

        logger.info(
            "failed_ids: %s",
            len(cleaner.id_groups["failed_ids"]),
        )

        logger.info(
            "size_mismatch_ids: %s",
            len(cleaner.id_groups["size_mismatch_ids"]),
        )

        logger.info(
            "remote_missing_ids: %s",
            len(cleaner.id_groups["remote_missing_ids"]),
        )

        logger.info(
            "invalid_base64_ids: %s",
            len(cleaner.id_groups["invalid_base64_ids"]),
        )

        logger.info(
            "no_file_ids: %s",
            len(cleaner.id_groups["no_file_ids"]),
        )

        logger.info(
            "remote_error_ids: %s",
            len(cleaner.id_groups["remote_error_ids"]),
        )

        # ----------------------------------------------------
        # Save JSON
        # ----------------------------------------------------

        save_results(
            args.output_file,
            stats,
            cleaner.results,
            cleaner.id_groups,
        )

        logger.info("")
        logger.info(
            "Output file: %s",
            args.output_file,
        )

        logger.info("==============================================")

    except KeyboardInterrupt:
        logger.warning(
            "Process interrupted by user."
        )

        try:
            db.rollback()
        except Exception:
            pass

        sys.exit(130)

    except Exception:
        logger.exception(
            "Fatal error."
        )

        try:
            db.rollback()
        except Exception:
            pass

        sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
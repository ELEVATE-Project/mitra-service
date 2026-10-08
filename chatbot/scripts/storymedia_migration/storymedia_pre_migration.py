#!/usr/bin/env python3

"""
Pre-migration validation/backfill for chatbot_storymedia.

Purpose:
    Before clearing base64_str, make sure every row with base64_str has a
    valid S3 object and both `file` / `file_url` references are available.

Rules:
    1. Only process rows where base64_str IS NOT NULL.
    2. If both file and file_url exist:
         - Verify the referenced S3 object against base64_str.
         - Do not update anything if valid.
    3. If file exists but file_url is missing:
         - Verify `file` in S3 against base64_str.
         - Generate file_url from the same S3 path.
         - Update only file_url.
    4. If file_url exists but file is missing:
         - Verify file_url in S3 against base64_str.
         - Derive file from the same S3 path.
         - Update only file.
    5. If both file and file_url are missing:
         - Decode base64_str.
         - Upload to S3.
         - Populate both file and file_url.
    6. NEVER modify base64_str.
    7. Every update is recorded in an audit CSV.

Environment variables:

PostgreSQL:
    DATABASE_HOST
    DATABASE_NAME
    DATABASE_USER
    DATABASE_PASSWORD
    DATABASE_PORT       (default: 5432)

S3:
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    AWS_REGION          (optional)
    S3_BUCKET           (default: mohini-static.shikshalokam.org)
    S3_BASE_URL         (example: https://qa-mohini-static.shikshalokam.org/)
    S3_MEDIA_URL        (example: https://qa-mohini-static.shikshalokam.org/)

Usage:

    Dry run:
        python3 storymedia_pre_migration.py --dry-run

    Process:
        python3 storymedia_pre_migration.py --confirm

    Limit:
        python3 storymedia_pre_migration.py --dry-run --limit 100
"""

#!/usr/bin/env python3

import argparse
import base64
import binascii
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Optional, Dict, Any

import boto3
import psycopg2
import requests
from dotenv import load_dotenv


# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv()


# ============================================================
# CONFIGURATION
# ============================================================

DB_HOST = os.getenv("DATABASE_HOST", "localhost")
DB_PORT = int(os.getenv("DATABASE_PORT", "5400"))
DB_NAME = os.getenv("DATABASE_NAME", "qa_backup")
DB_USER = os.getenv("DATABASE_USER", "admin")
DB_PASSWORD = os.getenv("DATABASE_PASSWORD", "")

S3_BUCKET_NAME = os.getenv(
    "S3_BUCKET_NAME",
    "mohini-static.shikshalokam.org",
)

S3_BASE_URL = os.getenv(
    "S3_BASE_URL",
    "https://qa-mohini-static.shikshalokam.org",
)

S3_MEDIA_URL = os.getenv(
    "S3_MEDIA_URL",
    "https://qa-mohini-static.shikshalokam.org",
)


# Normalize exactly like cleanup script
S3_BASE_URL = (
    S3_BASE_URL
    .strip()
    .strip('"')
    .strip("'")
    .rstrip("/")
)

S3_MEDIA_URL = (
    S3_MEDIA_URL
    .strip()
    .strip('"')
    .strip("'")
    .rstrip("/")
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
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

        logger.info(
            "Database connected successfully"
        )

    def close(self):

        if self.connection:
            self.connection.close()
            logger.info(
                "Database connection closed"
            )

    def fetch_batch(
        self,
        last_id: int,
        batch_size: int,
        limit: Optional[int] = None,
    ):

        fetch_size = batch_size

        if limit is not None:
            fetch_size = min(
                batch_size,
                limit,
            )

        query = """
            SELECT
                id,
                base64_str,
                file,
                file_url
            FROM chatbot_storymedia
            WHERE id > %s
              AND base64_str IS NOT NULL
              AND base64_str <> ''
            ORDER BY id
            LIMIT %s
        """

        with self.connection.cursor() as cursor:

            cursor.execute(
                query,
                (
                    last_id,
                    fetch_size,
                ),
            )

            return cursor.fetchall()

    def update_file(
        self,
        story_id: int,
        file_path: str,
    ):

        query = """
            UPDATE chatbot_storymedia
            SET file = %s
            WHERE id = %s
        """

        with self.connection.cursor() as cursor:

            cursor.execute(
                query,
                (
                    file_path,
                    story_id,
                ),
            )

        self.connection.commit()

    def update_file_url(
        self,
        story_id: int,
        file_url: str,
    ):

        query = """
            UPDATE chatbot_storymedia
            SET file_url = %s
            WHERE id = %s
        """

        with self.connection.cursor() as cursor:

            cursor.execute(
                query,
                (
                    file_url,
                    story_id,
                ),
            )

        self.connection.commit()

    def update_file_and_url(
        self,
        story_id: int,
        file_path: str,
        file_url: str,
    ):

        query = """
            UPDATE chatbot_storymedia
            SET
                file = %s,
                file_url = %s
            WHERE id = %s
        """

        with self.connection.cursor() as cursor:

            cursor.execute(
                query,
                (
                    file_path,
                    file_url,
                    story_id,
                ),
            )

        self.connection.commit()


# ============================================================
# MEDIA / S3
# ============================================================

class MediaManager:

    def __init__(
        self,
        timeout: int = 30,
    ):

        self.timeout = timeout

        self.s3 = boto3.client("s3")

        logger.info(
            "Found credentials in environment variables."
        )

    @staticmethod
    def normalize_path(value):

        if value is None:
            return None

        value = str(value).strip()

        if not value:
            return None

        if value.lower() in (
            "null",
            "none",
            "undefined",
        ):
            return None

        return value

    def build_url_from_file(
        self,
        file_path,
    ):

        file_path = self.normalize_path(
            file_path
        )

        if not file_path:
            return None

        if (
            file_path.startswith("http://")
            or file_path.startswith("https://")
        ):
            return file_path

        file_path = file_path.lstrip("/")

        return f"{S3_MEDIA_URL}/{file_path}"

    def build_url_from_file_url(
        self,
        file_url,
    ):

        file_url = self.normalize_path(
            file_url
        )

        if not file_url:
            return None

        if (
            file_url.startswith("http://")
            or file_url.startswith("https://")
        ):
            return file_url

        file_url = file_url.lstrip("/")

        return f"{S3_MEDIA_URL}/{file_url}"

    def url_to_key(
        self,
        url: str,
    ) -> Optional[str]:

        if not url:
            return None

        url = url.strip()

        media_base = (
            S3_MEDIA_URL.rstrip("/")
            + "/"
        )

        if url.startswith(media_base):

            return url[
                len(media_base):
            ].lstrip("/")

        base_url = (
            S3_BASE_URL.rstrip("/")
            + "/"
        )

        if url.startswith(base_url):

            return url[
                len(base_url):
            ].lstrip("/")

        return None

    def get_remote_size(
        self,
        url: str,
    ) -> Dict[str, Any]:

        result = {
            "exists": False,
            "size": None,
            "status_code": None,
            "error": None,
        }

        # ----------------------------------------------------
        # HEAD request
        # ----------------------------------------------------

        try:

            response = requests.head(
                url,
                timeout=self.timeout,
                allow_redirects=True,
            )

            result["status_code"] = (
                response.status_code
            )

            if response.status_code == 200:

                content_length = (
                    response.headers.get(
                        "Content-Length"
                    )
                )

                if content_length:

                    try:

                        result["size"] = int(
                            content_length
                        )

                    except ValueError:
                        pass

                result["exists"] = True

                if result["size"] is not None:
                    return result

        except requests.RequestException as exc:

            result["error"] = str(exc)

        # ----------------------------------------------------
        # Range GET fallback
        # ----------------------------------------------------

        try:

            response = requests.get(
                url,
                headers={
                    "Range": "bytes=0-0"
                },
                timeout=self.timeout,
                allow_redirects=True,
                stream=True,
            )

            result["status_code"] = (
                response.status_code
            )

            if response.status_code in (
                200,
                206,
            ):

                result["exists"] = True

                content_range = (
                    response.headers.get(
                        "Content-Range"
                    )
                )

                if (
                    content_range
                    and "/" in content_range
                ):

                    total = (
                        content_range
                        .split("/")[-1]
                    )

                    if total.isdigit():

                        result["size"] = int(
                            total
                        )

                if result["size"] is None:

                    content_length = (
                        response.headers.get(
                            "Content-Length"
                        )
                    )

                    if content_length:

                        try:

                            result["size"] = int(
                                content_length
                            )

                        except ValueError:
                            pass

        except requests.RequestException as exc:

            result["error"] = str(exc)

        return result

    def verify_url_against_base64(
        self,
        url: str,
        base64_value: str,
    ) -> Dict[str, Any]:

        result = {
            "url": url,
            "exists": False,
            "remote_size": None,
            "base64_size": None,
            "size_match": False,
            "error": None,
        }

        # ----------------------------------------------------
        # Decode Base64
        # ----------------------------------------------------

        try:

            decoded = base64.b64decode(
                base64_value,
                validate=True,
            )

            result["base64_size"] = len(
                decoded
            )

        except (
            binascii.Error,
            ValueError,
            TypeError,
        ) as exc:

            result["error"] = (
                f"Invalid Base64: {exc}"
            )

            return result

        # ----------------------------------------------------
        # Check remote object
        # ----------------------------------------------------

        remote = self.get_remote_size(
            url
        )

        result["exists"] = remote[
            "exists"
        ]

        result["remote_size"] = remote[
            "size"
        ]

        if not remote["exists"]:

            result["error"] = (
                remote.get("error")
                or (
                    f"HTTP status: "
                    f"{remote.get('status_code')}"
                )
            )

            return result

        if remote["size"] is None:

            result["error"] = (
                "Remote object exists but "
                "size could not be determined"
            )

            return result

        result["size_match"] = (
            remote["size"]
            == result["base64_size"]
        )

        if not result["size_match"]:

            result["error"] = (
                f"Size mismatch: "
                f"Base64="
                f"{result['base64_size']} "
                f"Remote="
                f"{remote['size']}"
            )

        return result

    def upload_base64(
        self,
        base64_value: str,
        key: str,
    ) -> int:

        try:

            data = base64.b64decode(
                base64_value,
                validate=True,
            )

        except (
            binascii.Error,
            ValueError,
            TypeError,
        ) as exc:

            raise ValueError(
                f"Invalid Base64: {exc}"
            )

        self.s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=data,
        )

        logger.info(
            "Uploaded %s bytes to "
            "s3://%s/%s",
            len(data),
            S3_BUCKET_NAME,
            key,
        )

        # ----------------------------------------------------
        # Verify S3 upload
        # ----------------------------------------------------

        response = self.s3.head_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
        )

        remote_size = response.get(
            "ContentLength"
        )

        if remote_size != len(data):

            raise RuntimeError(
                "S3 verification failed. "
                f"Expected={len(data)}, "
                f"Actual={remote_size}"
            )

        return len(data)


# ============================================================
# PRE-MIGRATION
# ============================================================

class PreMigration:

    def __init__(
        self,
        db: Database,
        media: MediaManager,
        dry_run: bool,
        delay: float = 0,
    ):

        self.db = db
        self.media = media
        self.dry_run = dry_run
        self.delay = delay

        # ----------------------------------------------------
        # Statistics
        # ----------------------------------------------------

        self.stats = {

            "processed": 0,
            "verified": 0,

            # Actual changes
            "updated_file": 0,
            "updated_file_url": 0,
            "updated_both": 0,
            "uploaded": 0,

            # Planned changes in read mode
            "would_update_file": 0,
            "would_update_file_url": 0,
            "would_update_both": 0,
            "would_upload": 0,

            # Problems
            "failed": 0,
            "invalid_base64": 0,
            "size_mismatch": 0,
            "remote_missing": 0,
            "conflicts": 0,
        }

        # ----------------------------------------------------
        # ID tracking
        # ----------------------------------------------------

        self.updated_ids = {

            # Actual changes
            "updated_file_ids": [],
            "updated_file_url_ids": [],
            "updated_both_ids": [],
            "uploaded_ids": [],

            # Planned changes
            "would_update_file_ids": [],
            "would_update_file_url_ids": [],
            "would_update_both_ids": [],
            "would_upload_ids": [],
        }

    @staticmethod
    def generate_s3_key(
        story_id: int,
    ) -> str:

        return (
            f"chatbot/storymedia/"
            f"{story_id}/"
            f"storymedia_{story_id}"
        )

    def process_row(
        self,
        row,
    ):

        (
            story_id,
            base64_value,
            file_path,
            file_url,
        ) = row

        self.stats["processed"] += 1

        file_path = (
            self.media.normalize_path(
                file_path
            )
        )

        file_url = (
            self.media.normalize_path(
                file_url
            )
        )

        # ====================================================
        # CASE 1:
        # FILE EXISTS
        # ====================================================

        if file_path:

            file_reference_url = (
                self.media.build_url_from_file(
                    file_path
                )
            )

            verification = (
                self.media.verify_url_against_base64(
                    file_reference_url,
                    base64_value,
                )
            )

            if not verification["exists"]:

                self.stats[
                    "remote_missing"
                ] += 1

                self.stats[
                    "failed"
                ] += 1

                logger.error(
                    "id=%s -> file exists but "
                    "remote object was not found: %s",
                    story_id,
                    file_reference_url,
                )

                return

            if not verification[
                "size_match"
            ]:

                error = (
                    verification.get(
                        "error"
                    )
                    or "Size mismatch"
                )

                if (
                    "Invalid Base64"
                    in error
                ):

                    self.stats[
                        "invalid_base64"
                    ] += 1

                else:

                    self.stats[
                        "size_mismatch"
                    ] += 1

                self.stats[
                    "failed"
                ] += 1

                logger.error(
                    "id=%s -> file verification "
                    "failed: %s",
                    story_id,
                    error,
                )

                return

            # ------------------------------------------------
            # File verified
            # ------------------------------------------------

            self.stats[
                "verified"
            ] += 1

            logger.info(
                "id=%s -> file verified: %s",
                story_id,
                file_reference_url,
            )

            # ------------------------------------------------
            # file_url missing
            # ------------------------------------------------

            if not file_url:

                generated_file_url = (
                    file_reference_url
                )

                if self.dry_run:

                    logger.info(
                        "id=%s -> file_url would "
                        "be updated to: %s",
                        story_id,
                        generated_file_url,
                    )

                    self.stats[
                        "would_update_file_url"
                    ] += 1

                    self.updated_ids[
                        "would_update_file_url_ids"
                    ].append(
                        story_id
                    )

                else:

                    try:

                        self.db.update_file_url(
                            story_id,
                            generated_file_url,
                        )

                        self.stats[
                            "updated_file_url"
                        ] += 1

                        self.updated_ids[
                            "updated_file_url_ids"
                        ].append(
                            story_id
                        )

                        logger.info(
                            "id=%s -> file_url "
                            "updated: %s",
                            story_id,
                            generated_file_url,
                        )

                    except Exception as exc:

                        self.stats[
                            "failed"
                        ] += 1

                        logger.exception(
                            "id=%s -> failed to "
                            "update file_url: %s",
                            story_id,
                            exc,
                        )

                return

            # ------------------------------------------------
            # Both exist
            # ------------------------------------------------

            file_url_reference = (
                self.media.build_url_from_file_url(
                    file_url
                )
            )

            second_verification = (
                self.media.verify_url_against_base64(
                    file_url_reference,
                    base64_value,
                )
            )

            if not second_verification[
                "exists"
            ]:

                self.stats[
                    "remote_missing"
                ] += 1

                self.stats[
                    "failed"
                ] += 1

                logger.error(
                    "id=%s -> file_url points "
                    "to missing object: %s",
                    story_id,
                    file_url_reference,
                )

                return

            if not second_verification[
                "size_match"
            ]:

                self.stats[
                    "size_mismatch"
                ] += 1

                self.stats[
                    "failed"
                ] += 1

                logger.error(
                    "id=%s -> file_url size mismatch: %s",
                    story_id,
                    second_verification.get(
                        "error"
                    ),
                )

                return

            # ------------------------------------------------
            # Ensure both references point to same key
            # ------------------------------------------------

            file_key = (
                self.media.url_to_key(
                    file_reference_url
                )
            )

            file_url_key = (
                self.media.url_to_key(
                    file_url_reference
                )
            )

            if (
                file_key
                and file_url_key
                and file_key != file_url_key
            ):

                self.stats[
                    "conflicts"
                ] += 1

                self.stats[
                    "failed"
                ] += 1

                logger.error(
                    "id=%s -> CONFLICT: file and "
                    "file_url point to different objects",
                    story_id,
                )

                logger.error(
                    "    file key     = %s",
                    file_key,
                )

                logger.error(
                    "    file_url key = %s",
                    file_url_key,
                )

                return

            logger.info(
                "id=%s -> file and file_url "
                "both verified",
                story_id,
            )

            return

        # ====================================================
        # CASE 2:
        # FILE MISSING, FILE_URL EXISTS
        # ====================================================

        if file_url:

            file_url_reference = (
                self.media.build_url_from_file_url(
                    file_url
                )
            )

            verification = (
                self.media.verify_url_against_base64(
                    file_url_reference,
                    base64_value,
                )
            )

            if not verification[
                "exists"
            ]:

                self.stats[
                    "remote_missing"
                ] += 1

                self.stats[
                    "failed"
                ] += 1

                logger.error(
                    "id=%s -> file_url exists "
                    "but remote object was not found: %s",
                    story_id,
                    file_url_reference,
                )

                return

            if not verification[
                "size_match"
            ]:

                self.stats[
                    "size_mismatch"
                ] += 1

                self.stats[
                    "failed"
                ] += 1

                logger.error(
                    "id=%s -> file_url "
                    "verification failed: %s",
                    story_id,
                    verification.get(
                        "error"
                    ),
                )

                return

            self.stats[
                "verified"
            ] += 1

            # ------------------------------------------------
            # Derive file from file_url
            # ------------------------------------------------

            key = (
                self.media.url_to_key(
                    file_url_reference
                )
            )

            if not key:

                self.stats[
                    "failed"
                ] += 1

                self.stats[
                    "conflicts"
                ] += 1

                logger.error(
                    "id=%s -> could not derive "
                    "S3 key from file_url: %s",
                    story_id,
                    file_url_reference,
                )

                return

            derived_file = "/" + key

            if self.dry_run:

                logger.info(
                    "id=%s -> file would "
                    "be updated to: %s",
                    story_id,
                    derived_file,
                )

                self.stats[
                    "would_update_file"
                ] += 1

                self.updated_ids[
                    "would_update_file_ids"
                ].append(
                    story_id
                )

            else:

                try:

                    self.db.update_file(
                        story_id,
                        derived_file,
                    )

                    self.stats[
                        "updated_file"
                    ] += 1

                    self.updated_ids[
                        "updated_file_ids"
                    ].append(
                        story_id
                    )

                    logger.info(
                        "id=%s -> file updated: %s",
                        story_id,
                        derived_file,
                    )

                except Exception as exc:

                    self.stats[
                        "failed"
                    ] += 1

                    logger.exception(
                        "id=%s -> failed to "
                        "update file: %s",
                        story_id,
                        exc,
                    )

            return

        # ====================================================
        # CASE 3:
        # BOTH FILE AND FILE_URL MISSING
        # ====================================================

        logger.warning(
            "id=%s -> both file and "
            "file_url are missing",
            story_id,
        )

        key = (
            self.generate_s3_key(
                story_id
            )
        )

        generated_file = "/" + key

        generated_file_url = (
            f"{S3_MEDIA_URL}/{key}"
        )

        # ----------------------------------------------------
        # READ MODE
        # ----------------------------------------------------

        if self.dry_run:

            logger.info(
                "id=%s -> would upload Base64 to: %s",
                story_id,
                generated_file_url,
            )

            logger.info(
                "id=%s -> file would "
                "be updated to: %s",
                story_id,
                generated_file,
            )

            logger.info(
                "id=%s -> file_url would "
                "be updated to: %s",
                story_id,
                generated_file_url,
            )

            self.stats[
                "would_upload"
            ] += 1

            self.stats[
                "would_update_both"
            ] += 1

            self.updated_ids[
                "would_upload_ids"
            ].append(
                story_id
            )

            self.updated_ids[
                "would_update_both_ids"
            ].append(
                story_id
            )

            return

        # ----------------------------------------------------
        # WRITE MODE
        # ----------------------------------------------------

        try:

            self.media.upload_base64(
                base64_value,
                key,
            )

            self.stats[
                "uploaded"
            ] += 1

            self.updated_ids[
                "uploaded_ids"
            ].append(
                story_id
            )

            self.db.update_file_and_url(
                story_id,
                generated_file,
                generated_file_url,
            )

            self.stats[
                "updated_both"
            ] += 1

            self.updated_ids[
                "updated_both_ids"
            ].append(
                story_id
            )

            logger.info(
                "id=%s -> uploaded and "
                "references updated",
                story_id,
            )

        except Exception as exc:

            self.stats[
                "failed"
            ] += 1

            logger.exception(
                "id=%s -> upload/update failed: %s",
                story_id,
                exc,
            )

    # ========================================================
    # RUN
    # ========================================================

    def run(
        self,
        batch_size: int,
        limit: Optional[int],
    ):

        last_id = 0
        total_processed = 0

        while True:

            remaining = None

            if limit is not None:

                remaining = (
                    limit
                    - total_processed
                )

                if remaining <= 0:
                    break

            rows = self.db.fetch_batch(
                last_id=last_id,
                batch_size=batch_size,
                limit=remaining,
            )

            if not rows:
                break

            first_id = rows[0][0]
            last_id = rows[-1][0]

            logger.info(
                "Processing batch: %s rows, "
                "id range %s -> %s",
                len(rows),
                first_id,
                last_id,
            )

            for row in rows:

                try:

                    self.process_row(row)

                except Exception as exc:

                    story_id = row[0]

                    self.stats[
                        "failed"
                    ] += 1

                    logger.exception(
                        "id=%s -> unexpected error: %s",
                        story_id,
                        exc,
                    )

                total_processed += 1

                if self.delay > 0:

                    time.sleep(
                        self.delay
                    )

            logger.info(
                "Progress: %s",
                self.stats,
            )

            if (
                limit is not None
                and total_processed >= limit
            ):
                break

        return self.stats


# ============================================================
# JSON REPORT
# ============================================================

def write_json_report(
    filename: str,
    stats: Dict[str, Any],
    ids: Dict[str, Any],
    mode: str,
    dry_run: bool,
):

    report = {

        "generated_at":
            datetime.utcnow().isoformat()
            + "Z",

        "mode": mode,

        "dry_run": dry_run,

        "stats": stats,

        "ids": ids,
    }

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            report,
            file,
            indent=2,
        )

    logger.info(
        "JSON report written: %s",
        filename,
    )


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Verify and repair chatbot_storymedia "
            "file/file_url references before "
            "Base64 cleanup."
        )
    )

    parser.add_argument(
        "--mode",
        choices=[
            "read",
            "write",
        ],
        default="read",
        help=(
            "read = verification/dry-run only, "
            "write = perform DB/S3 changes"
        ),
    )

    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Required for write mode"
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Maximum number of rows "
            "to process"
        ),
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help=(
            "Number of rows per batch"
        ),
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help=(
            "HTTP timeout in seconds"
        ),
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0,
        help=(
            "Delay between rows "
            "in seconds"
        ),
    )

    parser.add_argument(
        "--json-output",
        default=(
            "storymedia_pre_migration_results.json"
        ),
        help=(
            "JSON summary file"
        ),
    )

    return parser.parse_args()


# ============================================================
# MAIN
# ============================================================

def main():

    args = parse_args()

    # --------------------------------------------------------
    # Safety
    # --------------------------------------------------------

    if (
        args.mode == "write"
        and not args.confirm
    ):

        logger.error(
            "Write mode requires --confirm"
        )

        logger.error(
            "Example:"
        )

        logger.error(
            "python storymedia_pre_migration.py "
            "--mode write --confirm"
        )

        sys.exit(1)

    dry_run = (
        args.mode == "read"
    )

    # --------------------------------------------------------
    # Startup
    # --------------------------------------------------------

    logger.info(
        "Database: %s:%s/%s",
        DB_HOST,
        DB_PORT,
        DB_NAME,
    )

    logger.info(
        "S3 bucket: %s",
        S3_BUCKET_NAME,
    )

    logger.info(
        "S3 base URL: %s",
        S3_BASE_URL,
    )

    logger.info(
        "S3 media URL: %s",
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

    if dry_run:

        logger.info(
            "Database write operations: DISABLED"
        )

        logger.info(
            "S3 upload operations: DISABLED"
        )

    else:

        logger.warning(
            "DATABASE/S3 WRITE MODE ENABLED"
        )

        logger.warning(
            "Base64 values will NOT be deleted "
            "by this script."
        )

    # --------------------------------------------------------
    # Run
    # --------------------------------------------------------

    db = Database()

    try:

        db.connect()

        media = MediaManager(
            timeout=args.timeout
        )

        processor = PreMigration(
            db=db,
            media=media,
            dry_run=dry_run,
            delay=args.delay,
        )

        stats = processor.run(
            batch_size=args.batch_size,
            limit=args.limit,
        )

        # ----------------------------------------------------
        # JSON report
        # ----------------------------------------------------

        write_json_report(
            filename=args.json_output,
            stats=stats,
            ids=processor.updated_ids,
            mode=args.mode,
            dry_run=dry_run,
        )

        # ----------------------------------------------------
        # Final summary
        # ----------------------------------------------------

        logger.info("")
        logger.info(
            "=========================================="
        )
        logger.info(
            "FINAL SUMMARY"
        )
        logger.info(
            "=========================================="
        )

        for key, value in stats.items():

            logger.info(
                "%s: %s",
                key,
                value,
            )

        logger.info("")
        logger.info(
            "ID SUMMARY"
        )

        for key, value in (
            processor.updated_ids.items()
        ):

            logger.info(
                "%s: %s",
                key,
                value,
            )

        logger.info(
            "=========================================="
        )

        logger.info(
            "Base64 values were NOT deleted."
        )

    except KeyboardInterrupt:

        logger.warning(
            "Process interrupted by user."
        )

        sys.exit(130)

    except Exception as exc:

        logger.exception(
            "Fatal error: %s",
            exc,
        )

        sys.exit(1)

    finally:

        db.close()


if __name__ == "__main__":
    main()
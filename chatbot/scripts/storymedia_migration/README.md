# Storymedia Migration

This folder contains scripts to safely migrate and clean up Base64 media data from the `chatbot_storymedia` table.

## What we are doing

The migration is performed in two steps:

1. **Pre-Migration**

   * Verify that existing `file` / `file_url` references point to valid S3 media.
   * Verify the S3 media size matches the Base64 data.
   * Populate missing `file` or `file_url` references when required.
   * Generate a JSON report containing the processed IDs.
   * **Base64 data is NOT deleted in this step.**

2. **Base64 Cleanup**

   * Verify the media again against the Base64 data.
   * Clear `base64_str` only after successful verification.
   * Generate a report containing the IDs whose Base64 data was cleared.

---

## Navigate to the migration folder

```bash
cd /mitra-service/chatbot/scripts/storymedia_migration
```

---

## Step 1: Pre-Migration - Read / Verify

First run in read mode.

```bash
python storymedia_pre_migration.py \
  --mode read \
  --batch-size 100
```

For testing with a limited number of records:

```bash
python storymedia_pre_migration.py \
  --mode read \
  --limit 10 \
  --batch-size 10
```

Read mode does **not** update PostgreSQL or upload anything to S3.

Check the generated:

```text
storymedia_pre_migration_results.json
```

Review the `stats` and `ids` sections.

---

## Step 2: Pre-Migration - Write

After confirming the read-mode results, run write mode.

For a small test:

```bash
python storymedia_pre_migration.py \
  --mode write \
  --confirm \
  --limit 10 \
  --batch-size 10
```

After verifying the test results, run the complete migration:

```bash
python storymedia_pre_migration.py \
  --mode write \
  --confirm \
  --batch-size 100
```

### Important

The pre-migration script **does not delete `base64_str`**.

It only verifies and repairs the media references and, when required, uploads missing media to S3.

---

## Step 3: Base64 Cleanup

After the pre-migration is successfully completed and verified, run the Base64 cleanup script.

### Read / Verify Mode

First run:

```bash
python sync_storymedia_base64_to_s3.py \
  --mode read \
  --batch-size 100
```

For a small test:

```bash
python sync_storymedia_base64_to_s3.py \
  --mode read \
  --limit 10 \
  --batch-size 10
```

Review the generated report and confirm that the media verification is successful.

---

## Step 4: Base64 Cleanup - Write

After confirming the read results, run:

```bash
python sync_storymedia_base64_to_s3.py \
  --mode write \
  --confirm \
  --batch-size 100
```

For the first write test, use:

```bash
python sync_storymedia_base64_to_s3.py \
  --mode write \
  --confirm \
  --limit 10 \
  --batch-size 10
```

The cleanup script will clear `base64_str` **only after the S3/media object is successfully verified against the Base64 data**.

---

## Recommended Execution Order

Always follow this order:

```text
1. Pre-Migration - Read
        ↓
2. Review report
        ↓
3. Pre-Migration - Write
        ↓
4. Verify PostgreSQL
        ↓
5. Cleanup - Read
        ↓
6. Review cleanup report
        ↓
7. Cleanup - Write
```

## Important Safety Notes

* Always run `--mode read` first.
* Use `--confirm` only when you are ready to make changes.
* Test with `--limit 10` before running the complete migration.
* The pre-migration script does not delete Base64 data.
* The cleanup script deletes/clears `base64_str` only after successful media verification.
* Review the generated JSON reports after each step.

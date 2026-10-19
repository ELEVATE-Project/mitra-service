# Storymedia Migration

This folder contains scripts to safely migrate and clean up Base64 media data from the `chatbot_storymedia` table.

## What we are doing

The migration is performed in two steps:

### 1. Pre-Migration

- Verify that existing `file` / `file_url` references point to valid S3 media.
- Verify that the S3 media size matches the Base64 data.
- Populate missing `file` or `file_url` references when required.
- Generate a JSON report containing the processed IDs.
- **Base64 data is NOT deleted in this step.**

### 2. Base64 Cleanup

- Verify the media again against the Base64 data.
- Clear `base64_str` only after successful verification.
- Generate a report containing the IDs whose Base64 data was cleared.

---

## Navigate to the migration folder

Run the following commands from the project root.

```bash
cd /mitra-service
```

## Running the migration

### Step 1: Start tmux

```bash
tmux
```

### Step 2: Activate the virtual environment

```bash
source .venv/bin/activate
```

### Step 3: Export environment variables

```bash
export $(cat .env | xargs)
```

### Step 4: Run the Pre-Migration script

**Read mode — verify without making changes**

```bash
python manage.py shell -c "import sys; sys.argv=['script', '--mode', 'read', '--batch-size', '100']; from chatbot.scripts.storymedia_migration.storymedia_pre_migration import main; main()"
```

**Write mode — apply pre-migration updates**

```bash
python manage.py shell -c "import sys; sys.argv=['script', '--mode', 'write', '--confirm', '--batch-size', '100']; from chatbot.scripts.storymedia_migration.storymedia_pre_migration import main; main()"
```

### Step 5: Run the Base64 Cleanup script

**Read mode — verify media before cleanup**

```bash
python manage.py shell -c "import sys; sys.argv=['script', '--mode', 'read', '--batch-size', '100']; from chatbot.scripts.storymedia_migration.sync_storymedia_base64_to_s3 import main; main()"
```

**Write mode — clear Base64 after verification**

First, run a limited test with 100 records:

```bash
python manage.py shell -c "import sys; sys.argv=['script', '--mode', 'write', '--confirm', '--batch-size', '50', '--limit', '100']; from chatbot.scripts.storymedia_migration.sync_storymedia_base64_to_s3 import main; main()"
```

After checking the results, run the full cleanup:

```bash
python manage.py shell -c "import sys; sys.argv=['script', '--mode', 'write', '--confirm', '--batch-size', '50']; from chatbot.scripts.storymedia_migration.sync_storymedia_base64_to_s3 import main; main()"
```

---

## Important Notes

- Run the commands from the project root, where `manage.py` and `.env` are located.
- Always run **read mode first** and review the generated JSON reports before running write mode.
- Use `--confirm` only when you are ready to apply changes.
- Keep the `tmux` session running during long-running migrations. Detach with `Ctrl+B`, then `D`. Reattach using `tmux attach`.
- The `.env` export command assumes the file contains shell-compatible values. Values containing spaces or special characters may require a safer loading method.

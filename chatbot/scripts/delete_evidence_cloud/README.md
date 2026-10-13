# S3 Object Deletion Script

## Purpose

The `delete_s3_objects.py` script reads S3/media URLs from a CSV file and deletes the corresponding objects from an S3 bucket.

It supports:

* Reading URLs from a CSV file.
* Validating the bucket and object key.
* Checking which objects can be deleted.
* Deleting objects after explicit confirmation.
* Generating a CSV report with the results.

## Script Location

Navigate to the script directory:

```bash
cd /home/user7/Documents/MITRA/mitra-service/mitra-service/chatbot/scripts/delete_evidence_cloud
```

## Input Details

* **CSV file:** `/home/user7/Downloads/Testingsheet.csv`
* **URL column:** `file_url`
* **Key prefix:** `chatbot/storymedia/`

Make sure the CSV contains a `file_url` column with the URLs to be processed.

## Step 1: Read and Validate URLs

Run the script in read mode to check the URLs before deletion.

```bash
python delete_s3_objects.py \
  --mode read \
  --csv "/home/user7/Downloads/Testingsheet.csv" \
  --column file_url
```

Review the output and report. Resolve any invalid URLs or missing bucket configuration before proceeding.

## Step 2: Dry Run

Run write mode without `--confirm` to check which objects would be deleted.

```bash
python delete_s3_objects.py \
  --mode write \
  --csv "/home/user7/Downloads/Testingsheet.csv" \
  --column file_url \
  --default-bucket YOUR_ACTUAL_BUCKET_NAME \
  --allowed-bucket YOUR_ACTUAL_BUCKET_NAME \
  --prefix chatbot/storymedia/
```

Replace `YOUR_ACTUAL_BUCKET_NAME` with the real S3 bucket name.

**Note:** `--default-bucket` resolves custom media URLs, while `--allowed-bucket` restricts deletion to the permitted bucket. The public hostname is not necessarily the S3 bucket name.

Review the report before proceeding.

## Step 3: Delete Objects

After verifying the bucket, prefix, and report, run:

```bash
python delete_s3_objects.py \
  --mode write \
  --csv "/home/user7/Downloads/Testingsheet.csv" \
  --column file_url \
  --default-bucket YOUR_ACTUAL_BUCKET_NAME \
  --allowed-bucket YOUR_ACTUAL_BUCKET_NAME \
  --prefix chatbot/storymedia/ \
  --confirm
```

**Warning:** The `--confirm` option sends delete requests to S3. Verify the target objects before running this command.

## Step 4: Check the Report

The script generates a report in the current working directory, with a filename similar to:

```text
delete_s3_objects_report_TIMESTAMP.csv
```

Check the status of each object.

| Status                 | Meaning                                                                   |
| ---------------------- | ------------------------------------------------------------------------- |
| `DRY_RUN_WOULD_DELETE` | The object would be deleted; no delete request was sent.                  |
| `DELETE_REQUESTED`     | The delete API request was sent successfully. Verify deletion separately. |
| `NOT_FOUND`            | The object was not found at the target bucket/key.                        |
| `DELETE_ERROR`         | The deletion request failed.                                              |
| `INVALID_URL`          | The URL could not be parsed or validated.                                 |

## Step 5: Verify Public URL Access

Use `curl` to check whether a deleted object is still accessible.

```bash
curl -I "YOUR_PUBLIC_MEDIA_URL"
```

To check the final HTTP status:

```bash
curl -L -o /tmp/test.pdf \
  -w "\nHTTP status: %{http_code}\n" \
  "YOUR_PUBLIC_MEDIA_URL"
```

A `404` response means the resource is not available at that public URL. It does not prove that all previous versions have been permanently removed from a versioned S3 bucket.

If the URL remains accessible, verify the bucket and object key, check bucket versioning, and investigate CDN caching.

## Safety Checklist

* Confirm the CSV path and column name.
* Confirm the actual S3 bucket name.
* Run read mode first.
* Review the dry-run report.
* Verify the allowed bucket and key prefix.
* Use `--confirm` only after checking the target objects.
* Verify public URL access after deletion.

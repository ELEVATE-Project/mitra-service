"""
User-facing response and validation messages, kept in one place.

Messages that reach an admin or an API client live here rather than inline at the point
they are raised, so wording can be reviewed and changed without hunting through views and
models. Several of these are asserted verbatim by QA, so treat the text as part of the
contract - change it deliberately, not incidentally.

Entries ending in `_TEMPLATE` take `.format(...)` arguments; the rest are complete
messages.

Named in snake_case to match the other modules in this package and PEP 8.
"""


# -------------- CSV CORRECTION: UPLOAD ------------------

CSV_NO_PERMISSION = "You do not have permission to change stories."
CSV_NO_FILE_UPLOADED = "No file uploaded."
CSV_INVALID_FILE_FORMAT = "Invalid file format. Please upload a .csv file."
CSV_EMPTY_FILE = "CSV file is empty."
CSV_MISSING_ID_COLUMN = "Missing required column: 'id'. The CSV must have an 'id' column."

CSV_PARSE_FAILED_TEMPLATE = "Could not parse CSV: {error}"
CSV_DUPLICATE_IDS_TEMPLATE = (
    "Duplicate id values detected — upload rejected. Duplicates: {ids}"
)


# -------------- CSV CORRECTION: ROW VALIDATION ------------------

CSV_ROW_ID_EMPTY = "id is empty"
CSV_ROW_INVALID_ACTION = "action must be 'update' or 'ignore'"

CSV_ROW_INVALID_STATE_TEMPLATE = (
    "Invalid State '{state}' — not in the 29 recognised states of India"
)
CSV_ROW_UNKNOWN_ROLE_TEMPLATE = (
    "Role '{role}' does not exist in master system access configurations"
)
CSV_ROW_UNKNOWN_LEADER_CATEGORY_TEMPLATE = (
    "Leader Category '{leader_category}' does not exist in master system access "
    "configurations"
)
CSV_ROW_STORY_NOT_FOUND_TEMPLATE = "No Story found with id='{story_id}'"
CSV_ROW_DB_ERROR_TEMPLATE = "DB error: {error}"
CSV_ROW_SAVE_FAILED_TEMPLATE = "Save failed: {error}"


# -------------- MODEL VALIDATION ------------------

FLOW_DEFAULT_FLOW_NOT_CHILD = "default_flow must be a direct child of this flow."

PROGRAM_MAPPING_UNKNOWN_STATE_TEMPLATE = (
    "'{state}' is not a known state. Choose one of: {valid_states}."
)

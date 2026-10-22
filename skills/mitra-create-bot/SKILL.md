---
name: mitra-create-bot
description: Build a Mitra bot-config JSON (name, route, optional max_token/bot_temperature/top_k, state_machines with step/name/bot_question) from the state_<int>_prompt.txt files, global_context.txt, and question-bank CSV in the current directory. Use when the user wants to create a bot JSON / bot config from Mitra state prompt files, e.g. "create bot json", "build bot config from states", "make the bot file for these states".
---

# mitra-create-bot

Produces `<route_slug>.json` in the directory where the skill is triggered (the user's cwd, NOT this skill dir). No API calls.

All parsing + validation is done by `scripts/build_bot_json.py` (stdlib only). Do not hand-build the JSON. `SCRIPT` below = `~/.claude/skills/mitra-create-bot/scripts/build_bot_json.py`. `FINALIZE` = `~/.claude/skills/mitra-create-bot/scripts/finalize_bot_json.py`.

## Workflow

### 1. Check directory

```bash
python3 SCRIPT check --dir .
```

Returns JSON: `states`, `csv_candidates`, `warnings`, `errors`.

- Show warnings (near-match files like `state_6a_prompt.txt` are ignored).
- If `errors` non-empty (missing `global_context.txt`, no state files, missing/multiple `<state id="...">` tags, duplicate steps): report ALL to user, stop.

### 2. Resolve CSV

- Exactly 1 entry in `csv_candidates` → use it, tell user which.
- 0 or >1 → ask user for CSV path.

### 3. Ask user (single prompt)

- **Bot name** — required. NEVER assume or infer from files/dir.
- **max_token** — optional, positive int.
- **bot_temperature** — optional, float 0.0–1.0 inclusive.
- **top_k** — optional, positive int.

User may skip optionals. Invalid value → re-ask that field only.

### 4. Route

```bash
python3 SCRIPT route --name "<name>"
```

Rule: lowercase → each run of non-`[a-z0-9]` → `_` → strip `_` ends → prefix `/`. E.g. `1M Voices` → `/1m_voices`.

- Script errors (no alphanumerics in name) → re-ask name.
- Show derived route; user may override. Override must match `^/[a-z0-9]+(_[a-z0-9]+)*$`, else re-ask.

### 5. Build

```bash
python3 SCRIPT build --dir . --csv "<csv>" --name "<name>" --route "<route>" \
  [--max-token N] [--temperature F] [--top-k N]
```

Omit flags for skipped optionals (keys are then omitted from JSON, not null).

Exit codes:
- `0` → prints output path. Go to step 6.
- `1` → validation errors on stderr. Report ALL to user; no JSON written. Errors include: state file with no CSV row, CSV step with no state file, invalid step cell, duplicate CSV step, missing `step number` / `main question` column.
- `2` → output file exists. Ask user to overwrite; if yes rerun with `--force`.

### 6. Finalize

ALWAYS run right after step 5 succeeds. Do not hand-edit the JSON instead.

```bash
python3 FINALIZE "<output path from step 5>" [--context <file>]
```

Inputs, all read from the JSON's dir (cwd irrelevant):
- `global_context.txt` → top-level `context`. `--context <file>` overrides path.
- `state_<step>_prompt.txt` → each state's `context`, matched by `step`. Top level only, same filename regex as step 5.

What it does, in place:
1. Top level, **defaults** (set only if key missing, so step-3 user values win): `max_token` 8192, `bot_temperature` 0.0, `top_k` 2.
2. Top level, **overrides** (always overwritten): `provider` `bedrock/converse`, `llm_model` Haiku 4.5, `filter_score` 0.8, `bot_type` `STATE_MACHINE`, `company_slug` `shikshalokamstaging`, timeouts, `chat_history_limit`, `stream` false, empty `dynamic_context`/`pre_context`/`tool_context`, `voices` [], and `other_params` (custom model + `structured_memory_output` JSON schema forcing bot turns into `reason`, `should_function_call`, `last_question_asked`, `message_kind`, `response`).
3. Top level `context` = global context text.
4. Each state, **overrides**: `use_stage_chats` true, `type` `MANDATORY`, `text_conversion_type` `TRANSLATE`, `operation_type` `llm`, pre/postprocess off, other fields null/empty. Then `context` = state prompt text. Existing `step`/`name`/`bot_question` kept.
5. Writes atomically, wrapped as single-object list `[ {...} ]`.

Exact values: `DEFAULTS`, `OVERRIDES`, `STATE_MACHINE_OVERRIDES` at top of script. Change values there, not in JSON.

Exit codes:
- `0` → prints path. Done; tell user file is finalized.
- `1` → `error: ...` on stderr, file untouched. Report to user. Causes: missing `global_context.txt`, state step with no prompt file, empty/missing `state_machines`, invalid JSON, top level not object/single-object list.

Idempotent: rerun on finalized file gives identical output.

## Rules (enforced by script)

- State files: top level only, exact `^state_(\d+)_prompt\.txt$`. `step` = that int.
- `name` = value of the single `<state id="...">` tag in the file.
- CSV headers matched by `header.lower() == "step number"` and `header.lower() == "main question"` (no whitespace trim).
- Step cells: trimmed, parsed to int; whole floats (`6.0`) OK; empty → row skipped; anything else → error.
- `bot_question` = Main Question cell verbatim, only ends trimmed.
- `global_context.txt` must exist; content unused.
- `state_machines` sorted by step (numeric), `step` emitted as int.

## Output shape (after step 5, before finalize)

```json
{
    "name": "1M Voices",
    "max_token": 512,
    "bot_temperature": 0.3,
    "top_k": 40,
    "route": "/1m_voices",
    "state_machines": [
        {"step": 1, "name": "SCHOOL_VISIT_FREQUENCY", "bot_question": "..."}
    ]
}
```

## Output shape (after finalize)

```json
[
    {
        "name": "1M Voices",
        "max_token": 512,
        "bot_temperature": 0.3,
        "top_k": 40,
        "route": "/1m_voices",
        "state_machines": [
            {"step": 1, "name": "SCHOOL_VISIT_FREQUENCY", "bot_question": "...",
             "use_stage_chats": true, "type": "MANDATORY", "...": "...",
             "context": "<state_1_prompt.txt text>"}
        ],
        "provider": "bedrock/converse",
        "llm_model": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "other_params": {"...": "..."},
        "...": "...",
        "context": "<global_context.txt text>"
    }
]
```

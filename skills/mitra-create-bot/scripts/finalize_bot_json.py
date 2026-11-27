#!/usr/bin/env python3
"""Finalize a Mitra bot-config JSON (output of build_bot_json.py) in place.

Usage:
  finalize_bot_json.py PATH [--context FILE]

Reads, from PATH's directory:
  global_context.txt          -> top-level "context" (override with --context)
  state_<step>_prompt.txt     -> each state_machines[i]["context"], matched by "step"

Steps:
  1. Top level: add DEFAULTS keys only when missing; always overwrite OVERRIDES keys.
  2. Top level: set "context".
  3. Each state: always overwrite STATE_MACHINE_OVERRIDES keys; set "context".
  4. Write back atomically, wrapped in a single-object list: [ {...} ].

Input may be a JSON object or an already-finalized single-object list, so reruns are safe.
Exit 0 on success (prints output path); exit 1 with "error: ..." on stderr otherwise.
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Top-level keys added when missing. Existing values are never overwritten.
DEFAULTS: dict = {
    "max_token": 8192,
    "bot_temperature": 0.0,
    "top_k": 2,
}

# Top-level keys always set. Existing values are overwritten.
# other_params.outputConfig forces the bot LLM to emit structured_memory_output JSON
# (reason, should_function_call, last_question_asked, message_kind, response).
OVERRIDES: dict = {
    "provider": "bedrock/converse",
    "llm_model": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "filter_score": 0.8,
    "bot_type": "STATE_MACHINE",
    "dynamic_context": "",
    "dynamic_context_type": None,
    "pre_context": "",
    "tool_context": "",
    "other_params": {
      "custom_model": "google.gemma-3-12b-it",
      "outputConfig": {
        "textFormat": {
          "type": "json_schema",
          "structure": {
            "jsonSchema": {
              "name": "structured_memory_output",
              "schema": "{\"type\": \"object\", \"required\": [\"reason\", \"should_function_call\", \"last_question_asked\", \"message_kind\", \"response\"], \"properties\": {\"reason\": {\"type\": \"string\", \"description\": \"Written first; this is where the decision is made. One line in this exact shape: Position: [0 / 1 / 2+]. Intent: [offensive / declined / complete_answer / incomplete_answer / not_read]. User said: [short paraphrase]. Decision: [ask_primary / probe / redirect / complete]. Why: [one short clause].\"}, \"should_function_call\": {\"type\": \"boolean\", \"description\": \"true only when the Decision in reason is complete (data collected, respondent declined, or probe already used). false for ask_primary, probe and redirect.\"}, \"last_question_asked\": {\"type\": \"string\", \"enum\": [\"primary\", \"fq1\"], \"description\": \"primary at Position 0, and at Position 1 when the Decision is complete or redirect. fq1 at Position 1 when the Decision is probe, and always at Position 2+. Descriptive only; not fed back on the next turn.\"}, \"message_kind\": {\"type\": \"string\", \"enum\": [\"clarification\", \"follow_up\"], \"description\": \"clarification when the Decision is redirect, or when response re-explains the same question. follow_up for everything else: ask_primary, probe, and complete.\"}, \"response\": {\"type\": \"string\", \"description\": \"Written last. Empty string if and only if should_function_call is true; write no thanks, acknowledgement or summary. Otherwise exactly one of: the state's PRIMARY question word for word (ask_primary); one new probe question grounded in what the respondent said (probe); or 'I'm here to have a respectful conversation.' followed by the PRIMARY question (redirect).\"}}, \"additionalProperties\": false}",
              "description": "Generate a structured JSON response: decision reasoning first, then the completion flag, bookkeeping fields, and finally the message to the respondent."
            }
          }
        }
      }
    },
    "connect_timeout": 5.0,
    "read_timeout": 10.0,
    "chat_history_limit": 1000,
    "stream": False,
    "default_role": None,
    "company_slug": "shikshalokamstaging",
    "voices": [],
}

# Keys always set on every state_machines entry. Existing values are overwritten.
STATE_MACHINE_OVERRIDES: dict = {
    "use_stage_chats": True,
    "type": "MANDATORY",
    "text_conversion_type": "TRANSLATE",
    "completion_criteria": "",
    "tool_context": "",
    "preprocess_type": "NONE",
    "preprocess_prompt": None,
    "preprocess_output_mode": "NONE",
    "postprocess_type": "NONE",
    "postprocess_prompt": None,
    "postprocess_output_mode": "NONE",
    "skip_to_step": None,
    "operation_type": "llm",
    "skip_if_authenticated": False,
    "translations": None,
    "preprocess_bot_route": None,
    "postprocess_bot_route": None
}



STATE_PROMPT_PATTERN = re.compile(r"^state_(\d+)_prompt\.txt$")


def find_state_prompts(root: Path) -> dict[int, Path]:
    """Map step number -> state_<step>_prompt.txt in root (top level only)."""
    prompts: dict[int, Path] = {}
    for p in root.iterdir():
        m = STATE_PROMPT_PATTERN.match(p.name)
        if p.is_file() and m:
            prompts[int(m.group(1))] = p
    return prompts


def add_state_machine(data: dict, root: Path) -> dict:
    """Apply STATE_MACHINE_OVERRIDES and set context on each state. Error if a step has no prompt file."""
    if not data.get("state_machines"):
        raise ValueError("State machine is empty in the json")
    prompts = find_state_prompts(root)

    for state in data["state_machines"]:
        add_defaults(data=state, defaults={}, overrides=STATE_MACHINE_OVERRIDES)
        context_path = prompts.get(int(state["step"]))
        if context_path is None:
            raise FileNotFoundError(f"Context prompt not found: state_{state['step']}_prompt.txt in {root}")
        state["context"] = context_path.read_text(encoding="utf-8")
    return data


def load_json(path: Path) -> dict:
    """Load bot config; unwrap a single-object list from a previous run."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object or single-object list, got {type(data).__name__}")
    return data


def add_defaults(data: dict, defaults: dict = DEFAULTS, overrides: dict = OVERRIDES) -> dict:
    """Set defaults only where key is missing, then overwrite with overrides."""
    for key, value in defaults.items():
        if key not in data:
            data.setdefault(key, value)
    data.update(overrides)
    return data


def write_json(path: Path, data) -> None:
    """Write to temp file in same dir, then atomically replace original."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def finalize(path: Path, context_path: Path) -> None:
    data = load_json(path)
    add_defaults(data)
    data["context"] = context_path.read_text(encoding="utf-8")
    add_state_machine(data, path.parent)
    write_json(path, [data])


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize a Mitra bot-config JSON in place.")
    parser.add_argument("path", type=Path, help="JSON file path (relative or absolute)")
    parser.add_argument(
        "--context",
        type=Path,
        help="Context text file (default: global_context.txt next to the JSON file)",
    )
    args = parser.parse_args()

    path = args.path.expanduser().resolve()
    context_path = (args.context or path.parent / "global_context.txt").expanduser().resolve()

    try:
        finalize(path, context_path)
    except (OSError, ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    print(path)


if __name__ == "__main__":
    main()

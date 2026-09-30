"""
Title regeneration benchmark: LLaMA 3.3 70B vs Claude Haiku 4.5 (Bedrock Converse)
==================================================================================

Design rules this script follows
--------------------------------
1. The system prompt is the bot's own `context`, used verbatim. Never edited here.
2. The old story title is injected through a **Jinja template that lives in config**
   (`tag_context`), rendered exactly the way `validate_title_utils()` does.
3. Both models receive the **identical** request - same system prompt, same message
   list, same toolConfig, same inferenceConfig. Only `modelId` differs, so the
   comparison is apples-to-apples.
4. NO prompt instruction text is stored in this file. Both the title template and
   the retry message come from config. If they are missing, the script stops and
   tells you exactly where to put them.
5. If a call comes back with an empty title or empty problem_statement, the script
   retries ONCE, appending the failure to the conversation using the retry message
   from config. Tokens and cost from BOTH attempts are summed into the sheet.
   With --title-only, only an empty title triggers the retry; problem_statement is
   still captured and written when present, but is no longer required. Use this with
   bot prompts that are deliberately title-only.
6. Every session is recorded as passed or failed in a run log.

Where the two prompt strings come from
--------------------------------------
Resolution order (first hit wins):

  title template   1. prompt file  -> key "title_template"
                   2. bot config   -> field "tag_context"

  retry message    1. prompt file  -> key "retry_message"
                   2. bot config   -> other_params["retry_message"]

The prompt file is JSON (or YAML if PyYAML is installed), pointed at by
--prompt-file, defaulting to PROMPT_FILE below.

The title template is Jinja and is rendered with these variables:
    title, old_title, session, id
e.g.   Existing story title: {{ title }}

Usage
-----
    # preflight: show the fully rendered request without calling Bedrock
    python shikshalokam/utils/title_regeneration_test.py --dry-run --limit 1

    # one row, LLaMA
    python shikshalokam/utils/title_regeneration_test.py --limit 1 --models llama

    # everything, both models
    python shikshalokam/utils/title_regeneration_test.py --models llama haiku

    # top up specific sessions (merges into the existing workbook)
    python shikshalokam/utils/title_regeneration_test.py --models haiku --sessions abc def

Requirements: boto3, pandas, openpyxl, json_repair, jinja2.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path

# --------------------------------------------------------------------------- #
#                                  CONFIG                                      #
#            (no prompt instruction text may live in this file)                #
# --------------------------------------------------------------------------- #

# Default input sheet, overridden by --csv. Accepts .csv or .xlsx.
CSV_PATH = "New_Data.xlsx"

# Default bot config, overridden by --bot-file. NOTE: this is the ORIGINAL Aug-10
# export. The current per-model bots are company_bots_51_llama_v1.json and
# company_bots_51_haiku_v2.json - always pass --bot-file so the run is explicit.
BOT_JSON_PATH = "company_bots_51.json"
BOT_ROUTE = "/story_temp"
BOT_COMPANY_SLUG = "shikshalokamstaging"

# Optional external prompt file (JSON/YAML) holding "title_template" / "retry_message".
PROMPT_FILE = "title_prompts.json"

OUT_DIR = "title_benchmark_output"
OUT_XLSX = "title_regeneration_comparison.xlsx"
RAW_JSONL = "bedrock_raw_responses.jsonl"
RUN_LOG = "run_log.json"

AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 60.0
SLEEP_BETWEEN_CALLS = 0.5
MAX_RETRIES = 3            # transport-level retries (throttling etc.)
MAX_LLM_ATTEMPTS = 2       # semantic retries: 1 original + 1 redo on empty output

# Minimum chars of real chat before we treat chat history as usable (chat mode only).
MIN_CHAT_CHARS = 50

INPUT_MODE = "title"

# Model registry. Prices are USD per 1K tokens.
# NOTE: request-shaping flags are deliberately IDENTICAL across models so that the
# two calls differ only by modelId. Changing one of these breaks the comparison.
# Anthropic models reject temperature and topP together ("cannot both be specified"),
# while Meta accepts either. To keep ONE request shape valid on both, send temperature
# only and omit topP. Flip this to send the bot's filter_score as topP instead - but
# then also drop temperature, or Claude will fail.
SEND_TOP_P = False
SEND_TEMPERATURE = True
FORCE_TOOL_CHOICE = False   # Bedrock rejects toolChoice for Meta, so off for both

MODELS = {
    "llama": {
        "label": "llama_3_3_70b",
        "model_id": "us.meta.llama3-3-70b-instruct-v1:0",
        "input_cost_per_1k": 0.00072,
        "output_cost_per_1k": 0.00072,
    },
    "haiku": {
        "label": "claude_haiku_4_5",
        "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "input_cost_per_1k": 0.001,
        "output_cost_per_1k": 0.005,
    },
}

DEFAULT_MODEL_ORDER = ["llama", "haiku"]

# Exactly the columns written to each model sheet: internal name -> display header.
# Everything else (problem_statement, retries, latency, errors, raw text) is still
# captured in run_log.json and bedrock_raw_responses.jsonl.
SHEET_COLUMNS = {
    "id": "id",
    "old_title": "Old Title",
    "updated_title": "Updated title",
    "content": "Content",
    "input_token": "Input token",
    "output_token": "Output token",
    "total_token": "Total token",
    "input_cost": "Input cost",
    "output_cost": "Output cost",
    "total_cost": "Total cost",
}


# --------------------------------------------------------------------------- #
#                            DJANGO BOOTSTRAP                                  #
# --------------------------------------------------------------------------- #

def bootstrap_django():
    here = Path(__file__).resolve()
    base = None
    for parent in [here.parent, *here.parents]:
        if (parent / "manage.py").exists():
            base = parent
            break
    if base is None:
        raise RuntimeError("Could not find manage.py above this script.")

    sys.path.insert(0, str(base))
    if not os.getenv("DJANGO_SETTINGS_MODULE"):
        manage_src = (base / "manage.py").read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"DJANGO_SETTINGS_MODULE[\"']\s*,\s*[\"']([^\"']+)", manage_src)
        if not m:
            raise RuntimeError("Could not auto-detect DJANGO_SETTINGS_MODULE from manage.py.")
        os.environ["DJANGO_SETTINGS_MODULE"] = m.group(1)

    import django
    django.setup()
    return base


DJANGO_READY = True
DJANGO_ERROR = None
try:
    BASE_DIR = bootstrap_django()
except Exception as _e:                                        # noqa: BLE001
    BASE_DIR = None
    DJANGO_READY = False
    DJANGO_ERROR = f"{type(_e).__name__}: {_e}"

import boto3                                                   # noqa: E402
import json_repair                                             # noqa: E402
from botocore.client import Config as BotoConfig               # noqa: E402
from botocore.exceptions import ClientError                    # noqa: E402
from jinja2 import Template                                    # noqa: E402

if DJANGO_READY:
    from chatbot.models import CompanyChat, CompanyBot, Company                    # noqa: E402
    from chatbot.utils.chat_utils import format_message_as_per_bedrock_format      # noqa: E402
else:
    CompanyChat = CompanyBot = Company = None
    format_message_as_per_bedrock_format = None


def require_django(what):
    if not DJANGO_READY:
        raise SystemExit(
            f"\n[!] {what} needs Django + the database, but bootstrap failed:\n"
            f"    {DJANGO_ERROR}\n"
            f"    Use --input-mode title to run straight off the sheet with no DB.\n"
        )


# --------------------------------------------------------------------------- #
#                                 HELPERS                                      #
# --------------------------------------------------------------------------- #

def resolve_path(path):
    if not path:
        return None
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    candidates = [Path.cwd() / p, Path(__file__).resolve().parent / p]
    if BASE_DIR:
        candidates.append(Path(BASE_DIR) / p)
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, bytes):
        return o.decode("utf-8", errors="replace")
    return str(o)


def dumps(obj, indent=2):
    return json.dumps(obj, indent=indent, ensure_ascii=False, default=_json_default)


def load_bot_config(bot_json_path=None):
    bot_json = resolve_path(bot_json_path or BOT_JSON_PATH)
    if bot_json and bot_json.exists():
        data = json.loads(bot_json.read_text(encoding="utf-8"))
        bot = (next((b for b in data if b.get("route") == BOT_ROUTE), data[0])
               if isinstance(data, list) else data)
        print(f"[bot] loaded from JSON: {bot_json}  (route={bot.get('route')}, name={bot.get('name')})")
        return bot

    print(f"[bot] JSON not found at {bot_json} - falling back to DB lookup")
    require_django("Loading the bot config from the database")
    qs = CompanyBot.objects.filter(route=BOT_ROUTE)
    if BOT_COMPANY_SLUG:
        company = Company.objects.filter(slug=BOT_COMPANY_SLUG).first()
        if company:
            qs = qs.filter(company=company)
    bot_obj = qs.first()
    if not bot_obj:
        raise SystemExit(f"No CompanyBot found for route={BOT_ROUTE} slug={BOT_COMPANY_SLUG}")
    print(f"[bot] loaded from DB: id={bot_obj.id} route={bot_obj.route}")
    return {
        "context": bot_obj.context,
        "tag_context": bot_obj.tag_context,
        "tool_context": bot_obj.tool_context,
        "llm_model": bot_obj.llm_model,
        "bot_temperature": bot_obj.bot_temperature,
        "filter_score": bot_obj.filter_score,
        "max_token": bot_obj.max_token,
        "other_params": bot_obj.other_params,
    }


def _as_dict(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:                                       # noqa: BLE001
            return {}
    return value or {}


def load_prompt_config(bot, prompt_file_path):
    """
    Resolve the two prompt strings from config. Nothing is defaulted in code:
    if either is missing the script stops with instructions.
    """
    file_cfg = {}
    pf = resolve_path(prompt_file_path)
    if pf and pf.exists():
        raw = pf.read_text(encoding="utf-8")
        if pf.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml
                file_cfg = yaml.safe_load(raw) or {}
            except ImportError:
                raise SystemExit(f"\n[!] {pf} is YAML but PyYAML is not installed. "
                                 f"pip install pyyaml, or use a .json prompt file.\n")
        else:
            file_cfg = json.loads(raw)
        print(f"[prompts] loaded prompt file: {pf}")
    else:
        print(f"[prompts] no prompt file at {pf} - falling back to the bot config")

    other_params = _as_dict(bot.get("other_params"))

    title_template = (file_cfg.get("title_template") or bot.get("tag_context") or "").strip()
    retry_message = (file_cfg.get("retry_message") or other_params.get("retry_message") or "").strip()

    # An explicitly-present empty title_template is a deliberate choice: send the
    # conversation only, with nothing appended. A missing key is a config error.
    title_optional = "title_template" in file_cfg and not (file_cfg.get("title_template") or "").strip()
    if title_optional and not title_template:
        print("[prompts] title_template is explicitly empty - sending the conversation only, "
              "no title injected")

    missing = []
    if not title_template and not title_optional:
        missing.append(
            '  title_template  - the Jinja block that injects the old title.\n'
            f'      put it in : {pf}  under key "title_template"\n'
            f'      or in     : the bot config field "tag_context"\n'
            '      variables: {{ story.title }} {{ story.session }} {{ story.id }}\n'
            '                 (flat forms {{ title }} {{ session }} {{ id }} also work)'
        )
    if not retry_message:
        missing.append(
            '  retry_message   - the instruction appended when the model returns an empty\n'
            '                    title or problem_statement, before the single retry.\n'
            f'      put it in : {pf}  under key "retry_message"\n'
            '      or in     : the bot config other_params["retry_message"]'
        )
    if missing:
        raise SystemExit(
            "\n[!] Missing prompt configuration. This script deliberately stores no prompt\n"
            "    instruction text of its own, so it cannot invent these for you.\n\n"
            + "\n\n".join(missing)
            + "\n\n    Example prompt file:\n"
              '    {\n'
              '      "title_template": "...your Jinja here, e.g. {{ title }} ...",\n'
              '      "retry_message": "...your retry instruction here..."\n'
              '    }\n'
        )

    return {"title_template": title_template, "retry_message": retry_message}


def extract_tool_config(bot):
    raw = bot.get("tool_context")
    if not raw:
        return None
    cfg = json_repair.repair_json(raw, return_objects=True) if isinstance(raw, str) else raw
    if not isinstance(cfg, dict):
        return None
    if "toolConfig" in cfg:
        return cfg["toolConfig"]
    for value in cfg.values():
        if isinstance(value, dict) and "toolConfig" in value:
            return value["toolConfig"]
        if isinstance(value, dict) and "tools" in value:
            return {"tools": value["tools"]}
    if "tools" in cfg:
        return {"tools": cfg["tools"]}
    return None


def read_sheet(csv_path):
    """
    Accepts .csv or .xlsx. Recognised columns: id, title (the existing title), session,
    and optionally `content` - a pre-written story narrative used as the source material
    when there is no chat export for the session.
    """
    path = Path(csv_path)

    if path.suffix.lower() in (".xlsx", ".xls", ".xlsm"):
        import pandas as pd
        df = pd.read_excel(path)
        df.columns = [str(c).strip() for c in df.columns]
        raw_rows = df.where(df.notna(), "").to_dict(orient="records")
    else:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            raw_rows = list(csv.DictReader(fh))

    rows = []
    for row in raw_rows:
        row = {(str(k) or "").strip(): (v.strip() if isinstance(v, str) else v)
               for k, v in row.items()}
        session = row.get("session") or row.get("session_id") or row.get("Session")
        if not session:
            continue
        rows.append({
            "id": str(row.get("id", "") or ""),
            "old_title": str(row.get("title", "") or ""),
            "session": str(session),
            "content": str(row.get("content", "") or ""),
        })
    return rows


def load_chat_files(paths):
    """
    Build {session: [bedrock messages]} from exported CompanyChat dumps
    (.xlsx / .csv), so requirement 3 works without prod DB access.

    Role mapping mirrors format_message_as_per_bedrock_format(): production marks a
    turn as the human's when `receiver` is the AI profile, so here a row whose
    `receiver` is "AI" becomes role=user and everything else becomes role=assistant.
    `translated_message` wins over `message` when present, exactly as in production.
    """
    import pandas as pd

    frames = []
    for raw in paths:
        for path in sorted(Path().glob(raw)) or [Path(raw)]:
            p = resolve_path(str(path))
            if not p or not p.exists():
                raise SystemExit(f"\n[!] chat file not found: {path}\n")
            df = pd.read_csv(p) if p.suffix.lower() in (".csv", ".tsv") else pd.read_excel(p)
            frames.append(df)
            print(f"[chat] loaded {len(df)} row(s) from {p.name}")

    if not frames:
        return {}

    df = pd.concat(frames, ignore_index=True)
    for col in ("session", "message", "receiver"):
        if col not in df.columns:
            raise SystemExit(f"\n[!] chat export is missing required column '{col}'. "
                             f"Found: {list(df.columns)}\n")
    if "created_at" in df.columns:
        df["_ts"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
        df = df.sort_values(["session", "_ts", "id"] if "id" in df.columns else ["session", "_ts"])

    chats = {}
    for session, group in df.groupby("session"):
        records, chars = [], 0
        for _, r in group.iterrows():
            translated = r.get("translated_message")
            message = r.get("message")
            text = translated if isinstance(translated, str) and translated.strip() else message
            if not isinstance(text, str) or not text.strip():
                continue
            receiver = r.get("receiver")
            is_user = isinstance(receiver, str) and receiver.strip().upper() == "AI"
            records.append({"role": "user" if is_user else "assistant",
                            "content": [{"text": text.strip()}]})
            chars += len(text)
        chats[str(session)] = (normalize_messages(records), len(group), chars)
    return chats


def get_chat_messages(session):
    company_chats = (
        CompanyChat.objects
        .select_related("sender", "receiver")
        .filter(session=session)
        .order_by("created_at")
        .values("receiver", "receiver__id", "translated_message", "message", "status", "created_at")
    )
    company_chats = list(company_chats)
    messages = normalize_messages(format_message_as_per_bedrock_format(chats=company_chats))
    chat_chars = sum(len(c.get("translated_message") or c.get("message") or "") for c in company_chats)
    return messages, len(company_chats), chat_chars


def render_title_block(template_str, row):
    """
    Render the config-supplied Jinja template.

    Two equivalent ways to reference the same values, so either template style works:

      dotted   {{ story.title }}   {{ story.session }}   {{ story.id }}
      flat     {{ title }}         {{ session }}         {{ id }}

    The flat keys mirror validate_title_utils() in validation_utils.py, whose context is
        {"title", "actionList", "objective", "problem_statement"}
    so a template written for that helper renders unchanged here.

    `title` is the existing story title from the sheet. actionList / objective /
    problem_statement have no source in this benchmark and render as empty strings -
    referencing them is safe, they simply produce nothing.
    """
    story = {
        "title": row["old_title"],
        "old_title": row["old_title"],
        "session": row["session"],
        "id": row["id"],
        "actionList": row.get("actionList", ""),
        "objective": row.get("objective", ""),
        "problem_statement": row.get("problem_statement", ""),
    }
    return Template(template_str).render(story=story, **story)


def build_messages(chat_messages, title_block):
    """
    Full conversation first, then the rendered title block as a final user turn.
    In title-only mode chat_messages is empty, so the block is the whole message list.
    """
    msgs = list(chat_messages or [])
    return normalize_messages(msgs)


def normalize_messages(messages):
    """Drop empty blocks, merge consecutive same-role turns, start and end on `user`."""
    cleaned = []
    for msg in messages or []:
        blocks = [b for b in msg.get("content", []) if isinstance(b, dict) and (b.get("text") or "").strip()]
        if not blocks:
            continue
        cleaned.append({"role": msg["role"], "text": "\n".join(b["text"].strip() for b in blocks)})

    merged = []
    for msg in cleaned:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["text"] += "\n" + msg["text"]
        else:
            merged.append(dict(msg))

    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    while merged and merged[-1]["role"] != "user":
        merged.pop()

    return [{"role": m["role"], "content": [{"text": m["text"]}]} for m in merged]


def build_retry_messages(base_messages, assistant_text, retry_message):
    """
    Append what the model actually said, then the config-supplied retry instruction.
    If the model said nothing usable we skip the assistant turn (Bedrock rejects empty
    text blocks) and normalize_messages merges the trailing user turns.
    """
    msgs = list(base_messages)
    if (assistant_text or "").strip():
        msgs.append({"role": "assistant", "content": [{"text": assistant_text.strip()}]})
    msgs.append({"role": "user", "content": [{"text": retry_message}]})
    return normalize_messages(msgs)


def make_client():
    return boto3.client(
        service_name="bedrock-runtime",
        region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        config=BotoConfig(connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT,
                          retries={"mode": "adaptive"}),
    )


def build_payload(model_id, system_prompt, messages, tool_config, temperature, top_p, max_tokens):
    """Identical for every model except modelId - that is the point."""
    inference_config = {"maxTokens": max_tokens}
    if SEND_TEMPERATURE and temperature is not None:
        inference_config["temperature"] = temperature
    if SEND_TOP_P and top_p is not None:
        inference_config["topP"] = top_p
    if SEND_TEMPERATURE and SEND_TOP_P:
        print("   ! WARNING: sending temperature AND topP - Anthropic models reject this")

    payload = {
        "modelId": model_id,
        "messages": messages,
        "system": [{"text": system_prompt}],
        "inferenceConfig": inference_config,
    }
    if tool_config:
        tool_config = json.loads(json.dumps(tool_config))
        if FORCE_TOOL_CHOICE:
            try:
                tool_config["toolChoice"] = {"tool": {"name": tool_config["tools"][0]["toolSpec"]["name"]}}
            except (KeyError, IndexError, TypeError):
                pass
        payload["toolConfig"] = tool_config
    return payload


def call_bedrock(client, payload):
    print(f"this is payload: {payload}")
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            t0 = time.time()
            response = client.converse(**payload)
            return response, round(time.time() - t0, 2)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            last_err = e
            print(f"   ! ClientError [{code}] attempt {attempt}/{MAX_RETRIES}: "
                  f"{e.response.get('Error', {}).get('Message')}")
            if code in ("ThrottlingException", "ModelTimeoutException",
                        "ServiceUnavailableException", "InternalServerException"):
                time.sleep(2 * attempt)
                continue
            raise
        except Exception as e:                                  # noqa: BLE001
            last_err = e
            print(f"   ! Error attempt {attempt}/{MAX_RETRIES}: {e}")
            time.sleep(2 * attempt)
    raise last_err


def parse_title(response):
    """toolUse first, then JSON-in-text. Returns (title, problem_statement, parsed, raw_text)."""
    parsed, text = {}, ""
    try:
        content = response["output"]["message"]["content"]
    except Exception:                                           # noqa: BLE001
        return "", "", {}, ""

    for block in content:
        if isinstance(block, dict) and block.get("toolUse"):
            parsed = block["toolUse"].get("input", {}) or {}
            break

    if not parsed:
        for block in content:
            if isinstance(block, dict) and block.get("text"):
                text += block["text"]
        start = text.find("{")
        if start != -1:
            candidate = text[start:].replace("\n", "").replace("\r", "").strip()
            try:
                repaired = json_repair.repair_json(candidate, return_objects=True)
                if isinstance(repaired, dict):
                    parsed = repaired
            except Exception:                                   # noqa: BLE001
                parsed = {}

    if isinstance(parsed, dict):
        if isinstance(parsed.get("parameters"), dict):
            parsed = parsed["parameters"]
        elif isinstance(parsed.get("input"), dict):
            parsed = parsed["input"]

    title = (parsed or {}).get("title", "") or ""
    problem = (parsed or {}).get("problem_statement") or (parsed or {}).get("challenge") or ""
    return str(title).strip(), str(problem).strip(), parsed or {}, text


def usage_and_cost(response, cfg):
    usage = response.get("usage", {}) or {}
    in_tok = int(usage.get("inputTokens", 0) or 0)
    out_tok = int(usage.get("outputTokens", 0) or 0)
    tot_tok = int(usage.get("totalTokens", 0) or (in_tok + out_tok))
    in_cost = (in_tok / 1000.0) * cfg["input_cost_per_1k"]
    out_cost = (out_tok / 1000.0) * cfg["output_cost_per_1k"]
    return in_tok, out_tok, tot_tok, in_cost, out_cost


# --------------------------------------------------------------------------- #
#                                   RUN                                        #
# --------------------------------------------------------------------------- #

def run(args):
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    global FORCE_TOOL_CHOICE
    if args.force_tool_choice:
        FORCE_TOOL_CHOICE = True

    if not args.bot_file:
        print(f"[warn] no --bot-file given; falling back to the default '{BOT_JSON_PATH}'. "
              f"Pass --bot-file explicitly to be sure which bot you are benchmarking.")

    bot = load_bot_config(args.bot_file)
    prompts = load_prompt_config(bot, args.prompt_file)

    # If the bot config carries its own model_pricing, prefer it over the hardcoded
    # rates in MODELS - the bot file is the source of truth for cost.
    bot_pricing = (_as_dict(bot.get("other_params")) or {}).get("model_pricing") or {}
    for key, cfg in MODELS.items():
        p = bot_pricing.get(cfg["model_id"])
        if p and "input_cost_per_1k" in p and "output_cost_per_1k" in p:
            if (cfg["input_cost_per_1k"], cfg["output_cost_per_1k"]) != (
                    float(p["input_cost_per_1k"]), float(p["output_cost_per_1k"])):
                print(f"[cfg] pricing for {cfg['label']} taken from bot file: "
                      f"in={p['input_cost_per_1k']} out={p['output_cost_per_1k']} per 1K")
            cfg["input_cost_per_1k"] = float(p["input_cost_per_1k"])
            cfg["output_cost_per_1k"] = float(p["output_cost_per_1k"])

    system_prompt = bot["context"]
    tool_config = extract_tool_config(bot)
    temperature = float(bot.get("bot_temperature") or 0.5)
    top_p = float(bot.get("filter_score") or 0.9)
    max_tokens = int(bot.get("max_token") or 4096)

    print(f"[cfg] input_mode={args.input_mode} temperature={temperature} "
          f"topP={top_p if SEND_TOP_P else 'omitted'} maxTokens={max_tokens} "
          f"tool={'yes' if tool_config else 'no'} toolChoice={'forced' if FORCE_TOOL_CHOICE else 'free'}")
    print(f"[cfg] request shape is identical across models; only modelId differs")

    csv_path = resolve_path(args.csv)
    if not csv_path or not csv_path.exists():
        raise SystemExit(f"\n[!] CSV not found: {args.csv}\n")

    rows = read_sheet(csv_path)
    all_rows = list(rows)
    if args.sessions:
        wanted = set(args.sessions)
        rows = [r for r in rows if r["session"] in wanted]
    if args.limit:
        rows = rows[: args.limit]
    print(f"[sheet] {len(rows)} row(s) to process from {csv_path}\n")

    # chat source: exported files if given, otherwise the DB
    file_chats = {}
    if args.chat_files:
        file_chats = load_chat_files(args.chat_files)
        if args.input_mode != "chat":
            args.input_mode = "chat"
            print("[cfg] --chat-files supplied -> input_mode switched to 'chat'")
        print(f"[chat] {len(file_chats)} session(s) available from files")

    if args.db_info:
        require_django("--db-info"); db_info(all_rows); return
    if args.check_chats:
        if file_chats:
            check_chats_from_files(all_rows, file_chats); return
        require_django("--check-chats"); check_chats(all_rows); return
    if args.input_mode == "chat" and not file_chats:
        require_django("--input-mode chat (no --chat-files given)")

    # ---- dry run: show the exact request, call nothing ----
    if args.dry_run:
        row = rows[0]
        chat_messages = []
        if args.input_mode == "chat":
            chat_messages, n_rows, n_chars = (file_chats.get(row["session"], ([], 0, 0))
                                              if file_chats else get_chat_messages(row["session"]))
            print(f"[dry-run] chat for {row['session']}: {n_rows} rows -> "
                  f"{len(chat_messages)} turns, {n_chars} chars")
        block = render_title_block(prompts["title_template"], row)
        msgs = build_messages(chat_messages, block)
        print("=" * 90)
        print("DRY RUN - exact request that would be sent (modelId omitted)")
        print("=" * 90)
        print(dumps(build_payload("<modelId>", system_prompt, msgs, tool_config,
                                  temperature, top_p, max_tokens)))
        print("\nRetry turn that would be appended on empty output:")
        print(dumps(build_retry_messages(msgs, "", prompts["retry_message"])[-1]))
        return

    raw_fh = open(out_dir / RAW_JSONL, "a", encoding="utf-8")
    client = make_client()
    results = {key: [] for key in args.models}
    run_log = {"passed": {}, "failed": {}}

    chat_cache = {}

    for model_key in args.models:
        cfg = MODELS[model_key]
        print("=" * 100)
        print(f"MODEL: {cfg['label']}  ({cfg['model_id']})")
        print("=" * 100)
        run_log["passed"][cfg["label"]] = []
        run_log["failed"][cfg["label"]] = []

        for idx, row in enumerate(rows, 1):
            session = row["session"]
            print(f"\n--- [{idx}/{len(rows)}] session={session}  id={row['id']}")
            print(f"    old title: {row['old_title']}")

            record = {
                "id": row["id"], "session": session, "old_title": row["old_title"],
                "content": row.get("content", ""),
                "model": cfg["label"], "model_id": cfg["model_id"],
                "updated_title": "", "problem_statement": "",
                "input_token": 0, "output_token": 0, "total_token": 0,
                "input_cost": 0.0, "output_cost": 0.0, "total_cost": 0.0,
                "llm_calls": 0, "retried": "no", "retry_reason": "",
                "latency_sec": 0.0, "stop_reason": "",
                "chat_rows": 0, "chat_chars": 0, "chat_used": "no",
                "raw_text_preview": "", "error": "",
            }

            try:
                # ---------- build the conversation ----------
                chat_messages = []
                if args.input_mode == "chat":
                    if session not in chat_cache:
                        chat_cache[session] = (file_chats.get(session, ([], 0, 0))
                                               if file_chats else get_chat_messages(session))
                    chat_messages, chat_rows, chat_chars = chat_cache[session]
                    record["chat_rows"] = chat_rows
                    record["chat_chars"] = chat_chars
                    if chat_rows == 0 or chat_chars < MIN_CHAT_CHARS:
                        # fall back to title-only, but flag it
                        chat_messages = []
                        record["error"] = (f"no usable chat ({chat_rows} rows, {chat_chars} chars) "
                                           f"- fell back to title-only")
                        print(f"    ~ {record['error']}")
                    else:
                        record["chat_used"] = "yes"
                        print(f"    chat: {chat_rows} db rows -> {len(chat_messages)} turns")

                # No chat for this session, but the sheet carries a written story
                # narrative -> use that as the source material (single user turn).
                if not chat_messages and (row.get("content") or "").strip():
                    content = row["content"].strip()
                    chat_messages = [{"role": "user", "content": [{"text": content}]}]
                    record["chat_used"] = "content"
                    record["chat_rows"] = 0
                    record["chat_chars"] = len(content)
                    record["error"] = ""
                    print(f"    content: {len(content)} chars from the sheet's `content` column")

                title_block = render_title_block(prompts["title_template"], row)
                # NOTE: build a per-row prompt in its OWN variable. Reassigning
                # `system_prompt` here would append to the outer variable on every
                # row, so by row 7 the prompt carried all 7 old titles at once.
                row_system_prompt = f"""
                {system_prompt}
                This is old title which was generated, refine this title as per the prompt instructions: {title_block}
"""
                messages = build_messages(chat_messages, '')
                record["chat_turns"] = len(messages)

                if args.show_input:
                    print("    INPUT MESSAGES:")
                    print(dumps(messages))

                # ---------- attempt loop: 1 original + up to 1 redo ----------
                title = problem = ""
                attempts_log = []
                for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
                    payload = build_payload(cfg["model_id"], row_system_prompt, messages,
                                            tool_config, temperature, top_p, max_tokens)
                    response, latency = call_bedrock(client, payload)

                    print(f"    ===== RAW BEDROCK RESPONSE (attempt {attempt}) =====")
                    print(dumps(response))
                    print("    ==================================================")

                    in_tok, out_tok, tot_tok, in_cost, out_cost = usage_and_cost(response, cfg)
                    record["input_token"] += in_tok
                    record["output_token"] += out_tok
                    record["total_token"] += tot_tok
                    record["input_cost"] = round(record["input_cost"] + in_cost, 8)
                    record["output_cost"] = round(record["output_cost"] + out_cost, 8)
                    record["total_cost"] = round(record["input_cost"] + record["output_cost"], 8)
                    record["llm_calls"] += 1
                    record["latency_sec"] = round(record["latency_sec"] + latency, 2)
                    record["stop_reason"] = response.get("stopReason", "")

                    title, problem, _parsed, raw_text = parse_title(response)

                    raw_fh.write(json.dumps({
                        "session": session, "model": cfg["label"], "attempt": attempt,
                        "input_mode": args.input_mode, "chat_used": record["chat_used"],
                        "input_messages": messages, "response": response,
                    }, ensure_ascii=False, default=_json_default) + "\n")
                    raw_fh.flush()

                    attempts_log.append({"attempt": attempt, "title": title, "problem": bool(problem),
                                         "tokens": tot_tok, "stop_reason": record["stop_reason"]})

                    missing = []
                    if not title:
                        missing.append("title")
                    if not problem and not args.title_only:
                        missing.append("problem_statement")

                    if not missing:
                        print(f"    NEW title : {title}")
                        print(f"    problem   : {problem[:120]}")
                        break

                    reason = "empty " + " + ".join(missing)
                    preview = " ".join((raw_text or "").split())[:300]
                    record["raw_text_preview"] = preview
                    print(f"    !! attempt {attempt}: {reason}")
                    if preview:
                        print(f"    !! text was: {preview[:160]}")

                    if attempt < MAX_LLM_ATTEMPTS:
                        record["retried"] = "yes"
                        record["retry_reason"] = reason
                        messages = build_retry_messages(messages, raw_text, prompts["retry_message"])
                        print(f"    -> retrying once with the configured retry message")
                        time.sleep(SLEEP_BETWEEN_CALLS)
                    else:
                        record["error"] = f"{reason} after {record['llm_calls']} call(s)"

                record["updated_title"] = title
                record["problem_statement"] = problem
                record["attempts"] = json.dumps(attempts_log, ensure_ascii=False)

                print(f"    tokens    : in={record['input_token']} out={record['output_token']} "
                      f"total={record['total_token']}  (calls={record['llm_calls']})")
                print(f"    cost      : total=${record['total_cost']:.6f}")

                if title and (problem or args.title_only):
                    run_log["passed"][cfg["label"]].append(session)
                else:
                    run_log["failed"][cfg["label"]].append(
                        {"session": session, "reason": record["error"] or "empty output"})

            except Exception as e:                              # noqa: BLE001
                record["error"] = f"{type(e).__name__}: {e}"
                print(f"    !! FAILED: {record['error']}")
                traceback.print_exc()
                run_log["failed"][cfg["label"]].append({"session": session, "reason": record["error"]})

            results[model_key].append(record)
            time.sleep(SLEEP_BETWEEN_CALLS)

        p = len(run_log["passed"][cfg["label"]])
        f = len(run_log["failed"][cfg["label"]])
        retried = sum(1 for r in results[model_key] if r["retried"] == "yes")
        print(f"\n>>> {cfg['label']}: passed={p} failed={f} retried={retried} | "
              f"tokens in={sum(r['input_token'] for r in results[model_key])} "
              f"out={sum(r['output_token'] for r in results[model_key])} | "
              f"cost=${sum(r['total_cost'] for r in results[model_key]):.6f}\n")

    raw_fh.close()
    # write_excel merges rows carried over from a previous workbook into its own copy.
    # The run log must describe THIS run only, so it gets the untouched records.
    write_excel(results, rows, out_dir / args.out_file, all_rows=all_rows)
    write_run_log(run_log, results, out_dir / RUN_LOG)
    print(f"\n[done] raw responses -> {out_dir / RAW_JSONL}")


def write_run_log(run_log, results, path):
    summary = {}
    for model_key, records in results.items():
        label = MODELS[model_key]["label"]
        summary[label] = {
            "passed_count": len(run_log["passed"].get(label, [])),
            "failed_count": len(run_log["failed"].get(label, [])),
            "retried_count": sum(1 for r in records if r.get("retried") == "yes"),
            "total_llm_calls": sum(r.get("llm_calls", 0) for r in records),
            "total_tokens": sum(r.get("total_token", 0) for r in records),
            "total_cost": round(sum(r.get("total_cost", 0.0) for r in records), 8),
            "passed_sessions": run_log["passed"].get(label, []),
            "failed_sessions": run_log["failed"].get(label, []),
        }

    Path(path).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 90)
    print("RUN LOG")
    print("=" * 90)
    for label, s in summary.items():
        print(f"\n{label}: passed={s['passed_count']} failed={s['failed_count']} "
              f"retried={s['retried_count']} calls={s['total_llm_calls']} "
              f"tokens={s['total_tokens']} cost=${s['total_cost']:.6f}")
        for f in s["failed_sessions"]:
            print(f"   FAILED {f['session']}: {f['reason']}")
    print(f"\n[done] run log -> {path}")


# --------------------------------------------------------------------------- #
#                               DIAGNOSTICS                                    #
# --------------------------------------------------------------------------- #

def db_info(rows):
    from django.conf import settings
    from django.db import connection

    print("=" * 80); print("DATABASE TARGET"); print("=" * 80)
    for alias, cfg in settings.DATABASES.items():
        print(f"  alias={alias} engine={cfg.get('ENGINE')} name={cfg.get('NAME')} "
              f"host={cfg.get('HOST') or '(local)'}:{cfg.get('PORT') or ''} user={cfg.get('USER')}")
    print(f"  vendor: {connection.vendor}")

    print("\n" + "=" * 80); print("TABLE COUNTS"); print("=" * 80)
    print(f"  CompanyChat rows            : {CompanyChat.objects.count()}")
    print(f"  CompanyChat distinct sessions: {CompanyChat.objects.values('session').distinct().count()}")
    try:
        from chatbot.models import ChatSession
        sheet_sessions = [r["session"] for r in rows]
        hits = ChatSession.objects.filter(session__in=sheet_sessions)
        print(f"  ChatSession rows            : {ChatSession.objects.count()}")
        print(f"  ChatSession matching sheet  : {hits.count()} / {len(sheet_sessions)}")
    except Exception as e:                                      # noqa: BLE001
        print(f"  ChatSession lookup failed: {e}")

    print("\n" + "=" * 80); print("SAMPLE CompanyChat.session VALUES"); print("=" * 80)
    sample = list(CompanyChat.objects.values_list("session", flat=True).distinct()[:10])
    if not sample:
        print("  (none - CompanyChat is empty in this database)")
    for s in sample:
        print(f"  {s}  ({CompanyChat.objects.filter(session=s).count()} rows)")


def check_chats_from_files(rows, file_chats):
    print(f"{'session':36} {'rows':>7} {'turns':>7} {'chars':>8}  status")
    print("-" * 80)
    ok = missing = thin = 0
    for row in rows:
        messages, n_rows, chars = file_chats.get(row["session"], ([], 0, 0))
        if n_rows == 0:
            status, missing = "MISSING - session not in the chat files", missing + 1
        elif chars < MIN_CHAT_CHARS:
            status, thin = "THIN - below MIN_CHAT_CHARS", thin + 1
        else:
            status, ok = "ok", ok + 1
        print(f"{row['session']:36} {n_rows:>7} {len(messages):>7} {chars:>8}  {status}")
    print("-" * 80)
    print(f"usable: {ok}   missing: {missing}   thin: {thin}   (of {len(rows)})")


def check_chats(rows):
    print(f"{'session':36} {'db_rows':>8} {'turns':>7} {'chars':>8}  status")
    print("-" * 80)
    ok = empty = thin = 0
    for row in rows:
        session = row["session"]
        try:
            messages, chat_count, chat_chars = get_chat_messages(session)
        except Exception as e:                                  # noqa: BLE001
            print(f"{session:36} {'ERR':>8} {'-':>7} {'-':>8}  {type(e).__name__}: {e}")
            continue
        if chat_count == 0:
            status, empty = "EMPTY - no CompanyChat rows", empty + 1
        elif chat_chars < MIN_CHAT_CHARS:
            status, thin = "THIN - below MIN_CHAT_CHARS", thin + 1
        else:
            status, ok = "ok", ok + 1
        print(f"{session:36} {chat_count:>8} {len(messages):>7} {chat_chars:>8}  {status}")
    print("-" * 80)
    print(f"usable: {ok}   empty: {empty}   thin: {thin}   (of {len(rows)})")


# --------------------------------------------------------------------------- #
#                                  EXCEL                                       #
# --------------------------------------------------------------------------- #

def load_previous_model_sheets(xlsx_path):
    import pandas as pd
    previous = {}
    if not Path(xlsx_path).exists():
        return previous
    label_to_key = {cfg["label"]: key for key, cfg in MODELS.items()}
    try:
        xl = pd.ExcelFile(xlsx_path)
    except Exception as e:                                      # noqa: BLE001
        print(f"[warn] could not read existing workbook ({e}); it will be overwritten")
        return previous
    for sheet in xl.sheet_names:
        key = label_to_key.get(sheet)
        if not key:
            continue
        try:
            df = pd.read_excel(xl, sheet)
            # sheets are written with display headers; map them back to internal names
            df = df.rename(columns={v: k for k, v in SHEET_COLUMNS.items()})
            if "id" in df.columns:
                df = df[df["id"].astype(str) != "TOTAL"]
            records = df.where(df.notna(), "").to_dict(orient="records")
            if records:
                previous[key] = records
        except Exception as e:                                  # noqa: BLE001
            print(f"[warn] could not read sheet '{sheet}': {e}")
    return previous


def write_excel(results_in, rows, xlsx_path, all_rows=None):
    import pandas as pd

    # Work on a copy: the caller's dict must keep only this run's records, otherwise
    # the run log would sum carried-forward rows from earlier runs.
    results = {k: list(v) for k, v in results_in.items()}

    previous = load_previous_model_sheets(xlsx_path)
    for key, old_records in previous.items():
        if key not in results:
            results[key] = old_records
            print(f"[merge] carried forward {len(old_records)} row(s) for '{MODELS[key]['label']}'")
        else:
            # sheets no longer carry `session`, so rows are keyed by `id`
            fresh = {str(r.get("id")) for r in results[key]}
            kept = [r for r in old_records if str(r.get("id")) not in fresh]
            if kept:
                results[key] = kept + results[key]
                print(f"[merge] kept {len(kept)} untouched row(s) for '{MODELS[key]['label']}'")

    order = {str(r["id"]): i for i, r in enumerate(all_rows or rows)}
    for key in results:
        results[key] = sorted(results[key], key=lambda r: order.get(str(r.get("id")), 10 ** 6))

    internal = list(SHEET_COLUMNS.keys())
    numeric = ["input_token", "output_token", "total_token",
               "input_cost", "output_cost", "total_cost"]

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for model_key, records in results.items():
            label = MODELS[model_key]["label"]
            df = pd.DataFrame(records).reindex(columns=internal)
            totals = {c: "" for c in internal}
            totals["id"] = "TOTAL"
            for c in numeric:
                totals[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).sum()
            df = pd.concat([df, pd.DataFrame([totals])], ignore_index=True)
            df = df.rename(columns=SHEET_COLUMNS)
            df.to_excel(writer, sheet_name=label[:31], index=False)

        by_session = {}
        for r in (all_rows or rows):
            by_session[r["session"]] = {"id": r["id"], "Old Title": r["old_title"],
                                        "Content": r.get("content", "")}
        for model_key, records in results.items():
            label = MODELS[model_key]["label"]
            for rec in records:
                slot = by_session.setdefault(rec.get("session", rec.get("id", "")),
                                             {"id": rec.get("id", ""),
                                              "Old Title": rec.get("old_title", ""),
                                              "Content": rec.get("content", "")})
                slot[f"{label} Updated title"] = rec.get("updated_title", "")
                slot[f"{label} Input token"] = rec.get("input_token", "")
                slot[f"{label} Output token"] = rec.get("output_token", "")
                slot[f"{label} Total token"] = rec.get("total_token", "")
                slot[f"{label} Input cost"] = rec.get("input_cost", "")
                slot[f"{label} Output cost"] = rec.get("output_cost", "")
                slot[f"{label} Total cost"] = rec.get("total_cost", "")

        comp = pd.DataFrame(list(by_session.values()))
        if not comp.empty:
            totals = {c: "" for c in comp.columns}
            totals["id"] = "TOTAL"
            for c in comp.columns:
                if c.endswith(("token", "cost")):
                    totals[c] = pd.to_numeric(comp[c], errors="coerce").fillna(0).sum()
            comp = pd.concat([comp, pd.DataFrame([totals])], ignore_index=True)
        comp.to_excel(writer, sheet_name="comparison", index=False)

    print(f"[done] excel -> {xlsx_path}")


def parse_args():
    p = argparse.ArgumentParser(description="Regenerate story titles and compare LLaMA vs Haiku on Bedrock.")
    p.add_argument("--csv", default=CSV_PATH)
    p.add_argument("--prompt-file", default=PROMPT_FILE,
                   help="JSON/YAML holding title_template and retry_message")
    p.add_argument("--bot-file", default=None,
                   help="bot config JSON to use for this run (overrides BOT_JSON_PATH). "
                        "Lets you run each model against its own tuned bot.")
    p.add_argument("--title-only", action="store_true",
                   help="treat a non-empty title alone as success: do not require "
                        "problem_statement and do not retry when it is missing. Use with "
                        "title-only bot prompts. problem_statement is still captured and "
                        "written whenever the model does return it.")
    p.add_argument("--force-tool-choice", action="store_true",
                   help="force the model to call the tool (Anthropic only; Bedrock rejects "
                        "toolChoice for Meta models)")
    p.add_argument("--models", nargs="+", default=DEFAULT_MODEL_ORDER, choices=list(MODELS.keys()))
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--sessions", nargs="+", default=None)
    p.add_argument("--out-dir", default=OUT_DIR)
    p.add_argument("--out-file", default=OUT_XLSX)
    p.add_argument("--input-mode", choices=["title", "chat"], default=INPUT_MODE)
    p.add_argument("--chat-files", nargs="+", default=None,
                   help="exported CompanyChat dumps (.xlsx/.csv, globs ok). Supplying these "
                        "switches input-mode to 'chat' and avoids needing DB access")
    p.add_argument("--show-input", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="print the exact rendered request and exit without calling Bedrock")
    p.add_argument("--check-chats", action="store_true")
    p.add_argument("--db-info", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    run(parse_args())

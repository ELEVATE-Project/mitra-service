#!/usr/bin/env python3
"""Build a Mitra bot-config JSON from state_<int>_prompt.txt files + a question-bank CSV.

Subcommands:
  check  --dir D                 validate dir, list CSV candidates (JSON report on stdout)
  route  --name N                print route derived from bot name
  build  --dir D --csv C --name N [--route R] [--max-token I] [--temperature F] [--top-k I] [--force]
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

STATE_FILE_RE = re.compile(r"^state_(\d+)_prompt\.txt$")
NEAR_STATE_RE = re.compile(r"^state.*prompt.*\.txt$", re.IGNORECASE)
STATE_TAG_RE = re.compile(r'<state\s+id="([^"]*)"')
ROUTE_RE = re.compile(r"^/[a-z0-9]+(_[a-z0-9]+)*$")
STEP_HEADER = "step number"
QUESTION_HEADER = "main question"


def derive_route(name):
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return "/" + slug if slug else None


def scan_states(d):
    """Return (states{step: name}, warnings, errors)."""
    states, warnings, errors = {}, [], []
    if not (d / "global_context.txt").is_file():
        errors.append("global_context.txt missing")
    for p in sorted(d.iterdir()):
        if not p.is_file():
            continue
        m = STATE_FILE_RE.match(p.name)
        if not m:
            if NEAR_STATE_RE.match(p.name):
                warnings.append(f"ignored near-match file: {p.name}")
            continue
        step = int(m.group(1))
        if step in states:
            errors.append(f"duplicate state step {step}: {p.name}")
            continue
        ids = STATE_TAG_RE.findall(p.read_text(encoding="utf-8"))
        if len(ids) != 1:
            errors.append(f'{p.name}: expected exactly 1 <state id="..."> tag, found {len(ids)}')
            continue
        if not ids[0]:
            errors.append(f"{p.name}: empty state id")
            continue
        states[step] = ids[0]
    if not any(STATE_FILE_RE.match(p.name) for p in d.iterdir() if p.is_file()):
        errors.append("no state_<int>_prompt.txt files found")
    return states, warnings, errors


def parse_step(raw):
    s = raw.strip()
    if not s:
        return None
    if re.fullmatch(r"\d+", s):
        return int(s)
    try:
        f = float(s)
    except ValueError:
        raise ValueError(f"invalid step value {raw!r}")
    if f < 0 or not f.is_integer():
        raise ValueError(f"invalid step value {raw!r}")
    return int(f)


def read_csv(path):
    """Return (questions{step: text}, errors)."""
    questions, errors = {}, []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return {}, [f"{path}: empty CSV"]
        lowered = [h.lower() for h in header]
        missing = [h for h in (STEP_HEADER, QUESTION_HEADER) if h not in lowered]
        if missing:
            return {}, [f"{path}: missing column(s) {missing}; headers={header}"]
        si, qi = lowered.index(STEP_HEADER), lowered.index(QUESTION_HEADER)
        for line_no, row in enumerate(reader, start=2):
            cell = row[si] if si < len(row) else ""
            try:
                step = parse_step(cell)
            except ValueError as e:
                errors.append(f"CSV row {line_no}: {e}")
                continue
            if step is None:
                continue
            if step in questions:
                errors.append(f"CSV row {line_no}: duplicate step {step}")
                continue
            questions[step] = (row[qi] if qi < len(row) else "").strip()
    return questions, errors


def cmd_check(args):
    d = Path(args.dir).resolve()
    states, warnings, errors = scan_states(d)
    report = {
        "dir": str(d),
        "states": {str(k): v for k, v in sorted(states.items())},
        "csv_candidates": sorted(p.name for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".csv"),
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if errors else 0


def cmd_route(args):
    r = derive_route(args.name)
    if not r:
        print("error: name has no alphanumeric chars", file=sys.stderr)
        return 1
    print(r)
    return 0


def cmd_build(args):
    d = Path(args.dir).resolve()
    errors = []

    name = args.name.strip()
    if not name:
        errors.append("name required")
    route = args.route if args.route is not None else derive_route(name)
    if not route or not ROUTE_RE.match(route):
        errors.append(f"invalid route {route!r}; must match {ROUTE_RE.pattern}")
    if args.max_token is not None and args.max_token <= 0:
        errors.append("max_token must be positive int")
    if args.top_k is not None and args.top_k <= 0:
        errors.append("top_k must be positive int")
    if args.temperature is not None and not (0.0 <= args.temperature <= 1.0):
        errors.append("bot_temperature must be float in [0.0, 1.0]")

    states, warnings, state_errors = scan_states(d)
    errors += state_errors
    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = d / csv_path
    if csv_path.is_file():
        questions, csv_errors = read_csv(csv_path)
        errors += csv_errors
    else:
        questions = {}
        errors.append(f"CSV not found: {csv_path}")

    if questions or states:
        for s in sorted(set(states) - set(questions)):
            errors.append(f"state_{s}_prompt.txt has no CSV row")
        for s in sorted(set(questions) - set(states)):
            errors.append(f"CSV step {s} has no state file")
        for s in sorted(set(states) & set(questions)):
            if not questions[s]:
                errors.append(f"CSV step {s}: empty Main Question")

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 1

    out = d / f"{route.lstrip('/')}.json"
    if out.exists() and not args.force:
        print(f"exists: {out}", file=sys.stderr)
        return 2

    data = {"name": name}
    if args.max_token is not None:
        data["max_token"] = args.max_token
    if args.temperature is not None:
        data["bot_temperature"] = args.temperature
    if args.top_k is not None:
        data["top_k"] = args.top_k
    data["route"] = route
    data["state_machines"] = [
        {"step": s, "name": states[s], "bot_question": questions[s]} for s in sorted(states)
    ]
    out.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    print(out)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check")
    c.add_argument("--dir", default=".")
    c.set_defaults(fn=cmd_check)

    r = sub.add_parser("route")
    r.add_argument("--name", required=True)
    r.set_defaults(fn=cmd_route)

    b = sub.add_parser("build")
    b.add_argument("--dir", default=".")
    b.add_argument("--csv", required=True)
    b.add_argument("--name", required=True)
    b.add_argument("--route")
    b.add_argument("--max-token", type=int)
    b.add_argument("--temperature", type=float)
    b.add_argument("--top-k", type=int)
    b.add_argument("--force", action="store_true")
    b.set_defaults(fn=cmd_build)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()

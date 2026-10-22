#!/usr/bin/env python3
"""
Parse a Mitra question-bank CSV into flat question records.

Required columns (matched by header name, case/space-insensitive, any order):
  Step Number, Main Question, Expected responses, When To Probe

Output: JSON array to stdout (or --out file), one record per data row:
  {
    "step_number": "7",
    "main_question": "...",        # lowercased
    "expected_responses": "...",   # lowercased
    "when_to_probe": "..."         # lowercased, "" if blank
  }

Cleaning:
- Header row is the first row containing "Main Question"; rows above it skipped.
- Stray wrapping quotes from spreadsheet exports ('"Frequency ..."') stripped.
- Multi-line cells flattened: main question lines joined with " ", other
  fields with "; " so list items stay distinct.
- Fully blank rows skipped. A row with content but no Step Number, or a
  duplicate Step Number, is an error.
"""

import csv
import json
import re
import sys
import argparse

# output field -> normalized header name (lowercase, alnum only)
COLUMNS = {
    "step_number": "stepnumber",
    "main_question": "mainquestion",
    "expected_responses": "expectedresponses",
    "when_to_probe": "whentoprobe",
}


def normalize_header(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def clean(s: str, line_sep: str, lower: bool = True) -> str:
    """Collapse whitespace; join non-blank lines with line_sep; optionally lowercase."""
    lines = [" ".join(ln.split()) for ln in (s or "").splitlines()]
    s = line_sep.join(ln for ln in lines if ln)
    # strip stray wrapping quotes left by spreadsheet exports
    while len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1].strip()
    return s.lower() if lower else s


def find_header(rows: list) -> tuple:
    """Return (header_index, {field: column_index})."""
    for i, row in enumerate(rows):
        normed = [normalize_header(c) for c in row]
        if COLUMNS["main_question"] not in normed:
            continue
        missing = [f for f, h in COLUMNS.items() if h not in normed]
        if missing:
            raise ValueError(f"Header row {i + 1} missing columns: {missing}")
        return i, {f: normed.index(h) for f, h in COLUMNS.items()}
    raise ValueError("No header row with a 'Main Question' column found")


def parse(csv_path: str) -> list:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    if not rows:
        return []

    header_idx, colmap = find_header(rows)

    records = []
    seen = set()

    for line_no, raw in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        rec = {}
        for field, j in colmap.items():
            cell = raw[j] if j < len(raw) else ""
            is_question = field == "main_question"
            rec[field] = clean(
                cell,
                line_sep=" " if is_question else "; ",
                lower=not is_question,
            )

        if not any(rec.values()):
            continue  # fully blank row

        step = rec["step_number"]
        if not step:
            raise ValueError(f"CSV line {line_no}: row has no Step Number")
        if step in seen:
            raise ValueError(f"CSV line {line_no}: duplicate Step Number {step}")
        seen.add(step)

        records.append(rec)

    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args()

    try:
        result = parse(args.csv_path)
    except ValueError as e:
        sys.exit(f"error: {e}")

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Wrote {len(result)} questions to {args.out}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()

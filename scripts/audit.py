#!/usr/bin/env python3
"""
Independent coverage audit, so a silently-broken schedule cannot go unnoticed.

For every round that is fully published in questions.csv, check that this
repository holds answers/round-XXXX.json and that the file is valid, complete
and well-named. Prints a report and exits non-zero if anything is wrong, which
the watchdog workflow turns into an emailed GitHub issue.

Usage:  python3 scripts/audit.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solve import (  # noqa: E402
    ANSWERS_DIR,
    LETTERS,
    answer_path,
    fetch_questions,
    load_state,
    parse_rows,
    released_at,
)

GRADED_FIRST_ROUND = 49
GRADED_LAST_ROUND = 168


def main() -> int:
    rows = parse_rows(fetch_questions())
    if not rows:
        print("ERROR: questions.csv parsed to zero rows")
        return 1

    by_round = defaultdict(list)
    for r in rows:
        by_round[int(str(r["round_id"]).strip())].append(r)

    now = dt.datetime.now(dt.timezone.utc)
    problems: list[str] = []
    ok = 0
    partial_feed = []

    for round_id in sorted(by_round):
        rrows = by_round[round_id]
        if len(rrows) < 25:
            partial_feed.append(f"round {round_id}: only {len(rrows)}/25 questions in feed")
            continue

        path = answer_path(round_id)
        label = f"round {round_id} ({os.path.basename(path)})"

        if not os.path.exists(path):
            rel = released_at(rrows)
            age = f"{(now - rel).total_seconds() / 3600:.1f}h old" if rel else "age unknown"
            problems.append(f"MISSING  {label} - {age}")
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"INVALID  {label} - not valid JSON: {exc}")
            continue

        answers = data.get("answers")
        if not isinstance(answers, dict):
            problems.append(f"INVALID  {label} - no answers object")
            continue
        bad = [f"q{i}" for i in range(1, 26) if answers.get(f"q{i}") not in LETTERS]
        if bad:
            problems.append(f"INVALID  {label} - bad or missing keys: {bad}")
            continue
        ok += 1

    # Stray files that do not correspond to a published round.
    if os.path.isdir(ANSWERS_DIR):
        for name in sorted(os.listdir(ANSWERS_DIR)):
            if not name.startswith("round-") or not name.endswith(".json"):
                continue
            stem = name[len("round-"):-len(".json")]
            if len(stem) != 4 or not stem.isdigit():
                problems.append(f"MISNAMED {name} - must be round-XXXX.json (four digits)")

    state = load_state()
    flagged = state.get("flagged", {})

    graded_present = sorted(
        r for r in by_round
        if GRADED_FIRST_ROUND <= r <= GRADED_LAST_ROUND and len(by_round[r]) >= 25
    )

    print(f"audit at {now.isoformat()}")
    print(f"rounds fully published in feed : {len([r for r in by_round if len(by_round[r]) >= 25])}")
    print(f"  of which graded (49-168)     : {len(graded_present)}")
    print(f"valid answer files             : {ok}")
    print(f"rounds containing a guess      : {len(flagged)} {sorted(flagged) if flagged else ''}")
    if partial_feed:
        print("\nstill publishing (not a problem):")
        for p in partial_feed:
            print(f"  {p}")

    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for p in problems:
            print(f"  {p}")
        return 1
    if flagged:
        print("\nno missing files, but some rounds contain a guessed answer")
        return 2

    print("\nOK: every published round has a valid, complete answer file")
    return 0


if __name__ == "__main__":
    sys.exit(main())

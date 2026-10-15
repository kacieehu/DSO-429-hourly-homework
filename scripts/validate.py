#!/usr/bin/env python3
"""
Score the solver against the published practice answer keys (rounds 1-48).

This is the regression test: it must report 1200/1200 before the graded rounds
start, and the hourly workflow runs it too, so a change to the solver that
breaks a template fails loudly instead of quietly guessing.

Usage:  python3 scripts/validate.py
"""

from __future__ import annotations

import collections
import csv
import io
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solve import LETTERS, fetch_questions, parse_rows, pick_letter  # noqa: E402

KEYS_URL = "https://raw.githubusercontent.com/FaisalXL/dso429-hourly-quiz/main/practice_keys.csv"


def fetch_keys() -> dict:
    req = urllib.request.Request(KEYS_URL, headers={"User-Agent": "dso429-hw3-solver"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8-sig", errors="replace")
    keys = {}
    for r in csv.DictReader(io.StringIO(text)):
        try:
            keys[(int(r["round_id"]), int(r["q_index"]))] = r["answer"].strip().upper()
        except (ValueError, KeyError):
            continue
    return keys


def skeleton(text: str) -> str:
    t = re.sub(r"[\d,]+\.?\d*", "#", text)
    t = re.sub(r"(January|February|March|April|May|June|July|August|"
               r"September|October|November|December)", "MON", t)
    return t[:70]


def main() -> int:
    rows = parse_rows(fetch_questions())
    keys = fetch_keys()
    if not keys:
        print("ERROR: could not load practice_keys.csv")
        return 1

    total = right = unsolved = 0
    per_template = collections.defaultdict(lambda: [0, 0])  # [right, total]
    failures = []

    for r in rows:
        rid, qi = int(r["round_id"]), int(r["q_index"])
        gold = keys.get((rid, qi))
        if gold not in LETTERS:
            continue
        q = r["question_text"]
        opts = [r["option_a"], r["option_b"], r["option_c"], r["option_d"]]
        try:
            got, _conf = pick_letter(q, opts)
        except Exception as exc:  # noqa: BLE001
            got = None
            failures.append((rid, qi, q, gold, f"error: {exc}"))

        total += 1
        tmpl = skeleton(q)
        per_template[tmpl][1] += 1
        if got == gold:
            right += 1
            per_template[tmpl][0] += 1
        else:
            if got is None:
                unsolved += 1
            if len(failures) < 40:
                failures.append((rid, qi, q, gold, got))

    print(f"\nscored {right}/{total} practice questions "
          f"({right / total * 100:.2f}%)" if total else "no questions scored")
    print(f"unmatched templates (no answer computed): {unsolved}")

    print("\nper template:")
    for tmpl, (ok, tot) in sorted(per_template.items(), key=lambda kv: -kv[1][1]):
        mark = "ok " if ok == tot else "BAD"
        print(f"  {mark} {ok:4d}/{tot:4d}  {tmpl}")

    if failures:
        print(f"\nfirst {len(failures)} mismatches:")
        for rid, qi, q, gold, got in failures:
            print(f"  r{rid} q{qi}: expected {gold}, got {got}")
            print(f"      {q}")

    if total == 0:
        print("\nFAIL: nothing scored")
        return 1
    if right != total:
        print("\nFAIL: solver is not exact on the practice set")
        return 1
    print("\nPASS: 100% on all practice rounds")
    return 0


if __name__ == "__main__":
    sys.exit(main())

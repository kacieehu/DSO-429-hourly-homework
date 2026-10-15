#!/usr/bin/env python3
"""
Leave-one-template-out evaluation of the network-free generic fallback.

This answers the question "what actually happens if the graded rounds contain a
question type I have never seen?" by pretending, one template at a time, that
the template solver does not know it, and scoring scripts/generic.py on exactly
those questions against the published practice keys.

It is a real measurement, not a claim: the number it prints is how the fallback
would have done on each of the twelve types had that type been brand new.

Usage:  python3 scripts/test_generic.py
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
from generic import solve_generic  # noqa: E402
from solve import LETTERS, fetch_questions, parse_rows  # noqa: E402

KEYS_URL = ("https://raw.githubusercontent.com/FaisalXL/dso429-hourly-quiz/"
            "main/practice_keys.csv")


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
    return t[:60]


USE_HINTS = "--no-hints" not in sys.argv


def main() -> int:
    print("mode:", "WITH keyword hints" if USE_HINTS
          else "NO keyword hints (pure structural search)")
    rows = parse_rows(fetch_questions())
    keys = fetch_keys()
    if not rows or not keys:
        print("ERROR: could not load the feed or the keys")
        return 1

    per = collections.defaultdict(lambda: {"right": 0, "total": 0, "abstain": 0})

    for r in rows:
        rid, qi = int(r["round_id"]), int(r["q_index"])
        gold = keys.get((rid, qi))
        if gold not in LETTERS:
            continue
        q = r["question_text"]
        options = [r["option_a"], r["option_b"], r["option_c"], r["option_d"]]

        got, _label = solve_generic(q, options, use_hints=USE_HINTS)

        bucket = per[skeleton(q)]
        bucket["total"] += 1
        if got is None:
            bucket["abstain"] += 1
        elif got == gold:
            bucket["right"] += 1

    print("\nHow the network-free fallback would do on each type, if that type")
    print("had never been seen before (scored against the practice keys):\n")
    print(f"  {'correct':>9}  {'abstain':>7}  {'of':>5}   template")

    tot_right = tot_total = tot_abstain = 0
    for tmpl, b in sorted(per.items(), key=lambda kv: -kv[1]["total"]):
        pct = b["right"] / b["total"] * 100 if b["total"] else 0
        print(f"  {b['right']:4d} {pct:5.1f}%  {b['abstain']:7d}  {b['total']:5d}   {tmpl}")
        tot_right += b["right"]
        tot_total += b["total"]
        tot_abstain += b["abstain"]

    overall = tot_right / tot_total * 100 if tot_total else 0
    print(f"\n  overall: {tot_right}/{tot_total} = {overall:.1f}% correct, "
          f"{tot_abstain} abstained ({tot_abstain / tot_total * 100:.1f}%)")
    print("\n  (Abstentions fall through to a fixed letter, worth ~25% each.)")
    expected = (tot_right + tot_abstain * 0.25) / tot_total * 100 if tot_total else 0
    print(f"  expected score on a brand-new type: ~{expected:.1f}%")
    print("  a blind guess would be 25%")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Edge cases that do NOT appear in practice rounds 1-48 but plausibly could in
the graded rounds: the mirror-image wording of a template, the other category
in a probability question, a geometric instead of arithmetic series, a leap
year, a year boundary, and negative results.

Runs offline - no network - so it is a fast guard in every workflow run.

Usage:  python3 scripts/test_variants.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solve import pick_letter  # noqa: E402

CASES = [
    ("second channel of a ratio split",
     "A $900.00 marketing budget is split between two channels in the ratio 2:5. "
     "What does the second channel receive?",
     ["$257.14", "$128.57", "$360.00", "$642.86"], "D"),

    ("probability of the middle category",
     "A support queue holds 25 billing tickets, 6 technical tickets and 10 account "
     "tickets. If one is drawn at random, what is the probability it is a technical ticket?",
     ["61.0%", "14.6%", "24.4%", "75.6%"], "B"),

    ("probability of the last category",
     "A support queue holds 25 billing tickets, 6 technical tickets and 10 account "
     "tickets. If one is drawn at random, what is the probability it is an account ticket?",
     ["61.0%", "14.6%", "24.4%", "75.6%"], "C"),

    ("geometric series",
     "A monthly headcount series runs 2, 6, 18, 54, 162. If the pattern continues, "
     "what is the next value?",
     ["486", "324", "216", "648"], "A"),

    ("quadratic series",
     "A monthly headcount series runs 1, 4, 9, 16, 25. If the pattern continues, "
     "what is the next value?",
     ["30", "36", "35", "49"], "B"),

    ("settlement across a leap day",
     "A contract signed on 20 February 2028 has a 10-day settlement period. "
     "On what date does it settle?",
     ["1 March 2028", "2 March 2028", "29 February 2028", "28 February 2028"], "A"),

    ("settlement across a year boundary",
     "A contract signed on 20 December 2026 has a 30-day settlement period. "
     "On what date does it settle?",
     ["19 January 2027", "20 January 2027", "19 January 2026", "18 January 2027"], "A"),

    ("negative percentage change",
     "Quarterly revenue moved from $500.00 to $250.00. What is the percentage change?",
     ["-50.0%", "50.0%", "-100.0%", "200.0%"], "A"),

    ("long compounding horizon",
     "An investment of $1,000.00 grows at 5% compounded annually. "
     "What is its value after 30 years?",
     ["$4,321.94", "$2,500.00", "$1,500.00", "$3,000.00"], "A"),

    ("negative gross margin",
     "A product line generates $100.00 in revenue against $120.00 in cost of goods "
     "sold. What is the gross margin?",
     ["-20.0%", "20.0%", "83.3%", "120.0%"], "A"),
]

# An unrecognised question must return None rather than a confident wrong pick,
# so the round gets flagged and alerted on.
MUST_NOT_SOLVE = [
    "A widget factory uses the Zorblat method. What is the flux capacity?",
]


def main() -> int:
    failures = 0

    for desc, question, options, expected in CASES:
        got, conf = pick_letter(question, options)
        if got == expected:
            print(f"  ok   {desc} -> {got} ({conf})")
        else:
            failures += 1
            print(f"  FAIL {desc} -> got {got}, expected {expected}")
            print(f"       {question}")

    for question in MUST_NOT_SOLVE:
        got, _conf = pick_letter(question, ["1", "2", "3", "4"])
        if got is None:
            print(f"  ok   unknown template correctly flagged, not guessed")
        else:
            failures += 1
            print(f"  FAIL unknown template returned {got} instead of None")

    total = len(CASES) + len(MUST_NOT_SOLVE)
    print(f"\n{total - failures}/{total} variant checks passed")
    if failures:
        print("FAIL")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

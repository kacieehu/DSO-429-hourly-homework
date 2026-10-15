#!/usr/bin/env python3
"""
Prove the LLM safety net is actually reachable and correct.

The deterministic solver answers every known template, so the fallback would
otherwise sit untested until the day a new question type appears - exactly the
wrong moment to discover it is misconfigured. This asks it questions whose
wording deliberately matches no template, and checks the answers.

Exits 0 if the fallback works, 1 if it is reachable but wrong, 2 if no provider
is configured at all (not a failure in itself - the hourly job still runs).

Usage:  python3 scripts/test_llm.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_fallback  # noqa: E402

# Phrased unlike any template in the feed, so pick_letter() cannot solve them
# and only the model can.
CASES = [
    ("A warehouse holds 7 pallets. Each pallet carries 12 cartons, and each "
     "carton holds 4 units. How many units are in the warehouse?",
     ["336", "84", "48", "28"], "A"),

    ("A team of 5 analysts each bill 6 hours at $150 per hour. What is the "
     "total billed?",
     ["$900", "$4,500", "$750", "$3,000"], "B"),

    ("Two machines run in parallel. One completes a job in 6 hours, the other "
     "in 12 hours. Working together, how long does the job take?",
     ["4 hours", "9 hours", "18 hours", "3 hours"], "A"),
]


def main() -> int:
    available = llm_fallback.providers_available()
    print(f"providers configured: {available or 'NONE'}")
    if not available:
        print("No LLM provider is configured.")
        print("The hourly solver still works - this only means a brand-new")
        print("question type would fall back to a fixed letter.")
        return 2

    failures = 0
    for question, options, expected in CASES:
        # Confirm the deterministic solver really cannot do this one, so the
        # test is exercising the model and not the templates.
        from solve import pick_letter
        det, _ = pick_letter(question, options)
        if det is not None:
            print(f"  note: template solver handled this one ({det}); "
                  f"not an LLM test")
            continue

        letter, provider = llm_fallback.answer(question, options)
        if letter == expected:
            print(f"  ok   -> {letter} via {provider}")
        else:
            failures += 1
            print(f"  FAIL -> got {letter} via {provider}, expected {expected}")
            print(f"       {question}")

    if failures:
        print(f"\n{failures} fallback case(s) wrong - the safety net is "
              f"reachable but unreliable")
        return 1
    print("\nPASS: LLM fallback is reachable and answered every case correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Network-free fallback for a question type the template solver does not know.

The idea: these are ordinary business-arithmetic questions, so the answer is
almost always one of a modest number of standard formulas applied to the
numbers in the sentence. Rather than needing to recognise the wording, compute
a ranked list of candidate values and take the most canonical one that lands
exactly on an offered option.

Ranking matters because the wrong answers are usually themselves plausible
formulas (a gross-margin question offers COGS/revenue as a distractor). The
candidates are ordered most-canonical-first and the first exact hit wins.

This is measured honestly by scripts/test_generic.py, which hides one template
at a time from the real solver and scores this code on those questions against
the published practice keys - a genuine "what if this type were new" test.
"""

from __future__ import annotations

import datetime as dt
import itertools
import re

LETTERS = ("A", "B", "C", "D")


def candidates(question: str, nums: list[float], use_hints: bool = True):
    """Return (value, label) candidates, most canonical first.

    Each candidate is computed behind a guard: a formula that overflows,
    divides by zero or produces NaN on this particular question is simply
    skipped, so one bad combination cannot abort the whole search.
    """
    out = []

    def add(fn, label):
        try:
            v = fn()
        except (ZeroDivisionError, OverflowError, ValueError, TypeError):
            return
        if v is None:
            return
        try:
            if v != v or abs(v) == float("inf") or abs(v) > 1e15:
                return
        except (TypeError, OverflowError):
            return
        out.append((float(v), label))

    n = nums
    k = len(n)
    low = question.lower()

    # --- strongly hinted shapes, keyed off a word in the sentence ----------
    # use_hints=False drops all of these, leaving only structural arithmetic.
    # That is the honest "formula I never anticipated" measurement.
    if not use_hints:
        low = ""
    if use_hints and k >= 3:
        a, b, c = n[0], n[1], n[2]
        if "compound" in low or "grows at" in low or "annually" in low:
            add(lambda: a * (1 + b / 100.0) ** c, "compound")
        if "break" in low and b != c:
            add(lambda: a / (b - c), "breakeven")

    if use_hints and k >= 2:
        a, b = n[0], n[1]
        if "margin" in low and a:
            add(lambda: (a - b) / a * 100.0, "margin")
        if ("percentage change" in low or "percent change" in low) and a:
            add(lambda: (b - a) / a * 100.0, "pctchange")
        if "discount" in low:
            add(lambda: a * (1 - b / 100.0), "discount")
        if "markup" in low or "increase" in low:
            add(lambda: a * (1 + b / 100.0), "markup")
        if "tax" in low or "interest" in low:
            add(lambda: a * b / 100.0, "pctof")

    if use_hints and k >= 4 and ("average" in low or "overall" in low):
        a, b, c, d = n[0], n[1], n[2], n[3]
        if a + c:
            add(lambda: (a * b + c * d) / (a + c), "weighted_avg")

    if use_hints and k >= 3 and ("ratio" in low or ":" in question):
        a, b, c = n[0], n[1], n[2]
        if b + c:
            add(lambda: a * b / (b + c), "ratio_first")
            add(lambda: a * c / (b + c), "ratio_second")

    if use_hints and ("probability" in low or "chance" in low):
        total = sum(n)
        if total:
            # the count attached to the category the question names
            m = re.search(r"probability it is an?\s+([a-z]+)", low)
            if m:
                want = m.group(1)
                cm = re.search(r"(\d[\d,]*\.?\d*)\s+" + re.escape(want), low)
                if cm:
                    add(lambda: float(cm.group(1).replace(",", "")) / total * 100.0,
                        "prob_named")
            for i, x in enumerate(n):
                add(lambda: x / total * 100.0, f"prob_{i}")

    # --- sequence continuation --------------------------------------------
    if k >= 3:
        diffs = [n[i + 1] - n[i] for i in range(k - 1)]
        if max(diffs) - min(diffs) < 1e-9:
            add(lambda: n[-1] + diffs[0], "seq_arith")
        if all(abs(x) > 1e-12 for x in n[:-1]):
            ratios = [n[i + 1] / n[i] for i in range(k - 1)]
            if max(ratios) - min(ratios) < 1e-9:
                add(lambda: n[-1] * ratios[0], "seq_geom")
        d2 = [diffs[i + 1] - diffs[i] for i in range(len(diffs) - 1)]
        if d2 and max(d2) - min(d2) < 1e-9:
            add(lambda: n[-1] + diffs[-1] + d2[0], "seq_quad")

    # --- generic two-number arithmetic, canonical order -------------------
    for i, j in itertools.permutations(range(k), 2):
        a, b = n[i], n[j]
        add(lambda: a * b, f"mul_{i}{j}")
    for i, j in itertools.permutations(range(k), 2):
        a, b = n[i], n[j]
        if b:
            add(lambda: a / b, f"div_{i}{j}")
        if a:
            add(lambda: (a - b) / a * 100.0, f"relchg_{i}{j}")
        if b:
            add(lambda: a / b * 100.0, f"pct_{i}{j}")
    for i, j in itertools.combinations(range(k), 2):
        add(lambda: n[i] + n[j], f"add_{i}{j}")
        add(lambda: n[i] - n[j], f"sub_{i}{j}")
        add(lambda: n[j] - n[i], f"sub_{j}{i}")

    if k >= 3:
        for i, j, l in itertools.permutations(range(k), 3):
            a, b, c = n[i], n[j], n[l]
            add(lambda: a * b * c, f"mul3_{i}{j}{l}")
            if b - c:
                add(lambda: a / (b - c), f"divdiff_{i}{j}{l}")
            if b + c:
                add(lambda: a * b / (b + c), f"share_{i}{j}{l}")
            add(lambda: a * (1 + b / 100.0) ** c, f"cmp_{i}{j}{l}")

    if k >= 1:
        total = sum(n)
        if total:
            for i, x in enumerate(n):
                add(lambda x=x, total=total: x / total * 100.0, f"shareof_{i}")

    return out


def solve_generic(question: str, options: list[str], use_hints: bool = True):
    """Return (letter, label) or (None, None), using no network."""
    from solve import all_nums, to_date, to_num

    # A date question is its own shape: signing date + N days.
    if "settle" in question.lower() or "date" in question.lower():
        start = to_date(question)
        m = re.search(r"(\d+)\s*-?\s*day", question.lower())
        if start and m:
            target = start + dt.timedelta(days=int(m.group(1)))
            for i, opt in enumerate(options):
                if to_date(opt) == target:
                    return LETTERS[i], "date_add"

    nums = all_nums(question)
    if not nums:
        return None, None

    opt_vals = []
    for i, opt in enumerate(options):
        v = to_num(opt)
        opt_vals.append((i, v))

    # The displayed options are rounded, so a hit only has to agree to the
    # precision actually shown. "11.6%" has been rounded to one decimal and
    # can sit up to 0.05 from the true value; "923 units" up to 0.5. Demanding
    # more than that is what makes a correct formula look like a miss.
    def tolerance_for(text: str, value: float) -> float:
        m = re.search(r"\.(\d+)", str(text).replace(",", ""))
        decimals = len(m.group(1)) if m else 0
        half_unit = 0.5 * (10.0 ** -decimals)
        # plus a little slack for float noise on large magnitudes
        return half_unit + max(abs(value), 1.0) * 1e-9

    def hits(value):
        best = None
        for i, ov in opt_vals:
            if ov is None:
                continue
            err = abs(ov - value)
            if err <= tolerance_for(options[i], value):
                if best is None or err < best[1]:
                    best = (i, err)
        return best[0] if best else None

    for value, label in candidates(question, nums, use_hints=use_hints):
        if value is None:
            continue
        try:
            if value != value or abs(value) == float("inf"):  # NaN / inf
                continue
        except (TypeError, OverflowError):
            continue
        idx = hits(value)
        if idx is not None:
            return LETTERS[idx], label

    return None, None

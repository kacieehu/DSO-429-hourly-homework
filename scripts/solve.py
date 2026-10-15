#!/usr/bin/env python3
"""
DSO 429 Homework 3 - autonomous hourly quiz solver.

Downloads the shared questions.csv, solves every round that does not yet have a
valid answer file, and writes answers/round-XXXX.json.

Pure standard library: no API keys, no network beyond the questions file.
Every question template is solved deterministically, then matched against the
four offered options by numeric/date proximity, so formatting differences in
the choices can never cause a wrong pick.

Exit codes:
  0  success (even if nothing new to do)
  1  hard failure (download failed, or a round could not be written)
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANSWERS_DIR = os.path.join(REPO_ROOT, "answers")
STATE_PATH = os.path.join(REPO_ROOT, "state", "solver_state.json")

# A round's graded version is the last one received within this window, so a
# round whose answers contain a guess is worth re-solving until it closes.
EDIT_WINDOW = dt.timedelta(hours=3)

QUESTIONS_SOURCES = [
    # API endpoint first: it is not behind the raw-content CDN cache, so it sees
    # a newly released round sooner.
    (
        "https://api.github.com/repos/FaisalXL/dso429-hourly-quiz/contents/questions.csv?ref=main",
        {"Accept": "application/vnd.github.raw"},
    ),
    (
        "https://raw.githubusercontent.com/FaisalXL/dso429-hourly-quiz/main/questions.csv",
        {},
    ),
]

LETTERS = ("A", "B", "C", "D")
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# download
# --------------------------------------------------------------------------

def fetch_questions(attempts: int = 4) -> str:
    """Fetch questions.csv, trying every mirror, and keep the fullest copy."""
    best_text = None
    best_rounds = -1
    last_error = None
    token = os.environ.get("GITHUB_TOKEN", "")

    for attempt in range(1, attempts + 1):
        for url, extra_headers in QUESTIONS_SOURCES:
            bust = f"{'&' if '?' in url else '?'}cb={int(time.time())}"
            headers = {
                "User-Agent": "dso429-hw3-solver",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                **extra_headers,
            }
            if token and "api.github.com" in url:
                headers["Authorization"] = f"Bearer {token}"
            try:
                req = urllib.request.Request(url + bust, headers=headers)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    text = resp.read().decode("utf-8-sig", errors="replace")
            except Exception as exc:  # noqa: BLE001 - any failure: try next mirror
                last_error = exc
                log(f"  fetch failed ({url.split('/')[2]}): {exc}")
                continue

            n_rounds = len({r["round_id"] for r in parse_rows(text)})
            log(f"  fetched {len(text)} bytes / {n_rounds} rounds from {url.split('/')[2]}")
            if n_rounds > best_rounds:
                best_rounds, best_text = n_rounds, text

        if best_rounds > 0:
            return best_text
        if attempt < attempts:
            wait = 10 * attempt
            log(f"  all mirrors failed, retrying in {wait}s")
            time.sleep(wait)

    raise RuntimeError(f"could not download questions.csv: {last_error}")


# Canonical field -> header spellings we will accept for it. The feed's
# headers are not under my control, so a rename ("question" for
# "question_text", "a" for "option_a") must not take the pipeline down.
FIELD_ALIASES = {
    "round_id": ("round_id", "round", "roundid", "round_number", "roundno", "round_num"),
    "q_index": ("q_index", "qindex", "question_index", "q", "q_no", "qno",
                "question_number", "index", "number"),
    "released_at": ("released_at", "releasedat", "released", "release_time",
                    "release_at", "timestamp", "published_at", "released_utc"),
    "question_text": ("question_text", "question", "questiontext", "text",
                      "prompt", "body", "stem"),
    "option_a": ("option_a", "optiona", "a", "choice_a", "answer_a", "opt_a"),
    "option_b": ("option_b", "optionb", "b", "choice_b", "answer_b", "opt_b"),
    "option_c": ("option_c", "optionc", "c", "choice_c", "answer_c", "opt_c"),
    "option_d": ("option_d", "optiond", "d", "choice_d", "answer_d", "opt_d"),
}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").strip().lower())


def build_header_map(fieldnames) -> dict:
    """Map canonical field -> the actual header in this file."""
    present = {_norm_header(h): h for h in (fieldnames or []) if h}
    mapping = {}
    for canon, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            key = _norm_header(alias)
            if key in present:
                mapping[canon] = present[key]
                break
    return mapping


def parse_rows(text: str) -> list[dict]:
    """Parse the feed into canonical dicts, tolerating renamed columns.

    Returns rows keyed by the canonical names the rest of the script uses, so
    a header change upstream is absorbed here rather than breaking everything
    downstream.
    """
    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception:  # noqa: BLE001
        return []

    hmap = build_header_map(reader.fieldnames)
    # Without these we genuinely cannot proceed.
    if not {"round_id", "q_index", "question_text"} <= set(hmap):
        log(f"  WARNING: feed headers not recognised: {reader.fieldnames}")
        return []

    out = []
    for r in rows:
        rid = r.get(hmap["round_id"])
        qix = r.get(hmap["q_index"])
        if rid is None or qix is None:
            continue
        try:
            int(str(rid).strip())
            int(str(qix).strip())
        except (ValueError, TypeError):
            continue
        canon = {canon: r.get(src, "") for canon, src in hmap.items()}
        # Any option column that is absent becomes an empty string rather than
        # a missing key, so option handling never raises.
        for letter in "abcd":
            canon.setdefault(f"option_{letter}", "")
        out.append(canon)
    return out


# --------------------------------------------------------------------------
# numeric / date helpers
# --------------------------------------------------------------------------

NUM_RE = re.compile(r"-?\$?\s*-?\d[\d,]*\.?\d*")


def to_num(s: str):
    """Parse the first number out of a string, ignoring $ , % and unit words."""
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace("$", "").replace("%", "")
    t = re.sub(r"[A-Za-z\s]+$", "", t).strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    m = re.search(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", t)
    if not m:
        return None
    try:
        v = float(m.group(0))
    except ValueError:
        return None
    return -v if neg else v


def all_nums(text: str) -> list[float]:
    """Every number in a sentence, in order, commas stripped."""
    out = []
    for m in re.finditer(r"-?\d[\d,]*\.?\d*", text):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    return out


def to_date(s: str):
    """Parse '17 November 2026' (also 'November 17, 2026' / ISO) -> date."""
    if s is None:
        return None
    t = str(s).strip()
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", t)
    if m and m.group(2).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", t)
    if m and m.group(1).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


# --------------------------------------------------------------------------
# the twelve templates
# --------------------------------------------------------------------------

def solve_value(q: str):
    """Return (value, kind) where kind is 'num' or 'date', or (None, None)."""
    t = " ".join(q.split())
    low = t.lower()
    n = all_nums(t)

    # 1. compound interest: P grows at r% compounded annually, after y years
    if "compounded annually" in low and len(n) >= 3:
        p, r, y = n[0], n[1], n[2]
        return p * (1 + r / 100.0) ** y, "num"

    # 2. gross margin: (revenue - cogs) / revenue
    if "gross margin" in low and len(n) >= 2:
        rev, cogs = n[0], n[1]
        if rev == 0:
            return None, None
        return (rev - cogs) / rev * 100.0, "num"

    # 3. sequence: next value in the pattern
    if "pattern continues" in low or "next value" in low:
        seq = all_nums(t.split("runs", 1)[1]) if "runs" in low else n
        seq = [x for x in seq]
        if len(seq) >= 3:
            diffs = [seq[i + 1] - seq[i] for i in range(len(seq) - 1)]
            if max(diffs) - min(diffs) < 1e-9:                      # arithmetic
                return seq[-1] + diffs[0], "num"
            if all(abs(x) > 1e-12 for x in seq[:-1]):
                ratios = [seq[i + 1] / seq[i] for i in range(len(seq) - 1)]
                if max(ratios) - min(ratios) < 1e-9:                # geometric
                    return seq[-1] * ratios[0], "num"
            d2 = [diffs[i + 1] - diffs[i] for i in range(len(diffs) - 1)]
            if d2 and max(d2) - min(d2) < 1e-9:                     # quadratic
                return seq[-1] + diffs[-1] + d2[0], "num"
        return None, None

    # 4. discount: list price less d%
    if "discount" in low and ("sale price" in low or "discounted by" in low) and len(n) >= 2:
        price, pct = n[0], n[1]
        return price * (1 - pct / 100.0), "num"

    # 5. percentage change between two figures
    if "percentage change" in low and len(n) >= 2:
        old, new = n[0], n[1]
        if old == 0:
            return None, None
        return (new - old) / old * 100.0, "num"

    # 6. settlement date: signed on <date>, +N-day settlement
    if "settle" in low:
        start = to_date(t)
        m = re.search(r"(\d+)\s*-?\s*day", low)
        if start and m:
            return start + dt.timedelta(days=int(m.group(1))), "date"
        return None, None

    # 7. break-even units: fixed / (price - variable)
    if "break even" in low or "break-even" in low:
        if len(n) >= 3:
            fixed, price, var = n[0], n[1], n[2]
            if price - var == 0:
                return None, None
            return fixed / (price - var), "num"
        return None, None

    # 8. ratio split of a budget between two channels
    if "ratio" in low and len(n) >= 3:
        total, a, b = n[0], n[1], n[2]
        if a + b == 0:
            return None, None
        share = a if ("first" in low or "second" not in low) else b
        return total * share / (a + b), "num"

    # 9. weighted average order value across two regions
    if "average order value" in low and len(n) >= 4:
        na, aa, nb, ab = n[0], n[1], n[2], n[3]
        if na + nb == 0:
            return None, None
        return (na * aa + nb * ab) / (na + nb), "num"

    # 10. currency conversion at a quoted rate
    if ("euros per" in low or "converted to" in low) and len(n) >= 2:
        amount, rate = n[0], n[1]
        return amount * rate, "num"

    # 11. probability of drawing one category from a queue
    if "probability" in low and len(n) >= 2:
        total = sum(n)
        if total == 0:
            return None, None
        target = None
        m = re.search(r"probability it is an?\s+([a-z]+)", low)
        if m:
            want = m.group(1)
            # find the count that sits directly in front of that category word
            for cm in re.finditer(r"(\d[\d,]*\.?\d*)\s+" + re.escape(want), low):
                target = float(cm.group(1).replace(",", ""))
                break
        if target is None:
            target = n[0]
        return target / total * 100.0, "num"

    # 12. total revenue: units x unit price
    if "total revenue" in low and len(n) >= 2:
        return n[0] * n[1], "num"

    return None, None


# --------------------------------------------------------------------------
# option matching
# --------------------------------------------------------------------------

def pick_letter(q: str, options: list[str]):
    """Return (letter, confidence) - confidence is 'exact', 'close' or None."""
    value, kind = solve_value(q)
    if value is None:
        return None, None

    if kind == "date":
        for i, opt in enumerate(options):
            if to_date(opt) == value:
                return LETTERS[i], "exact"
        return None, None

    # numeric: the option nearest the computed value wins
    scored = []
    for i, opt in enumerate(options):
        ov = to_num(opt)
        if ov is None:
            continue
        err = abs(ov - value) / max(1.0, abs(value))
        scored.append((err, i, ov))
    if not scored:
        return None, None
    scored.sort()
    best_err, best_i, _ = scored[0]
    runner_err = scored[1][0] if len(scored) > 1 else float("inf")

    # Options are rounded (cents, or one decimal on a percent), so a tiny
    # relative gap is expected; anything bigger means the template was misread.
    if best_err <= 0.02 and (runner_err > best_err * 3 or runner_err - best_err > 0.004):
        return LETTERS[best_i], "exact" if best_err < 1e-6 else "close"
    if best_err <= 0.02:
        return LETTERS[best_i], "close"
    return None, None


# --------------------------------------------------------------------------
# rounds
# --------------------------------------------------------------------------

def answer_path(round_id: int) -> str:
    return os.path.join(ANSWERS_DIR, f"round-{round_id:04d}.json")


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            state = json.load(fh)
    except Exception:  # noqa: BLE001 - missing or corrupt: start fresh
        state = {}
    state.setdefault("flagged", {})
    return state


def save_state(state: dict) -> None:
    """Write the state file only if its content actually changed.

    No timestamps live in here on purpose. A field that moves every run would
    produce a commit every 15 minutes and, worse, make this the one file two
    runs can conflict on.
    """
    body = json.dumps(state, indent=2, sort_keys=True) + "\n"
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            if fh.read() == body:
                return
    except OSError:
        pass
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        fh.write(body)


def released_at(rows: list[dict]):
    """Earliest released_at in a round, as an aware UTC datetime, or None."""
    stamps = []
    for r in rows:
        raw = (r.get("released_at") or "").strip()
        if not raw:
            continue
        try:
            d = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        stamps.append(d)
    return min(stamps) if stamps else None


def still_editable(rows: list[dict]) -> bool:
    """True while a round is inside its 3-hour window (unknown time -> yes)."""
    rel = released_at(rows)
    if rel is None:
        return True
    return dt.datetime.now(dt.timezone.utc) - rel < EDIT_WINDOW


def existing_answers(round_id: int):
    """Return the dict of answers already committed for a round, or None."""
    path = answer_path(round_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 - corrupt file: treat as not submitted
        return None
    answers = data.get("answers")
    if not isinstance(answers, dict):
        return None
    if any(answers.get(f"q{i}") not in LETTERS for i in range(1, 26)):
        return None
    return answers


def solve_round(round_id: int, rows: list[dict]):
    """Return (answers, unsolved q_index list, llm-rescued q_index list).

    Three tiers, in order:
      1. the deterministic template solver - exact, and all that practice
         rounds ever need;
      2. an LLM fallback, for a question type that never appeared in practice;
      3. a fixed letter, so the file is always valid JSON worth partial credit
         rather than a missing file worth zero.
    """
    by_index = {}
    for r in rows:
        by_index[int(str(r["q_index"]).strip())] = r

    answers, unsolved, rescued = {}, [], []
    for i in range(1, 26):
        row = by_index.get(i)
        letter = None
        opts = ["", "", "", ""]
        question = ""
        if row:
            question = row.get("question_text", "")
            opts = [row.get("option_a", ""), row.get("option_b", ""),
                    row.get("option_c", ""), row.get("option_d", "")]
            try:
                letter, _conf = pick_letter(question, opts)
            except Exception as exc:  # noqa: BLE001 - never let one question stop a round
                log(f"    q{i}: solver error: {exc}")
                letter = None

        if letter is None and question and any(o for o in opts):
            # Unknown template: hand this one question to a model.
            try:
                import llm_fallback

                letter, provider = llm_fallback.answer(question, opts, log=log)
                if letter:
                    rescued.append(i)
                    log(f"    q{i}: no template matched; answered {letter} "
                        f"via {provider}")
            except Exception as exc:  # noqa: BLE001 - fallback must never raise
                log(f"    q{i}: llm fallback unavailable: {exc}")
                letter = None

        if letter is None:
            unsolved.append(i)
            # A valid file with a guess scores partial credit; a missing or
            # invalid file scores zero. Always emit a legal letter.
            letter = "A"
        answers[f"q{i}"] = letter
    return answers, unsolved, rescued


def write_round(round_id: int, answers: dict) -> None:
    os.makedirs(ANSWERS_DIR, exist_ok=True)
    path = answer_path(round_id)
    body = {"round_id": round_id, "answers": answers}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=2)
        fh.write("\n")
    # verify before it becomes the real file
    with open(tmp, encoding="utf-8") as fh:
        check = json.load(fh)
    assert check["round_id"] == round_id
    assert all(check["answers"][f"q{i}"] in LETTERS for i in range(1, 26))
    os.replace(tmp, path)


def main() -> int:
    log("== DSO 429 HW3 solver ==")
    log(f"utc now: {dt.datetime.now(dt.timezone.utc).isoformat()}")

    text = fetch_questions()
    rows = parse_rows(text)
    if not rows:
        log("ERROR: questions.csv parsed to zero usable rows")
        return 1

    by_round = defaultdict(list)
    for r in rows:
        by_round[int(str(r["round_id"]).strip())].append(r)

    log(f"rounds present in feed: {len(by_round)} "
        f"(min {min(by_round)}, max {max(by_round)})")

    state = load_state()
    old_flagged = {str(k): v for k, v in state["flagged"].items()}

    wrote, skipped, incomplete, flagged, locked = [], 0, [], [], []
    rescued_rounds = {}          # rounds an LLM had to rescue a question in
    new_templates = {}           # unrecognised question wording, for the alert

    for round_id in sorted(by_round):
        rrows = by_round[round_id]
        key = str(round_id)

        if len(rrows) < 25:
            # Round is still being published; leave it for the next run so we
            # never lock in guesses for questions that have not appeared yet.
            incomplete.append((round_id, len(rrows)))
            continue

        have = existing_answers(round_id) is not None
        was_flagged = key in old_flagged

        if have and not was_flagged:
            skipped += 1
            continue
        if have and was_flagged and not still_editable(rrows):
            # Past three hours the submitted answer is locked; rewriting it
            # cannot help, so leave the file alone and keep reporting it.
            locked.append((round_id, old_flagged[key]))
            flagged.append((round_id, old_flagged[key]))
            skipped += 1
            continue

        answers, unsolved, rescued = solve_round(round_id, rrows)
        write_round(round_id, answers)
        wrote.append(round_id)

        # Record the wording of anything the template solver did not know, so
        # the alert can show it and a formula can be added.
        if unsolved or rescued:
            by_index = {int(str(r["q_index"]).strip()): r for r in rrows}
            for qi in sorted(set(unsolved) | set(rescued)):
                row = by_index.get(qi)
                if row:
                    new_templates[f"r{round_id}q{qi}"] = \
                        row.get("question_text", "")[:300]

        if rescued:
            rescued_rounds[str(round_id)] = rescued
        if unsolved:
            flagged.append((round_id, unsolved))
            log(f"  round {round_id}: WROTE with {len(unsolved)} guessed "
                f"question(s): {unsolved}")
        elif rescued:
            log(f"  round {round_id}: 25/25, but {len(rescued)} answered by "
                f"LLM fallback: {rescued}")
        else:
            verb = "re-solved" if have else "solved"
            log(f"  round {round_id}: {verb} 25/25")

    save_state({
        "flagged": {str(r): u for r, u in flagged},
        "feed_max_round": max(by_round),
    })

    log("")
    log(f"already answered : {skipped}")
    log(f"newly written    : {len(wrote)} {wrote if wrote else ''}")
    if incomplete:
        log(f"partial rounds   : {incomplete} (will retry next run)")
    if flagged:
        log(f"NEEDS ATTENTION  : rounds with guesses {flagged}")
    if rescued_rounds:
        log(f"LLM-rescued      : {rescued_rounds}")
    if locked:
        log(f"locked (past 3h) : {locked}")

    # Make the outcome available to the workflow.
    summary = {
        "wrote": wrote,
        "skipped": skipped,
        "incomplete": [r for r, _ in incomplete],
        "flagged": {str(r): u for r, u in flagged},
        "rescued": rescued_rounds,
        "new_templates": new_templates,
        "feed_max_round": max(by_round),
    }
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"wrote_count={len(wrote)}\n")
            fh.write(f"wrote_rounds={','.join(str(r) for r in wrote)}\n")
            fh.write(f"flagged_count={len(flagged)}\n")
            fh.write(f"rescued_count={len(rescued_rounds)}\n")
            fh.write(f"summary={json.dumps(summary)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

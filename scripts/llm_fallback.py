#!/usr/bin/env python3
"""
Last-resort answerer for a question no deterministic template matches.

The deterministic solver in solve.py handles every template seen so far and is
exact, so this is never used on a known question. It exists for one scenario:
the graded rounds introduce a question type that did not appear in the practice
rounds. Without it, a new type would fall back to a fixed letter (25% expected)
and depend on a human patching the solver within three hours.

Providers, tried in order:
  1. GitHub Models - free, no API key, authenticated with the workflow's own
     GITHUB_TOKEN. Needs `permissions: models: read` in the workflow.
  2. Anthropic - only if ANTHROPIC_API_KEY is set as a repository secret.

Rather than trusting the model to pick a letter, we ask it for the *value* and
match that value against the options with the same numeric/date matcher the
deterministic solver uses. A model that computes correctly but mislabels the
option still lands on the right letter. The model's own letter is used only if
the value cannot be matched.

Everything is standard library, and every failure path returns None so a
provider outage can never raise into the solver.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

LETTERS = ("A", "B", "C", "D")

# Set once a provider proves non-functional, so we stop paying for retries.
_GITHUB_MODELS_DEAD = False

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_MODELS_MODEL = os.environ.get("GH_MODEL", "openai/gpt-4.1")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")

PROMPT = """You are answering a multiple-choice business-arithmetic question.

Question:
{question}

Options:
A) {a}
B) {b}
C) {c}
D) {d}

Work out the exact answer. Then reply with ONLY a JSON object, no prose, no
code fences:

{{"value": <the computed answer as a bare number, or as "D Month YYYY" if it is a date>, "letter": "<A, B, C or D>"}}

For a number, do not include currency symbols, percent signs, thousands
separators or units - just the number, for example 3852.95 or -15.1.
"""


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        ctype = resp.headers.get("Content-Type", "") or ""
    if "json" not in ctype.lower():
        raise RuntimeError(
            f"expected JSON, got {ctype or 'unknown'}: {raw[:80]!r}"
        )
    return json.loads(raw)


def _ask_github_models(prompt: str):
    """GitHub Models, free with the workflow token.

    Measured note: on the runner this repository actually uses, this endpoint
    is intercepted - every request, including a plain catalog GET, comes back
    as 200 text/plain "OK" rather than JSON. That is detected here and the
    provider is marked dead for the rest of the process instead of retrying,
    so it costs one quick request and then gets out of the way. It is kept
    because it is free and may work on a different runner.
    """
    global _GITHUB_MODELS_DEAD
    if _GITHUB_MODELS_DEAD:
        return None
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return None
    body = _post_json(
        GITHUB_MODELS_URL,
        {
            "model": GITHUB_MODELS_MODEL,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        },
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "dso429-hw3-solver",
        },
    )
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        _GITHUB_MODELS_DEAD = True
        raise RuntimeError(
            "GitHub Models returned no choices (endpoint appears intercepted); "
            "skipping it for the rest of this run"
        ) from None


def _ask_anthropic(prompt: str):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return None
    body = _post_json(
        ANTHROPIC_URL,
        {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 512,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        },
        {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "User-Agent": "dso429-hw3-solver",
        },
    )
    return "".join(part.get("text", "") for part in body.get("content", []))


PROVIDERS = (("github-models", _ask_github_models), ("anthropic", _ask_anthropic))


def providers_available() -> list[str]:
    names = []
    if os.environ.get("GITHUB_TOKEN"):
        names.append("github-models")
    if os.environ.get("ANTHROPIC_API_KEY"):
        names.append("anthropic")
    return names


def _extract_json(text: str):
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def answer(question: str, options: list[str], log=print):
    """Return (letter, provider) or (None, None)."""
    # Imported lazily so this module can be used on its own in tests.
    from solve import to_date, to_num

    prompt = PROMPT.format(
        question=question,
        a=options[0], b=options[1], c=options[2], d=options[3],
    )

    for name, fn in PROVIDERS:
        for attempt in (1, 2):
            try:
                raw = fn(prompt)
            except Exception as exc:  # noqa: BLE001 - try the next provider
                log(f"      llm {name} attempt {attempt} failed: {exc}")
                time.sleep(2 * attempt)
                continue
            if raw is None:
                break  # provider not configured

            parsed = _extract_json(raw)
            if not parsed:
                log(f"      llm {name} returned unparseable output")
                continue

            # Prefer matching the computed value to an option ourselves.
            value = parsed.get("value")
            if value is not None:
                as_date = to_date(str(value))
                if as_date is not None:
                    for i, opt in enumerate(options):
                        if to_date(opt) == as_date:
                            return LETTERS[i], name
                as_num = to_num(str(value))
                if as_num is not None:
                    best, best_err = None, None
                    for i, opt in enumerate(options):
                        ov = to_num(opt)
                        if ov is None:
                            continue
                        err = abs(ov - as_num) / max(1.0, abs(as_num))
                        if best_err is None or err < best_err:
                            best, best_err = i, err
                    if best is not None and best_err is not None and best_err <= 0.02:
                        return LETTERS[best], name

            letter = str(parsed.get("letter", "")).strip().upper()[:1]
            if letter in LETTERS:
                return letter, name

    return None, None


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    print("providers available:", providers_available() or "none")
    letter, provider = answer(
        "An investment of $1,000.00 grows at 5% compounded annually. "
        "What is its value after 30 years?",
        ["$4,321.94", "$2,500.00", "$1,500.00", "$3,000.00"],
    )
    print(f"smoke test -> {letter} via {provider} (expected A)")
    sys.exit(0 if letter == "A" else 1)

#!/usr/bin/env python3
"""Temporary diagnostic: find the working GitHub Models endpoint/model combo."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

TOKEN = os.environ.get("GITHUB_TOKEN", "")
print("token present:", bool(TOKEN), "len", len(TOKEN))


def show(label, url, payload=None, method="GET", extra=None):
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "dso429-diag",
    }
    if extra:
        headers.update(extra)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method if data is None else "POST")
    print(f"\n=== {label} ===")
    print(f"{req.get_method()} {url}")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            body = r.read().decode("utf-8", errors="replace")
            print("status:", r.status)
            print("ctype :", r.headers.get("Content-Type"))
            print("body  :", body[:600] if body else "<EMPTY>")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print("HTTPError status:", e.code)
        print("body  :", body[:600] if body else "<EMPTY>")
    except Exception as e:  # noqa: BLE001
        print("ERROR:", type(e).__name__, e)


msgs = [{"role": "user", "content": "Reply with the single word: ok"}]

show("catalog", "https://models.github.ai/catalog/models")
show("inference models.github.ai openai/gpt-4.1",
     "https://models.github.ai/inference/chat/completions",
     {"model": "openai/gpt-4.1", "messages": msgs, "temperature": 0})
show("inference models.github.ai openai/gpt-4o-mini",
     "https://models.github.ai/inference/chat/completions",
     {"model": "openai/gpt-4o-mini", "messages": msgs, "temperature": 0})
show("azure endpoint gpt-4o-mini",
     "https://models.inference.ai.azure.com/chat/completions",
     {"model": "gpt-4o-mini", "messages": msgs, "temperature": 0})

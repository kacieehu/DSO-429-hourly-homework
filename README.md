# DSO 429 — Homework 3: The Hourly Quiz

Autonomous submission pipeline for the hourly quiz (rounds 1–168).

Answers are computed and pushed by **GitHub Actions**, which runs on GitHub's
own servers. Nothing runs on my laptop, so the machine can be closed or off for
the whole week.

## How it works

Every 10 minutes, the
[solve workflow](.github/workflows/solve.yml):

1. downloads [`questions.csv`](https://github.com/FaisalXL/dso429-hourly-quiz/blob/main/questions.csv),
2. finds every round that is fully published (25 of 25 questions) and does not
   yet have a valid answer file,
3. solves all 25 questions,
4. writes `answers/round-XXXX.json`,
5. commits and pushes to `main`, then re-fetches `main` to confirm the files
   actually arrived.

### Why every 10 minutes

A scheduled Actions run is best-effort: GitHub delays them under load and
drops them outright during incidents, and the questions file itself can lag a
release by up to five minutes. Timing credit is 100% for three hours after
release, so a round has ~18 chances and needs only one. A public repository
gets unlimited Actions minutes and each run takes about 15 seconds.

**Known risk, stated plainly:** if GitHub's scheduler stops firing entirely,
every attempt stops with it. The watchdog catches that and emails, and
`docs/external-trigger.md` sets up a backup trigger that does not depend on
GitHub's scheduler at all.

### How the answers are computed

Four tiers, tried in order. Tiers 1 and 2 are standard library only — no API
key, no model call, no per-run cost, nothing to run out of credit.

| Tier | What it is | Measured accuracy |
| --- | --- | --- |
| 1 | Exact formula per known template | **1200/1200** on practice rounds |
| 2 | Offline formula search over the sentence's numbers | **1200/1200**; ~65% on a formula shape it was given no hint for |
| 3 | An LLM — only if `ANTHROPIC_API_KEY` is set | not enabled by default |
| 4 | A fixed letter | ~25%, but the file is always valid |

**Tier 1** gives each of the twelve question templates in the feed a
closed-form formula:

| Template | Formula |
| --- | --- |
| Compound growth | `P(1 + r)^n` |
| Gross margin | `(revenue − COGS) / revenue` |
| Discounted sale price | `list × (1 − d)` |
| Total revenue | `units × unit price` |
| Currency conversion | `amount × rate` |
| Percentage change | `(new − old) / old` |
| Weighted average order value | `(nₐ·x̄ₐ + n_b·x̄_b) / (nₐ + n_b)` |
| Break-even units | `fixed / (price − variable)` |
| Ratio split | `total × a / (a + b)` |
| Probability from a queue | `category / total` |
| Next value in a series | arithmetic, geometric or quadratic difference |
| Settlement date | `signing date + N days` |

The computed value is then matched against the four offered options by
**numeric (or calendar) proximity**, not by string formatting — so the way a
choice is written (`$3,852.95` vs `3852.95` vs `60.9%`) can never cause a wrong
pick. A match is only accepted when the nearest option is distinctly nearer
than the runner-up; otherwise the question falls through to tier 2.

Verified: **1200 / 1200** on practice rounds 1–48, every template at 100%
(`scripts/validate.py`). `answers/round-0001.json` matches the example file in
the assignment PDF exactly.

### What happens if the graded rounds are not like the practice rounds

This is the one risk the practice set cannot rule out, so it is handled
explicitly rather than assumed away.

**A new question type.** Tier 2 (`scripts/generic.py`) does not try to
recognise the wording at all. It extracts the numbers, computes a ranked list
of standard business formulas over them, and takes the most canonical value
that lands on an offered option to the precision that option is printed at.

`scripts/test_generic.py` measures this honestly by scoring it against the
published keys with the real template solver switched off:

- **1200/1200** with its formula library available;
- **~65%** in `--no-hints` mode, which strips every keyword-driven formula and
  leaves only a blind structural search — a stand-in for a formula shape
  nobody anticipated. A blind guess is 25%.

A new type also opens a GitHub issue even when it was answered correctly, so
an exact formula can be added rather than leaning on the fallback.

**A changed file format.** Column headers are matched by alias, so a rename
upstream (`Round`, `Question`, `A`–`D`, …) is absorbed. A header that cannot be
recognised at all fails the run loudly and emails, rather than writing
rubbish answers.

**Note on GitHub Models.** Tier 3 originally used GitHub Models, which is free
and needs no key. On this repository's runner that endpoint is intercepted —
every request, including a plain catalog `GET`, returns `200 text/plain "OK"`
instead of JSON — so it does not work here and is detected and skipped. The
Anthropic API is reachable from the same runner, so tier 3 activates if an
`ANTHROPIC_API_KEY` secret is added. It is not required: tiers 1 and 2 need no
network beyond the questions file.

## Safety nets

| Risk | What handles it |
| --- | --- |
| A scheduled run is late or skipped | A run every 10 minutes; a round is picked up by any later run |
| The questions file is slow to update | Two independent sources (GitHub API, then raw CDN), cache-busted, with retries and backoff; the fullest copy wins |
| A round is half-published when we look | Rounds with fewer than 25 questions are left for the next run, so a guess is never locked in for a question that has not appeared yet |
| Two runs push at once | `concurrency` queues runs; the push step rebases and retries five times |
| A push silently fails | The run re-fetches `main` and fails if any answer file is not in the remote tree |
| A new, unrecognised question type appears | Tier 2's offline formula search answers it (100% on the practice set, ~65% on an unanticipated formula shape), the round is still written as **valid JSON**, and an issue is opened. The round is automatically re-solved for three hours after release, so a fix inside that window is picked up |
| The questions file changes its column names | Headers are matched by alias; an unrecognisable header fails loudly instead of writing rubbish |
| The solver gets silently broken | Every run re-scores all 1200 practice questions and fails if it is not perfect |
| The schedule dies and says nothing | The [watchdog](.github/workflows/watchdog.yml) audits coverage three times a day, independently of the solver, and opens an issue for any missing, invalid or misnamed file |
| A safety net is quietly misconfigured | The [self-test](.github/workflows/selftest.yml) exercises the fallbacks daily, so they are proven working *before* they are needed |
| The repository is made private by accident | The watchdog checks visibility every run and alerts |

Every alert is a GitHub issue, which GitHub emails to me — so the pipeline
reports problems instead of needing to be watched.

## Layout

```
answers/round-XXXX.json      one file per round, round number padded to 4 digits
scripts/solve.py             fetch, solve, write
scripts/generic.py           offline formula search for unknown question types
scripts/llm_fallback.py      optional LLM tier, used only if a key is set
scripts/validate.py          regression test against the published practice keys
scripts/test_variants.py     offline edge cases (leap days, mirrored wording, ...)
scripts/test_generic.py      leave-one-out measurement of the offline fallback
scripts/test_llm.py          proves the LLM tier is reachable, if configured
scripts/audit.py             independent coverage audit used by the watchdog
state/solver_state.json      which rounds contain a guess, for re-solve + reporting
.github/workflows/solve.yml  the hourly job
.github/workflows/watchdog.yml  the coverage alarm
```

## Running it by hand

```bash
python3 scripts/solve.py                  # solve and write any unanswered rounds
python3 scripts/validate.py               # must print 1200/1200
python3 scripts/test_variants.py          # must print 11/11
python3 scripts/test_generic.py           # fallback, must print 1200/1200
python3 scripts/test_generic.py --no-hints  # honest held-out number (~65%)
python3 scripts/audit.py                  # must print OK
```

Or from the **Actions** tab → *Solve and submit quiz rounds* → *Run workflow*.

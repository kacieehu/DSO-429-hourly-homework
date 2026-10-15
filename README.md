# DSO 429 — Homework 3: The Hourly Quiz

Autonomous submission pipeline for the hourly quiz (rounds 1–168).

Answers are computed and pushed by **GitHub Actions**, which runs on GitHub's
own servers. Nothing runs on my laptop, so the machine can be closed or off for
the whole week.

## How it works

Four times an hour (`:07`, `:22`, `:37`, `:52`), the
[solve workflow](.github/workflows/solve.yml):

1. downloads [`questions.csv`](https://github.com/FaisalXL/dso429-hourly-quiz/blob/main/questions.csv),
2. finds every round that is fully published (25 of 25 questions) and does not
   yet have a valid answer file,
3. solves all 25 questions,
4. writes `answers/round-XXXX.json`,
5. commits and pushes to `main`, then re-fetches `main` to confirm the files
   actually arrived.

### Why four runs an hour

A scheduled Actions run can be delayed 10–30 minutes under load, and the
questions file itself can lag a release by up to five minutes. Timing credit is
100% for three hours after release, so four attempts an hour keep every round
far inside that window even if several runs are late or dropped entirely.

### How the answers are computed

A deterministic solver (`scripts/solve.py`), standard library only — no API
key, no model call, no per-run cost, nothing to run out of credit. Each of the
twelve question templates in the feed has a closed-form formula:

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
than the runner-up; otherwise the question is treated as unsolved and flagged.

Verified: **1200 / 1200** on practice rounds 1–48, every template at 100%
(`scripts/validate.py`). `answers/round-0001.json` matches the example file in
the assignment PDF exactly.

## Safety nets

| Risk | What handles it |
| --- | --- |
| A scheduled run is late or skipped | Four runs an hour; a round is picked up by any later run |
| The questions file is slow to update | Two independent sources (GitHub API, then raw CDN), cache-busted, with retries and backoff; the fullest copy wins |
| A round is half-published when we look | Rounds with fewer than 25 questions are left for the next run, so a guess is never locked in for a question that has not appeared yet |
| Two runs push at once | `concurrency` queues runs; the push step rebases and retries five times |
| A push silently fails | The run re-fetches `main` and fails if any answer file is not in the remote tree |
| A new, unrecognised question type appears | The round is still written as **valid JSON** with a legal letter (partial credit beats a missing file, which scores zero), and an issue is opened. The round is automatically re-solved for three hours after release, so a solver fix inside that window is picked up |
| The solver gets silently broken | Every run re-scores all 1200 practice questions and fails if it is not perfect |
| The schedule dies and says nothing | The [watchdog](.github/workflows/watchdog.yml) audits coverage three times a day, independently of the solver, and opens an issue for any missing, invalid or misnamed file |
| The repository is made private by accident | The watchdog checks visibility every run and alerts |

Every alert is a GitHub issue, which GitHub emails to me — so the pipeline
reports problems instead of needing to be watched.

## Layout

```
answers/round-XXXX.json      one file per round, round number padded to 4 digits
scripts/solve.py             fetch, solve, write
scripts/validate.py          regression test against the published practice keys
scripts/audit.py             independent coverage audit used by the watchdog
state/solver_state.json      which rounds contain a guess, for re-solve + reporting
.github/workflows/solve.yml  the hourly job
.github/workflows/watchdog.yml  the coverage alarm
```

## Running it by hand

```bash
python3 scripts/solve.py       # solve and write any unanswered rounds
python3 scripts/validate.py    # must print 1200/1200
python3 scripts/audit.py       # must print OK
```

Or from the **Actions** tab → *Solve and submit quiz rounds* → *Run workflow*.

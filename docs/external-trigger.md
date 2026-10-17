# Backup trigger (only needed if GitHub's scheduler stops firing)

The hourly job normally runs from GitHub's own `schedule` trigger. That
trigger is **best-effort**: GitHub delays scheduled runs under load and drops
them during incidents. If it stops firing entirely, nothing in GitHub itself
will restart it.

This sets up a second, fully independent trigger. A free external cron service
calls the GitHub API every 5 minutes and asks the workflow to run. It does not
depend on GitHub's scheduler, so the two fail for different reasons.

**You only need this if the Actions tab shows no runs with the trigger
`schedule`.** Check at:
<https://github.com/kacieehu/DSO-429-hourly-homework/actions/workflows/solve.yml>

---

## Step 1 — Create a token GitHub will accept

A fine-grained token limited to this one repository, so it can do nothing else.

1. Go to <https://github.com/settings/personal-access-tokens/new>
2. **Token name:** `dso429-quiz-trigger`
3. **Expiration:** pick a date after **23 October 2026**
4. **Repository access:** *Only select repositories* → `DSO-429-hourly-homework`
5. **Permissions** → *Repository permissions* → **Actions: Read and write**
   (leave every other permission at *No access*)
6. **Generate token** and copy it. It is shown once.

> Treat this token like a password. It can start workflows in this one
> repository and nothing else. Revoke it on the same page when the assignment
> is graded.

## Step 2 — Point a free cron service at the workflow

Using **cron-job.org** (free, no card):

1. Sign up at <https://console.cron-job.org/signup>
2. **Create cronjob**
3. **Title:** `DSO 429 quiz`
4. **URL:**
   ```
   https://api.github.com/repos/kacieehu/DSO-429-hourly-homework/actions/workflows/solve.yml/dispatches
   ```
5. **Schedule:** choose **custom / expression** and enter

   ```
   1,6,11,16,21,26,31,36,41,46,51,56 * * * *
   ```

   That is every 5 minutes, offset by one, so runs land at :01, :06, :11 and
   so on. The offset matters: rounds are released at the top of the hour but
   can take up to five minutes to appear in `questions.csv`, so a run at :00
   sees nothing. `:01` catches a prompt update and `:06` catches the
   worst-case lag. (If the UI only offers fixed intervals, *every 5 minutes*
   is nearly as good.)
6. Open **Advanced**:
   - **Request method:** `POST`
   - **Request body:**
     ```json
     {"ref":"main"}
     ```
   - **Headers** — add these three:

     | Name | Value |
     | --- | --- |
     | `Accept` | `application/vnd.github+json` |
     | `Authorization` | `Bearer YOUR_TOKEN_FROM_STEP_1` |
     | `Content-Type` | `application/json` |
7. **Create**

A successful call returns **HTTP 204** with an empty body. cron-job.org shows
204 as a success.

## Step 3 — Confirm it works

Within ~10 minutes, the Actions tab should show new runs with the trigger
`workflow_dispatch`. That is the backup working.

---

## Test it from your own machine first (optional)

If you want to confirm the token before wiring up the service, run this once —
it should print `204`:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "Accept: application/vnd.github+json" -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" https://api.github.com/repos/kacieehu/DSO-429-hourly-homework/actions/workflows/solve.yml/dispatches -d '{"ref":"main"}'
```

## Why not have the workflow restart itself?

A run authenticated with the built-in `GITHUB_TOKEN` cannot start another
workflow run — GitHub blocks that specifically to prevent infinite loops. So a
self-restarting chain would need a stored personal token anyway, and it would
have a worse failure mode: one broken link and the chain stops forever, with
nothing left to restart it. An external caller has no such chain to break.

## Running it from your own computer instead

Not recommended as the primary route — it needs the machine awake and online —
but as an emergency stopgap, from inside a clone of this repository:

```bash
while true; do python3 scripts/solve.py && git add -A answers state && git commit -m "Answers" && git push; sleep 600; done
```

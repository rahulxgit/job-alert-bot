# job-alert-bot

A daily, self-hosted job search pipeline. It crawls job boards and APIs,
filters and de-duplicates listings, scores each one against a canonical
candidate profile using LLMs, finds a recruiter/company email where it can,
and delivers a ranked shortlist by email plus a running log in Google
Sheets — fully automated via GitHub Actions.

## Pipeline

```
fetch (13 independent sources, parallel)
  -> dedupe (normalize + strip tracking params)
  -> keyword pre-filter (cheap scoring, caps AI pool size)
  -> Crawl4AI batch enrichment (fills short/missing descriptions)
  -> AI admission control (adaptive daily candidate limit)
  -> AI fit review (Groq -> Gemini -> AI Gateway, per-candidate fallback chain)
  -> recruiter/company email enrichment (Hunter.io / Apollo)
  -> sort (has-email first, then fit score)
  -> Google Sheets log + Gmail digest
```

Every stage writes a snapshot to `run-artifacts/` (raw listings, dedupe
counts, prefilter shortlist, AI verdicts, final digest) so a run can be
debugged after the fact without re-running anything.

## Sources

`main.py` runs all of these concurrently and records per-source health
(status, duration, error classification) rather than letting one failing
source silently drop from the results:

- **Crawl4AI Discovery** — deep-crawls board roots (Greenhouse, Lever,
  Wellfound, Naukri, Internshala, Y Combinator, Cutshort, etc.) and
  extracts job-detail links directly; treated as a first-class source, not
  a fallback.
- **LinkedIn / Google Jobs** — via `python-jobspy`.
- **Internshala, Naukri, Wellfound** — direct scrapers.
- **Greenhouse, Lever** — company board APIs across a configured list of
  companies (`config.GREENHOUSE_BOARDS`, `config.LEVER_BOARDS`).
- **Arbeitnow, RemoteOK** — public job APIs.
- **YouTube, LinkedIn posts** — recruiter/hiring-post mining.
- **Firecrawl** — search-driven discovery across curated queries
  (role+location, tech-stack combos, site-targeted searches).

A bounded Crawl4AI batch pass (`_enrich_descriptions_with_crawl4ai` in
`main.py`) tops up any listing whose description came back too short to
evaluate, instead of discarding it.

## AI evaluation

Each candidate is scored against the canonical profile in
`data/rahul-master-profile.json` (built into a prompt by `ai/profile.py`,
condensed by default via `ai/profile_condensed.py` to keep prompts small
and avoid truncated JSON responses).

Provider fallback chain per candidate (`ai/evaluator.py`):

1. **Groq** (`openai/gpt-oss-120b`) — fastest, tried first.
2. **Gemini** (`gemini-2.5-flash-lite`) — fallback on Groq rate-limit/failure.
3. **AI Gateway** (self-hosted, [ai-gateway](https://github.com/rahulxgit/ai-gateway),
   multi-provider failover of its own) — last resort.

Each provider has its own shared backoff (`ai/provider_limiter.py`) so a
struggling provider doesn't get hammered by every concurrent worker at
once. Scoring breaks fit into seven weighted components (role, experience,
technical, project, education, location, company quality) that must sum to
the reported `fit_score`; anything below `LLM_FIT_THRESHOLD` (default 70)
or flagged not fresher-appropriate is rejected.

Evaluation state is checkpointed (`ai/state_store.py`, `ai/checkpoint.py`)
so a run that hits its time budget resumes unresolved candidates next time
instead of re-evaluating everything from scratch. An adaptive admission
controller (`ai/admission_controller.py`) caps how many candidates enter
AI review per run and defers the rest.

## Project layout

```
main.py                    Pipeline entry point (see run_pipeline)
config.py                  All tunables/env vars — no side effects, safe to import
models.py                  JobListing / FitVerdict dataclasses
scheduler.py                Local scheduling helper

ai/                        Evaluation: providers, prompts, state, backoff, metrics
sources/                   One module per job source
enrichment/                Recruiter/company email lookup (Hunter.io, Apollo)
mailer/                    Gmail send + digest HTML building
sheets/                    Google Sheets read/write (seen-URL tracking, logging)
utils/                     Logging, retry, run-artifact export, text/JSON helpers
data/                      Canonical candidate profile (rahul-master-profile.json)

tests/                     pytest suite (129 tests as of this writing)
run-artifacts/             Per-stage JSON/CSV snapshots from the last run (gitignored)
.github/workflows/         job-alerts.yml (daily run), tests.yml (CI)

daily_health_check.py      Local git/log/artifact hygiene check (see below)
run_daily_health_check.bat Wrapper for Windows Task Scheduler
```

## Configuration

Everything tunable lives in `config.py` as `os.environ.get(...)` calls with
sane defaults — nothing needs to be edited directly. Required at runtime
(checked by `config.validate()`, skipped in `--dry-run`):

| Variable | Purpose |
|---|---|
| `GOOGLE_SHEET_ID` | Sheet used for seen-URL tracking and job log |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Service account credentials for Sheets access |
| `ALERT_EMAIL_TO` | Destination address for the daily digest |

Common optional overrides:

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` / `GROQ_API_KEY` | — | AI provider credentials |
| `AI_GATEWAY_URL` | `ai-gateway-wx35.onrender.com` | Self-hosted fallback gateway |
| `MAX_LLM_CANDIDATES` | `300` | Cap on candidates sent to AI review per run |
| `LLM_EVALUATION_BUDGET_SECONDS` | `86400` | Wall-clock budget for the AI review stage |
| `AI_MAX_CONCURRENCY` | `4` | Parallel AI evaluation workers |
| `AI_PROFILE_MODE` | `condensed` | `condensed` or `full` candidate profile in prompts |
| `HUNTER_API_KEY` / `APOLLO_API_KEY` | — | Recruiter email enrichment |
| `GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN` | — | Gmail OAuth for sending the digest |

## Running locally

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for pytest

# Dry run: fetches, filters, evaluates, prints results — no email, no Sheets write
python main.py --dry-run

# Full run (requires the required env vars above)
python main.py
```

## Testing

```powershell
python -m pytest -q
```

129 tests covering source parsing, dedupe, prefilter scoring, AI provider
fallback/backoff behavior, checkpoint resume, discovery title extraction,
and run-artifact export.

## Daily automation

- **GitHub Actions** (`.github/workflows/job-alerts.yml`) runs the full
  pipeline daily at 8:00 AM IST, restores the latest AI checkpoint before
  starting, and uploads a fresh one after — so evaluation progress survives
  across scheduled runs within the same day's candidate pool.
- **`daily_health_check.py`** (local, via Windows Task Scheduler at 9:15 AM)
  checks git hygiene, `.gitignore` integrity (byte-level — catches
  encoding corruption, not just missing lines), the latest Actions run log
  for errors/rate-limits, and whether local `run-artifacts/*.json` are
  stale relative to each other. Run it manually anytime:

  ```powershell
  python daily_health_check.py --verbose
  ```

## Notes on data quality

Two production issues worth knowing about if you're extending this:

- **Crawl4AI title extraction** (`sources/crawl4ai_discovery.py`) prefers
  a page's real `<title>` tag over scanning markdown lines, and strips/
  rejects nav chrome (`Close`, bare links, nested image-links) before
  falling back to a markdown scan — first-line markdown on a job board
  page is often navigation, not the job title.
- **AI provider fallback** treats gateway/provider unavailability as
  recoverable per-candidate, not fatal to the run; a candidate only ends
  up unresolved if every provider fails after retries, at which point it's
  checkpointed for retry on the next run rather than dropped.

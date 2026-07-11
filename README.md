# Job Alert Bot

Scrapes Indeed, LinkedIn, Google Jobs, Internshala (all-India), Naukri,
(best-effort) Wellfound, optional LinkedIn recruiter posts, and
Greenhouse/Lever company career pages every morning. (Glassdoor and
ZipRecruiter were tried and removed — both are fully blocked from GitHub
Actions, see limitations below.) Runs a cheap keyword pre-filter, then
sends the shortlist to Gemini (free tier) to actually read each job
description against my resume and decide real fit — not just keyword
overlap. For jobs that pass, tries to find a real recruiter/company email
for outreach. Logs new matches to a Google Sheet and emails me the digest.
Runs on GitHub Actions so it doesn't depend on my laptop being on.

## How it fits together

```
GitHub Actions (cron, 8 AM IST)
        ↓
job_search.py
        ↓
jobspy scrapes Indeed + LinkedIn + Google Jobs
        +
custom scraper pulls paid internships from Internshala (all-India)
        +
custom scraper hits Naukri's internal search API directly
        +
custom scraper attempts Wellfound (best-effort, often returns nothing —
Wellfound actively blocks scrapers, see limitations below)
        +
optional: LinkedIn recruiter-post scraper (only if LINKEDIN_LI_AT_COOKIE
is set — off by default, see limitations below)
        +
Greenhouse/Lever public APIs for company career pages (limited to
companies that actually use those ATS platforms — see limitations)
        +
optional: YouTube job-alert channels via the official Data API (only if
YOUTUBE_API_KEY is set — off by default)
        ↓
keyword pre-filter (cheap) — cuts hundreds of listings down to ~55 candidates
        ↓
dedup against Google Sheet — drop anything already logged before
        ↓
Gemini API reads each remaining JD against my actual resume/profile,
scores genuine fit 0-100, rejects unpaid internships and roles that
need real professional experience
        ↓ (if Gemini's retries are exhausted — e.g. daily quota gone)
falls back to my self-hosted AI gateway (github.com/rahulxgit/ai-gateway),
which itself already fails over across 7+ providers internally
        ↓
log the survivors to the Sheet
        ↓
email the digest via Gmail API
```

## On hitting 50+ matches/day

I widened this pipeline as far as reasonably possible — 8 sources, a higher
candidate cap (55), a broader search — but I deliberately kept the Gemini
fit threshold (60/100) where it was rather than lowering it, so the digest
stays high-signal instead of stuffed with borderline matches just to hit a
number. Some days will have well over 50 genuinely good matches; other days
fewer, because that reflects the real job market that day, not a limitation
in the pipeline. If the daily count still feels too low after running this
for a week or two, the honest next lever is lowering `LLM_FIT_THRESHOLD` —
that's a one-line change whenever it's wanted.

## Known limitations (be aware of these)

- **Wellfound is best-effort and frequently returns 0 listings — this is
  expected, not a bug.** Wellfound protects its job listings with
  DataDome/Cloudflare anti-bot systems specifically to block scrapers, and
  their own scraping vendors note the site often requires a logged-in
  session to browse listings at all. The scraper tries to read Wellfound's
  embedded Next.js page data (`__NEXT_DATA__`) without logging in, which
  sometimes works and often doesn't depending on whether DataDome flags the
  request. Making this reliable would require a paid residential-proxy or
  anti-bot-bypass service (e.g. ScrapFly, Apify) — a real cost, not a code
  fix. If Wellfound consistently returns 0, that's the anti-bot wall, not
  something to debug in the script.
- **Y Combinator's "Work at a Startup" job board is not included at all**
  (not even best-effort) — it requires a logged-in session to browse
  listings in the first place, so there's no public page to even attempt.
- Internshala now searches all-India (not Bangalore-only). Its HTML
  structure can change without notice, which would break the scraper
  silently — watch the Action logs occasionally.
- **Naukri is the second most fragile source.** It's pulled via an internal
  search API (`naukri.com/jobapi/v3/search`) that their own site uses but
  isn't officially documented or supported — Naukri can change required
  headers, rate-limit harder, or restructure the response at any time
  without notice. If Naukri listings suddenly drop to zero in the logs,
  this is the first place to check.
- **LinkedIn recruiter-post scraping is optional, off by default, and the
  highest-risk source in this project.** It only activates if
  `LINKEDIN_LI_AT_COOKIE` is set. It uses a real personal session cookie
  against an undocumented internal API — LinkedIn can change this API
  without notice, rate-limit or block the session, or in the worst case
  flag/suspend the account tied to that cookie. This trade-off was made
  knowingly. If it ever causes account trouble, delete the
  `LINKEDIN_LI_AT_COOKIE` secret — the source turns itself off with no
  other changes needed, and everything else keeps working.
- **Glassdoor and ZipRecruiter were tried and removed.** Confirmed via real
  run logs: Glassdoor's jobspy scraper can't parse Indian locations and
  gets a 400/403 on every single call; ZipRecruiter is blocked outright by
  Cloudflare's WAF (403 `forbidden cf-waf`) from GitHub Actions' IPs on
  every call. Neither returned a single listing across multiple runs, so
  both were removed from `SITES` rather than left in as dead weight. If
  jobspy ever fixes the Glassdoor location bug, it could be worth re-adding.
- **Company career pages only cover Greenhouse/Lever-based companies.**
  Postman is confirmed working (`GREENHOUSE_BOARDS`). Many Indian product
  companies (Flipkart, Swiggy, Zomato, etc.) run custom in-house career
  sites that have no public API — those aren't and can't easily be covered
  this way. To add a company, find its Greenhouse/Lever board token by
  checking whether `job-boards.greenhouse.io/<token>/` or
  `jobs.lever.co/<token>` loads a real careers page, then add it to
  `GREENHOUSE_BOARDS` or `LEVER_BOARDS` at the top of `job_search.py`.
- **Instahyre and Hirist are intentionally not included.** Both render
  listings via client-side JavaScript rather than plain server HTML,
  similar to Wellfound's situation — reliably scraping them would need the
  same guesswork/uncertainty as the Wellfound attempt, and this was
  deliberately skipped as not worth the uncertain payoff.
- **WhatsApp Channels are intentionally not included, on purpose, not as a
  gap.** There's no official API for reading arbitrary public WhatsApp
  Channels, and the only unofficial route (WhatsApp Web automation) needs
  a persistent authenticated session — fundamentally incompatible with
  GitHub Actions runners, which are stateless and use a different IP every
  run. That exact pattern (repeated automated logins from rotating IPs) is
  what WhatsApp's anti-automation detection is built to catch, risking a
  ban on whatever personal number got linked. This was a deliberate call,
  not a missed feature.
- **Zapier is not wired into this script, and can't be directly** — Zapier
  connectors are tools available inside a Claude *chat*, not something
  importable into a standalone Python script running on GitHub Actions. If
  Zapier automation is wanted, that would be a separate, parallel
  automation built on Zapier's own platform (e.g. a Zap watching an RSS
  feed and writing to the Sheet), independent of this repo — not something
  that plugs into `job_search.py`.
- **YouTube job-channel scraping is a v1 simplification.** Each recent
  video is treated as one candidate (title + full description), even
  though these channels often bundle several distinct job postings into a
  single video description. Gemini reviews the video as a whole rather
  than each opening separately, so a video with one great match buried
  among five irrelevant ones might not score as highly as it should.
  Channel name → channel ID resolution also happens via a live YouTube
  search each run (not hardcoded), so a channel with an ambiguous or
  common name could occasionally resolve to the wrong result — worth
  spot-checking `YOUTUBE_CHANNEL_NAMES` results in the logs occasionally.
- **Gemini free-tier rate limits are stricter than they first appear —
  but now there's a real fallback.** The script paces calls 4.5s apart and
  retries on 429 with backoff; if that's still exhausted (e.g. same-day
  quota gone from heavy manual testing), it now falls back to my
  self-hosted AI gateway (github.com/rahulxgit/ai-gateway) automatically,
  no config needed beyond it being reachable. The gateway itself already
  routes across 7+ providers internally, so this fallback is meaningfully
  more resilient than Gemini alone — the "everything failed" circuit
  breaker now only trips if *both* tiers fail, which is a much rarer and
  more genuine "something is actually down" signal than before.
- **The AI gateway fallback has no built-in auth or retry of its own on
  this side** — it's called once per job as a last resort, relying on the
  gateway's own internal failover rather than retrying it directly. If the
  gateway URL ever changes, override it via the optional `AI_GATEWAY_URL`
  secret (defaults to `https://ai-gateway-wx35.onrender.com`). Since it's
  an open endpoint with no API key, anyone who discovers the URL could in
  theory call it directly and consume the underlying provider quotas —
  worth keeping in mind since it's a shared resource, not something
  scoped only to this bot.
- The Gemini review step calls the API once per shortlisted job (up to 55
  calls/run, paced ~4.5s apart to respect free-tier rate limits, with
  automatic retry-with-backoff on 429s) — this is free but means a run can
  take several minutes, longer now with more sources feeding in (25-minute
  workflow timeout to accommodate this).

## One-time setup

### 1. Google Sheet
Create a sheet called "Job Search Tracker" with a header row:
`URL | Title | Company | Location | Fit Score | Reason | Date Added`
Copy the sheet ID from the URL (the long string between `/d/` and `/edit`).

### 2. Google Service Account (for Sheets access)
1. Go to Google Cloud Console → create a project (or reuse one).
2. Enable the **Google Sheets API**.
3. Create a Service Account, generate a JSON key.
4. Share the Sheet with the service account's email (found in the JSON, looks
   like `xxx@xxx.iam.gserviceaccount.com`) as an Editor.
5. You'll paste the whole JSON file content into a GitHub secret.

### 3. Gmail OAuth (for sending mail)
1. In the same Cloud project, enable the **Gmail API**.
2. Create OAuth 2.0 credentials (Desktop app type).
3. Run this once locally to get a refresh token:

```python
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "credentials.json",
    scopes=["https://www.googleapis.com/auth/gmail.send"],
)
creds = flow.run_local_server(port=0)
print("refresh_token:", creds.refresh_token)
print("client_id:", creds.client_id)
print("client_secret:", creds.client_secret)
```

Keep the three printed values — they go into GitHub secrets below.

### 4. Gemini API key (for the real resume-matching step, free tier)
1. Go to https://aistudio.google.com/apikey → Create API Key.
2. No credit card required — this is a genuine free tier, not a trial.
3. Copy the key (starts with `AIza...`).

### 5. (Optional, higher-risk) LinkedIn recruiter-post cookie
This turns on scraping LinkedIn feed posts where recruiters announce
openings directly, separate from formal LinkedIn Jobs listings. **Skip this
step entirely if you don't want it** — the script checks whether this secret
exists and just skips the source cleanly if it doesn't; nothing else breaks.

**Read this before adding it:** this uses your own LinkedIn session cookie
to call an internal, undocumented API. LinkedIn actively pursues legal
action against scrapers and can flag or suspend accounts used this way —
this is a materially bigger risk than any other source in this project,
since it's tied to your real personal account, not a throwaway API key.

If you still want it:
1. Log into linkedin.com in your browser (Chrome/Edge/Firefox).
2. Open DevTools (F12) → Application tab (Chrome) or Storage tab (Firefox)
   → Cookies → `https://www.linkedin.com`.
3. Find the cookie named `li_at` → copy its value.
4. This value is as sensitive as a password — it grants access to your
   account session. Treat it accordingly.

### 6. (Optional) Hunter.io key — for a fallback recruiter/company email
Used only when a job description doesn't already contain a published email
directly. Real domain-search lookups, not guesses — but the free tier is
~25 lookups/month, and each run caps itself at 15 calls to avoid burning
the whole month in one run.

1. Go to https://hunter.io → sign up free (no card needed for the free tier).
2. Dashboard → API → copy your API key.

### 7. (Optional) YouTube Data API key — for job-alert channel scraping
Official free API, no scraping — reads recent videos + descriptions from
~21 placement/job-alert YouTube channels (Apna College, Take U Forward,
PrepInsta, etc.). Free tier is 10,000 units/day, comfortably covers this.

1. In the same Google Cloud project as steps 2-4, go to
   https://console.cloud.google.com/apis/library/youtube.googleapis.com
   → Enable.
2. Go to https://console.cloud.google.com/apis/credentials → Create
   Credentials → API key. Copy it.
3. (Recommended) Click into the new key → restrict it to only the
   "YouTube Data API v3" under API restrictions, so it can't be misused
   for anything else if it ever leaks.

### 8. GitHub repo secrets
Repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret name | Value |
|---|---|
| `GOOGLE_SHEET_ID` | the sheet ID from step 1 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | full contents of the service account JSON |
| `GMAIL_CLIENT_ID` | from step 3 |
| `GMAIL_CLIENT_SECRET` | from step 3 |
| `GMAIL_REFRESH_TOKEN` | from step 3 |
| `ALERT_EMAIL_TO` | rahulkumarshc00@gmail.com |
| `GEMINI_API_KEY` | from step 4 |
| `LINKEDIN_LI_AT_COOKIE` | optional, from step 5 — omit entirely to skip this source |
| `HUNTER_API_KEY` | optional, from step 6 — omit entirely to skip this fallback |
| `YOUTUBE_API_KEY` | optional, from step 7 — omit entirely to skip this source |
| `AI_GATEWAY_URL` | optional — omit entirely to use the default `https://ai-gateway-wx35.onrender.com`; only set this if the gateway is redeployed elsewhere |

### 9. ⚠️ Update the Sheet header row before running again
The script now appends an 8th column (`Email`) after `Date Added`. If
you've manually added an `Applied` column to the sheet already, **insert a
new column for `Email` between `Date Added` and `Applied`** before running
again — otherwise new rows will write recruiter emails into whatever column
currently sits in that 8th position, silently colliding with your `Applied`
tracking. Header row should read:
`URL | Title | Company | Location | Fit Score | Reason | Date Added | Email | Applied`

### 10. Push and test
Push this repo to GitHub, then go to Actions → Daily Job Alert → Run workflow
to trigger it manually and confirm it works before waiting for the 8 AM cron.

## Tuning

- `SEARCH_TERMS`, `LOCATIONS`, `PROFILE_KEYWORDS`, `PRIORITY_COMPANIES`,
  `INTERNSHALA_SEARCH_TERMS` are all at the top of `job_search.py`.
- **`data/profile-data.json` now drives `CANDIDATE_PROFILE` automatically** —
  this is a copy of the same source-of-truth file the resume-portfolio-sync
  skill uses. Whenever the resume/portfolio changes, update
  `data/profile-data.json` in this repo and push — `job_search.py` rebuilds
  the profile text Gemini reads from this file at the start of every run,
  no manual script edits needed anymore. If the file is ever missing or
  malformed, the script falls back to a minimal generic profile and logs a
  warning rather than crashing.
- `LLM_FIT_THRESHOLD` (currently 60) controls how strict Gemini's review is.
  Raise it if the digest is too noisy, lower it if too sparse.
- `MAX_LLM_CANDIDATES` (currently 55) caps how many jobs get sent to Gemini
  per run — kept conservative to stay within free-tier rate limits (roughly
  15 requests/minute on Flash-Lite). The script paces calls 4.5s apart to
  avoid 429 errors; raising the candidate cap will make the run take longer.
- **Rate-limit circuit breaker**: if `CONSECUTIVE_RATE_LIMIT_BREAKER`
  (currently 5) candidates in a row fail with 429 even after retries, the
  run stops evaluating further candidates instead of retrying every
  remaining one — this protects against a genuine daily-quota exhaustion
  turning into a 25-minute timeout that saves nothing. Anything left
  unevaluated when this triggers is never logged, so it's automatically
  reconsidered fresh on the next run.
- **The bot always sends an email now, even on a 0-match day** — including
  a "Sources today" line showing how many raw listings each source
  returned. This makes source outages visible at a glance (e.g. "Naukri: 0"
  every day means that source needs attention) without needing to open
  the Action logs each time.

## Known Sheet setup issue

If your Sheet's header row still reads `Score | Fit` instead of
`Fit Score | Reason`, the columns are just mislabeled (data is correct, only
the header text is wrong) — rename those two header cells directly in the
Sheet. This isn't something the script can fix since it only appends rows,
it never touches row 1.


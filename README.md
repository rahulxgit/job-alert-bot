# Job Alert Bot

Scrapes LinkedIn, Google Jobs, Internshala (all-India), Naukri,
(best-effort) Wellfound, optional LinkedIn recruiter posts,
Greenhouse/Lever company career pages, Arbeitnow, RemoteOK, and
(optional) Firecrawl web search/extraction every morning. (Glassdoor and
ZipRecruiter were tried and removed — both are fully blocked from GitHub
Actions, see limitations below.) Runs a cheap keyword pre-filter, then
sends the shortlist to Gemini (free tier) to actually read each job
description against my resume and decide real fit — not just keyword
overlap. For jobs that pass, tries to find a real recruiter/company email
for outreach. Logs new matches to a Google Sheet and emails me the digest.
Runs on GitHub Actions so it doesn't depend on my laptop being on.

## Architecture (refactored into modules)

The bot was refactored from a single ~1700-line script into a modular
package. Entry point is now `main.py` (was `config.py (or the relevant module in sources/, ai/, etc.)`) — the
workflow and all environment variable names are unchanged, so no secrets
need updating.

```
main.py            entry point — orchestrates the pipeline
config.py           all env vars, search terms, keyword lists, constants
models.py            JobListing, FitVerdict dataclasses
scheduler.py          optional local-loop runner (GH Actions handles real scheduling)
utils/                logging, retry/backoff, hard-timeout helper, text parsing
sources/               one file per source, each implementing fetch_listings()
ai/                     Gemini provider, gateway fallback, prefilter, evaluator
enrichment/              recruiter email chain (JD -> Hunter -> Apollo)
sheets/                  Google Sheets dedup logging
mailer/                  Gmail digest (named mailer/, not email/ — email/ would
                         shadow Python's own stdlib email module)
tests/                   pytest suite for the pure-logic pieces (no network needed)
```

Every source in `sources/` is fully isolated — `main.py`'s `fetch_all()`
catches any unexpected exception per-source, so one source breaking can
never take down the rest of the run. This was already true in the
monolith's `try/except` blocks; the refactor just makes it structurally
enforced rather than convention-based.

## How it fits together

```
GitHub Actions (cron, 8 AM IST)
        ↓
main.py
        ↓
jobspy scrapes LinkedIn + Google Jobs (Indeed removed at user request)
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
My self-hosted AI gateway (github.com/rahulxgit/ai-gateway) reads each
remaining JD against my actual resume/profile first — it already fails
over across 7+ providers internally, so this is the primary review path
        ↓ (only if the gateway itself fails outright)
falls back to Gemini directly, scores genuine fit 0-100, rejects unpaid
internships and roles that need real professional experience
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
- **Apollo's domain-filter parameter is not 100% verified.** The
  `q_organization_domains_list` parameter used in `apollo_find_contact` was
  inferred from general knowledge of Apollo's API rather than a directly
  confirmed doc example — Apollo's official docs snippets found during
  development showed `person_titles`/`person_locations` clearly but not
  the exact domain-filter param name. If Apollo lookups consistently
  return nothing despite a valid key, this parameter name is the first
  thing to double-check against Apollo's current API reference.
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
  `GREENHOUSE_BOARDS` or `LEVER_BOARDS` at the top of `config.py (or the relevant module in sources/, ai/, etc.)`.
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
  that plugs into `config.py (or the relevant module in sources/, ai/, etc.)`.
- **YouTube descriptions are parsed for individual job links, not treated
  as one lump per video.** Each video's description is split line by line,
  and every real job/apply link found becomes its own separate candidate
  — with the surrounding line of text as a title guess — instead of the
  whole video (which might bundle 5-10 different postings) being judged
  as a single unit. Social/messaging/self-promo links (Instagram,
  Telegram, WhatsApp, the channel's own YouTube links) are filtered out
  automatically before being treated as job links. If a video's
  description has no parseable links at all — some channels talk through
  openings verbally instead of linking them — it falls back to treating
  the video itself as one candidate, so nothing is silently dropped
  either way. One residual limitation: link-aggregator pages like
  Linktree aren't followed/resolved, so a channel that only posts a
  single Linktree link per video (rather than direct per-company links)
  won't get its individual postings extracted — that whole link is
  filtered out as non-job noise instead.
  Channel resolution is URL-based and deterministic now (see step 8 in
  setup) — `/channel/` and `/@handle` links resolve exactly, with no
  fuzzy-matching risk. Legacy `/c/` or `/user/` URLs still fall back to a
  name search and carry the old mismatch risk, so prefer `/@handle` or
  `/channel/` links when adding a channel.
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
~25 lookups/month, so each run caps itself at just 1 call to actually last
the month instead of spiking out in a couple of days.

1. Go to https://hunter.io → sign up free (no card needed for the free tier).
2. Dashboard → API → copy your API key.

### 7. (Optional) Apollo.io key — final email fallback, tried after Hunter
Only used if both the JD-extraction and Hunter tiers come up empty. Free
tier is ~50 credits/month (better than Hunter's), and unlike Hunter's
generic company-pattern guess, Apollo can return an actual **named**
person (name + title + email) — genuinely more useful for a personalized
"Hi [Name]," referral ask. Same sustainability logic: capped at 1 call/run.

1. Go to https://www.apollo.io → sign up free (a work/corporate-style
   email address tends to go through signup more smoothly than a personal
   Gmail).
2. Settings → Integrations → API Keys → create a key. Copy it.

### 8. (Optional) YouTube Data API key — for job-alert channel scraping
Official free API, no scraping — reads recent videos + descriptions from
placement/job-alert YouTube channels. Free tier is 10,000 units/day,
comfortably covers this.

1. In the same Google Cloud project as steps 2-4, go to
   https://console.cloud.google.com/apis/library/youtube.googleapis.com
   → Enable.
2. Go to https://console.cloud.google.com/apis/credentials → Create
   Credentials → API key. Copy it.
3. (Recommended) Click into the new key → restrict it to only the
   "YouTube Data API v3" under API restrictions, so it can't be misused
   for anything else if it ever leaks.

Two independent lists at the top of `config.py (or the relevant module in sources/, ai/, etc.)`, both starting empty
until real URLs are added — currently configured:

- **`YOUTUBE_CHANNEL_URLS`** — scans each channel's recent uploads
  (last 48h, up to `YOUTUBE_MAX_VIDEOS_PER_CHANNEL` = 3 latest videos per
  channel). Currently 9 channels: KN Academy, Anu Sharma, Lokesh Bagora,
  OnlineStudy4u, learningwithram1299, hiremeplz, ashishcode, Foundthejob,
  HireWithHarsh. Direct `/@handle` or `/channel/` links resolve
  deterministically and cheaply; avoid legacy `/c/` or `/user/` URLs
  where possible since those fall back to a fuzzy name search instead.
- **`YOUTUBE_VIDEO_URLS`** — checks specific individual videos directly
  (not a whole channel), e.g. a one-off video someone shared. Currently
  empty. Cheaper than the channel path since there's no resolution step —
  one API call per video. Whatever's in this list gets re-checked every
  run, but the existing job-URL dedup means an already-logged video's job
  never gets written to the sheet twice, so it's safe to leave old video
  URLs in this list indefinitely.

### 9. GitHub repo secrets
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
| `APOLLO_API_KEY` | optional, from step 7 — omit entirely to skip this fallback |
| `YOUTUBE_API_KEY` | optional, from step 8 — omit entirely to skip this source |
| `AI_GATEWAY_URL` | optional — omit entirely to use the default `https://ai-gateway-wx35.onrender.com`; only set this if the gateway is redeployed elsewhere |

### 10. ⚠️ Update the Sheet header row before running again
The script now appends a 9th column (`Source`) after `Email`. Insert a
new column for `Source` between `Email` and `Applied` (if you've added an
`Applied` column already) before running again — otherwise new rows will
write the source platform into whatever column currently sits in that 9th
position, silently colliding with your `Applied` tracking. Header row
should read:
`URL | Title | Company | Location | Fit Score | Reason | Date Added | Email | Source | Applied`

`Source` shows exactly which platform each job came from —
Linkedin, Google, Internshala, Naukri, Wellfound, Greenhouse, Lever,
YouTube, or LinkedIn Posts — so you can see directly, every day, which
sources are actually contributing to your final matches instead of
guessing from the Action logs.

### 11. Push and test
Push this repo to GitHub, then go to Actions → Daily Job Alert → Run workflow
to trigger it manually and confirm it works before waiting for the 8 AM cron.

## Tuning

- `SEARCH_TERMS`, `LOCATIONS`, `PROFILE_KEYWORDS`, `PRIORITY_COMPANIES`,
  `INTERNSHALA_SEARCH_TERMS` are all at the top of `config.py (or the relevant module in sources/, ai/, etc.)`.
- **`data/profile-data.json` now drives `CANDIDATE_PROFILE` automatically** —
  this is a copy of the same source-of-truth file the resume-portfolio-sync
  skill uses. Whenever the resume/portfolio changes, update
  `data/profile-data.json` in this repo and push — `config.py (or the relevant module in sources/, ai/, etc.)` rebuilds
  the profile text Gemini reads from this file at the start of every run,
  no manual script edits needed anymore. If the file is ever missing or
  malformed, the script falls back to a minimal generic profile and logs a
  warning rather than crashing.
- `LLM_FIT_THRESHOLD` (currently 60) controls how strict Gemini's review is.
  Raise it if the digest is too noisy, lower it if too sparse.
- `MAX_LLM_CANDIDATES` (currently 60, raised from 40 after a real run
  confirmed the cap was actually being hit) caps how many jobs get sent
  for review per run. As of the 22-term search expansion, jobspy's own
  scraping (~31 min for 44 term×location combos) is the actual time
  bottleneck now, not this review stage — a run with 40 candidates
  completed comfortably inside the timeout with room to spare, which is
  why this was raised.
- **Log timestamps for anything after the jobspy stage were previously
  unreliable** — Python's `print()` output is block-buffered when not
  connected to a live terminal (which is what GitHub Actions gives it),
  so dozens of log lines could appear with nearly identical timestamps,
  clustered at the very end, even though the actual work happened spread
  out over real time. Fixed by running `python -u config.py (or the relevant module in sources/, ai/, etc.)` in the
  workflow (unbuffered stdout) — logs from any run after this fix reflect
  real timing accurately.
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

## Outreach prioritization

Since the actual strategy is cold email / referral outreach rather than
portal applications, the pipeline now actively favors contactable jobs at
two points, without loosening the quality bar:

1. **Pre-filter boost** — a listing with a directly-published email in its
   JD gets +4 in the keyword pre-filter score, so it's more likely to
   survive the cut down to the ~55 candidates sent to Gemini, instead of
   being trimmed purely on keyword/fresher-signal strength.
2. **Final ordering** — after Gemini review and email-finding, results are
   re-sorted by (has a contact, fit score) instead of fit score alone.
   Jobs with a found email — from the JD directly, or either paid-API
   fallback — appear first in both the Sheet and the email digest, marked
   with 📧 in the email. Fit score still breaks ties and is still the
   actual quality gate: a mediocre-fit job with a contact never displaces
   a genuine fit without one, this only reorders what already passed
   review.

**Email lookup is a three-tier chain**, each tried only if the previous
one comes up empty: JD-published email (free, most reliable) → Hunter.io
generic domain pattern (1 call/run) → Apollo.io named-person search (1
call/run, tried last since it's the most valuable when it hits — an
actual name + title, not just a pattern guess). Both paid-API tiers are
spent on the **highest-fit job that doesn't already have an email**, since
`enrich_with_emails` runs on the already fit-sorted list before the final
contact-based re-sort — so the limited quota goes to the best-fit
candidate that needs it most, not whichever job happens to be processed
first.

## Confirmed bug fix #2 — adaptive Gemini quota detection (found via a real run log)

A run on July 12 hit the 40-minute timeout despite the AI gateway fallback
working perfectly (12/12 successful fallback calls, zero gateway
failures). The actual cause: Gemini's daily quota was fully exhausted for
the entire run — every single call hit 429 — but the script didn't know
that until each candidate individually spent the full 90-second retry
sequence (15s + 30s + 45s) proving it, before finally falling back. With
up to 55 candidates all guaranteed to fail the same way, that's over 80
minutes of pure wasted waiting on a conclusion already reached on
candidate #1.

Fixed with adaptive detection: the first time a candidate exhausts
Gemini's retries and falls back, a flag is set for the rest of that run.
Every subsequent candidate then tries Gemini exactly once (no backoff
wait) before going straight to the gateway — since we already know
retrying won't help today. This turns ~90 wasted seconds/candidate into
effectively zero once exhaustion is confirmed. `MAX_LLM_CANDIDATES` was
also trimmed from 55 to 40 as a safety margin, since even with this fix,
every candidate on an exhausted day still costs a real gateway call
(~10-45s) instead of the old 4.5s happy-path pacing.

## Confirmed bug fix (found via a real run log, not speculation)

A run on July 12 got cancelled with zero explanation in the logs — just a
21-minute silent gap between the last log line and GitHub's own job
timeout killing it. Root cause: `jobspy`'s internal HTTP calls don't
reliably enforce their own timeout, so when LinkedIn or Google stalls a
connection instead of failing cleanly, the call can hang indefinitely.

Fixed by running each term/location combo in a daemon thread with a hard
90-second timeout (`JOBSPY_CALL_TIMEOUT_SECONDS`). If a combo doesn't
finish in time, the run logs a warning and moves on immediately instead of
hanging. Daemon thread specifically matters here — Python can't force-kill
a thread stuck on a network call, so a *non-daemon* thread left behind
would have blocked the whole script's own exit at the very end; a daemon
thread gets torn down automatically by the interpreter instead. Workflow
timeout has since been raised further (now 55 minutes) as the search
terms expanded and jobspy's real scraping time grew alongside it.

**Honest worst-case math**: with 22 search terms × 2 locations = 44
combos, if every single one hit the full 90-second timeout, jobspy alone
could theoretically take up to 66 minutes — more than the 55-minute
workflow timeout. In practice, a real run completed all 44 combos in
~31 minutes (most combos finish in a few seconds; only genuinely stuck
ones hit the full 90s), so this hasn't been an issue, but a sufficiently
unlucky day with many stalled connections at once could still in theory
approach the timeout. If that ever happens, lowering
`JOBSPY_CALL_TIMEOUT_SECONDS` (trading a bit of per-combo patience for a
lower worst-case ceiling) is the first lever to pull.

## Self-audit fixes (found by code review, not a test run)

- **`HUNTER_MAX_CALLS_PER_RUN` was set to 15, but Hunter's free tier is
  ~25/month total.** Running daily, that would have exhausted the entire
  month's quota in under 2 days, then silently returned nothing for the
  rest of the month. Fixed to 1/run — a genuinely sustainable pace that
  actually lasts the month instead of spiking and going dark.
- **YouTube channel resolution had no sanity check.** Several channel names
  in the list are generic words (`Unstop`, `Scaler`, `Freshers Now`,
  `College Wallah`) where YouTube's search could plausibly match an
  unrelated channel, and this would have happened silently — pulling the
  wrong channel's videos every day with no indication anything was wrong.
  Now logs a clear `[warn]` if the resolved channel's title doesn't share
  any meaningful word with the name it was searched for.
- **Wellfound's `__NEXT_DATA__` parser had no recursion depth limit.**
  Next.js state can nest deeply; without a cap this risked either a
  `RecursionError` (caught gracefully, but still wasted the attempt) or
  just running slowly on a large page, eating into the run's time budget.
  Capped at depth 25.

## Firecrawl integration (web research/extraction — additive)

Firecrawl is a discovery layer, not another dedicated scraper like Naukri
or Greenhouse. Where the other sources hit one fixed site each, Firecrawl
runs a batch of web searches (`role + fresher + location`, e.g. "React
Developer fresher Bangalore") through Firecrawl's `POST /v2/search` API,
which returns each result's URL, title, and scraped page content in a
single call. Every result it finds is normalized into the same
`JobListing` shape everything else uses, so it flows through the exact
same pipeline — dedupe, keyword pre-filter, AI fit review (against
`profile-data.json`, same as every other source), recruiter-email
enrichment, Sheet logging, digest email. There is no separate Firecrawl
pipeline or matching logic.

```
Naukri / LinkedIn / Greenhouse / Lever / ... (existing dedicated sources)
                              +
                Firecrawl (broad web search/extraction)
                              ↓
                     normalized JobListing
                              ↓
                  existing pipeline (unchanged)
```

**Why the REST API and not the MCP server:** the Firecrawl MCP server is
built for an interactive session where a client approves each tool call —
there's no human in the loop on a GitHub Actions cron run. The
`/v2/search` API gives the identical capability (search + scrape in one
request) without needing a live MCP client, so it's the CI-compatible way
to get the same thing. If you're using this profile/config from an
interactive Claude session instead, Firecrawl's MCP `search` tool does
the same job.

**On "as many jobs as possible":** Firecrawl's `/v2/search` endpoint (as
of its current API reference) has no cursor/offset pagination — `limit`
is capped at 100 results per call, full stop. So breadth here comes from
running many distinct queries (`FIRECRAWL_MAX_QUERIES`), not from paging
a single query. `config.py` builds one query per role x location
combination (11 roles x 3 locations = 33 queries, each rotated across
four experience-level phrasings — "fresher", "0-1 years experience",
"entry level", "graduate" — so the same combo isn't asked the same way
every time), plus 5 site-targeted queries pointed at Naukri, LinkedIn
Jobs, Greenhouse, Lever, and Indeed via the `site:` operator. That's 38
queries total, and `FIRECRAWL_MAX_QUERIES` defaults to running all of
them — override it lower only if a run is bumping into the time budget.

### Enabling it

1. Sign up at https://www.firecrawl.dev and copy an API key (starts with `fc-`).
2. Add it as a GitHub repo secret named `FIRECRAWL_API_KEY` (Settings →
   Secrets and variables → Actions).
3. That's it — the source auto-detects the key and turns itself on. Omit
   the secret entirely to skip Firecrawl and keep running every other
   source unchanged.

### Configuration

All optional, all with safe defaults — set these as repo secrets or
environment variables only if you want to change the defaults:

| Variable | Default | What it controls |
|---|---|---|
| `FIRECRAWL_API_KEY` | (none) | Required to enable the source at all |
| `FIRECRAWL_ENABLED` | `true` | Set to `false` to turn it off without removing the key |
| `FIRECRAWL_MAX_RESULTS_PER_QUERY` | `10` | Results pulled per search query — hard-capped at 100 (Firecrawl's own `/v2/search` ceiling) |
| `FIRECRAWL_MAX_QUERIES` | `38` (all generated queries) | How many of the generated role/location/site-targeted searches actually run |
| `FIRECRAWL_MAX_TOTAL_RESULTS` | `150` | Hard ceiling across the whole source, checked as queries run so it can stop early |
| `FIRECRAWL_TIMEOUT` | `30` | Per-request timeout (seconds) |

### Posting date (best-effort)

`/v2/search` doesn't return a structured posting-date field for web
results (only its separate "news" source type does, and this source only
requests "web"), so `JobListing.posting_date` is filled in — when
possible — by scanning the scraped page text for common phrasings:
"posted N days/hours/weeks/months ago", "posted today"/"just posted", or
a bare ISO date near the top of the page. This is best-effort text
matching, not a guarantee; if none of those patterns show up,
`posting_date` is just left empty, exactly as it already is for every
other source that doesn't populate it. Nothing downstream depends on it
being set.

The actual search queries are built in `config.py` from
`FIRECRAWL_ROLE_TERMS x FIRECRAWL_LOCATIONS` (roles like "React Developer",
"Full Stack Developer", "Software Engineer" fresher-qualified, across
Bangalore/Pune/India) — edit those two lists directly to change what it
searches for, rather than a runtime flag.

### Local testing

```bash
export FIRECRAWL_API_KEY="fc-..."
python -c "from sources.firecrawl import FirecrawlSource; rows = FirecrawlSource().fetch_listings(); print(len(rows)); print(rows[0] if rows else 'no results')"
```

Run just its tests (fully mocked, no real API calls, no key needed):

```bash
pytest tests/test_firecrawl.py -v
```

### How it differs from the dedicated sources

Naukri/Greenhouse/Lever/etc. each know exactly one site's structure and
hit it directly — reliable when the site cooperates, blind everywhere
else. Firecrawl is broad instead of deep: it doesn't know any one site's
markup, it searches the open web and scrapes whatever comes back, so it
picks up company career pages, smaller job boards, and postings the
dedicated sources were never built to reach — at the cost of being noisier
and needing the existing pre-filter/AI-review stages to actually be
useful. It's additive coverage, not a replacement for anything above.

## Known Sheet setup issue

If your Sheet's header row still reads `Score | Fit` instead of
`Fit Score | Reason`, the columns are just mislabeled (data is correct, only
the header text is wrong) — rename those two header cells directly in the
Sheet. This isn't something the script can fix since it only appends rows,
it never touches row 1.


# Job Alert Bot

Scrapes Indeed, LinkedIn, Google Jobs, Internshala, and Naukri every
morning, runs a cheap keyword pre-filter, then sends the shortlist to
Gemini (free tier) to actually read each job description against my resume
and decide real fit — not just keyword overlap. Logs new matches to a
Google Sheet and emails me the digest. Runs on GitHub Actions so it doesn't
depend on my laptop being on.

## How it fits together

```
GitHub Actions (cron, 8 AM IST)
        ↓
job_search.py
        ↓
jobspy scrapes Indeed + LinkedIn + Google Jobs
        +
custom scraper pulls paid internships from Internshala
        +
custom scraper hits Naukri's internal search API directly
        ↓
keyword pre-filter (cheap) — cuts hundreds of listings down to ~40 candidates
        ↓
dedup against Google Sheet — drop anything already logged before
        ↓
Gemini API reads each remaining JD against my actual resume/profile,
scores genuine fit 0-100, rejects unpaid internships and roles that
need real professional experience
        ↓
log the survivors to the Sheet
        ↓
email the digest via Gmail API
```

## Known limitations (be aware of these)

- **Wellfound and Y Combinator's job board (Work at a Startup) are not
  included.** Both require a logged-in session and JS rendering to browse —
  they can't be reliably scraped by a headless script the way Indeed/LinkedIn
  can. If you want startup-specific listings, Internshala and the Google Jobs
  aggregator (which pulls from many boards) are the closest reliable proxies
  right now.
- Internshala's HTML structure can change without notice, which would break
  the scraper silently — watch the Action logs occasionally.
- **Naukri is the most fragile source.** It's pulled via an internal search
  API (`naukri.com/jobapi/v3/search`) that their own site uses but isn't
  officially documented or supported — Naukri can change required headers,
  rate-limit harder, or restructure the response at any time without notice.
  If Naukri listings suddenly drop to zero in the logs, this is the first
  place to check.
- The Gemini review step calls the API once per shortlisted job (up to 40
  calls/run, paced ~4.5s apart to respect free-tier rate limits) — this is
  free but means a run can take several minutes.

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

### 5. GitHub repo secrets
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

### 6. Push and test
Push this repo to GitHub, then go to Actions → Daily Job Alert → Run workflow
to trigger it manually and confirm it works before waiting for the 8 AM cron.

## Tuning

- `SEARCH_TERMS`, `LOCATIONS`, `PROFILE_KEYWORDS`, `PRIORITY_COMPANIES`,
  `INTERNSHALA_SEARCH_TERMS` are all at the top of `job_search.py`.
- `CANDIDATE_PROFILE` is the text block Gemini actually reads to judge fit —
  keep this in sync with `profile-data.json` from the resume-portfolio-sync
  skill whenever the resume changes.
- `LLM_FIT_THRESHOLD` (currently 60) controls how strict Gemini's review is.
  Raise it if the digest is too noisy, lower it if too sparse.
- `MAX_LLM_CANDIDATES` (currently 40) caps how many jobs get sent to Gemini
  per run — kept conservative to stay within free-tier rate limits (roughly
  15 requests/minute on Flash-Lite). The script paces calls 4.5s apart to
  avoid 429 errors; raising the candidate cap will make the run take longer.


# Job Alert Bot

Scrapes Indeed, LinkedIn and Naukri every morning, filters for SDE-1 / full-stack
roles that actually match my profile, logs new ones to a Google Sheet, and
emails me a digest. Runs on GitHub Actions so it doesn't depend on my laptop
being on.

## How it fits together

```
GitHub Actions (cron, 8 AM IST)
        ↓
job_search.py
        ↓
jobspy scrapes Indeed + LinkedIn + Naukri
        ↓
score against my resume keywords, drop anything below threshold
        ↓
check Google Sheet for URLs already logged (dedup)
        ↓
append new rows to the Sheet
        ↓
email the new matches via Gmail API
```

## One-time setup

### 1. Google Sheet
Create a sheet called "Job Search Tracker" with a header row:
`URL | Title | Company | Location | Score | Date Added`
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

### 4. GitHub repo secrets
Repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret name | Value |
|---|---|
| `GOOGLE_SHEET_ID` | the sheet ID from step 1 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | full contents of the service account JSON |
| `GMAIL_CLIENT_ID` | from step 3 |
| `GMAIL_CLIENT_SECRET` | from step 3 |
| `GMAIL_REFRESH_TOKEN` | from step 3 |
| `ALERT_EMAIL_TO` | rahulkumarshc00@gmail.com |

### 5. Push and test
Push this repo to GitHub, then go to Actions → Daily Job Alert → Run workflow
to trigger it manually and confirm it works before waiting for the 8 AM cron.

## Tuning

- `SEARCH_TERMS`, `LOCATIONS`, `PROFILE_KEYWORDS`, `PRIORITY_COMPANIES` are
  all at the top of `job_search.py` — edit directly as the search evolves.
- `min_score` in `filter_and_rank()` controls how strict the matching is.
  Start at 3, raise it if the digest is too noisy.

## Known limitations

- LinkedIn scraping through jobspy is rate-limited and occasionally blocked —
  the script just logs a warning and moves on if one site fails.
- Naukri listings sometimes lack full descriptions, which can undercount the
  keyword score for otherwise good matches.

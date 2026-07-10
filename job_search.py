"""
Daily job alert bot.

Pulls fresher/SDE-1 listings from Indeed, LinkedIn, Google Jobs (via jobspy),
Internshala (paid internships only), Naukri (via their internal search API),
and Wellfound (best-effort — Wellfound actively blocks scrapers, so this
one frequently returns nothing; see README), runs a cheap keyword pre-filter
to cut the list down, then sends the survivors to the Gemini API to actually
read each job description against my resume and decide real fit — not just
keyword overlap. Logs matches to a Google Sheet so I don't see repeats, and
emails me the digest.

Run manually with:  python job_search.py
Runs automatically every day at 8 AM IST via .github/workflows/job-alerts.yml
"""

import base64
import json
import os
import time
from datetime import datetime
from email.mime.text import MIMEText

import gspread
import pandas as pd
import requests
from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from jobspy import scrape_jobs

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SEARCH_TERMS = [
    "SDE 1",
    "Software Development Engineer",
    "Full Stack Developer",
    "Backend Developer",
]

LOCATIONS = ["Bengaluru, India", "India"]
SITES = ["indeed", "linkedin", "google"]
RESULTS_PER_SITE = 30
HOURS_OLD = 24

INTERNSHALA_SEARCH_TERMS = ["full-stack-development", "software-development", "web-development"]
NAUKRI_SEARCH_TERMS = ["sde 1", "software developer fresher", "full stack developer fresher"]

# Pre-filter keywords — cheap first pass to shrink the list before paying for LLM calls
PROFILE_KEYWORDS = [
    "react", "next.js", "nextjs", "node", "express", "typescript", "javascript",
    "mongodb", "postgresql", "prisma", "mysql", "supabase", "firebase",
    "rest api", "mern", "full stack", "fullstack", "ai agents",
    "rag", "llm", "mcp", "docker", "git", "ci/cd", "python", "java", "c++",
]

FRESHER_SIGNALS = [
    "sde 1", "sde-1", "sde i", "software development engineer i",
    "fresher", "0-1 year", "0-2 year", "0 - 2 year", "0-2 yrs",
    "entry level", "entry-level", "graduate engineer", "graduate trainee",
    "junior", "campus hire", "new grad", "intern",
]

SENIORITY_EXCLUSIONS = [
    "senior", "sr.", "sr ", "staff", "principal", "lead", "architect",
    "manager", "director", "head of", "vp ", "9-12 yr", "6-9 yr", "5-8 yr",
    "8+ year", "10+ year", "7+ year", "6+ year", "5+ year", "4+ year",
]

PRIORITY_COMPANIES = [
    "razorpay", "sarvam", "groww", "meesho", "zepto", "cred", "swiggy",
    "zomato", "flipkart", "postman", "browserstack", "freshworks",
]

# How many pre-filtered candidates to actually send to the LLM per run —
# caps API spend even on a day with a huge raw pull
MAX_LLM_CANDIDATES = 40
LLM_FIT_THRESHOLD = 60  # 0-100 scale; only keep jobs Gemini scores at or above this

SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GMAIL_TO = os.environ["ALERT_EMAIL_TO"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Optional — only set this if you want the LinkedIn recruiter-post scraper
# (see fetch_linkedin_posts_listings below). Leave unset to skip it entirely.
LINKEDIN_LI_AT_COOKIE = os.environ.get("LINKEDIN_LI_AT_COOKIE", "")
LINKEDIN_POST_SEARCH_TERMS = ["hiring software engineer fresher", "hiring sde 1", "hiring full stack developer"]

# My actual background — this is what the LLM checks each job against.
# Keep this in sync with resume-portfolio-sync's profile-data.json.
CANDIDATE_PROFILE = """
Rahul Kumar — final-year B.Tech CSE student, NIT Raipur (2022-2026), CGPA 8.67.
Targeting: SDE-1 / Junior Software Engineer roles, and paid internships, at
Indian product companies, AI-first startups, and funded companies, preferably Bengaluru.

Experience: SDE Intern at Bluestock Fintech (Feb-Mar 2026, remote). Built and shipped
three production projects: Logic Looper (client-first daily puzzle platform — React,
Redux Toolkit, IndexedDB, Node.js, Express, PostgreSQL/Prisma, ~70% reduction in API
calls, ~60% server load reduction via CDN-first ISR, 500+ concurrent users, 100%
offline capable), an open-source AI Profile Picture Maker, and The Corporate Blog.

Key projects:
- DriveClone: MERN Google Drive clone with a native MCP server letting AI agents
  interact with the drive directly — JWT auth, Cloudinary storage, deployed on
  Render/Vercel. Strongest AI-engineering differentiator.
- AI Inference Playground: React/TypeScript LLM inference playground with token
  streaming, live latency metrics, WCAG AA accessibility, custom diff viewer.
- Smart Bookmark App: Next.js + Supabase, SSR auth, layered architecture.
- Realtime Gallery: React + Zustand + InstantDB, real-time multi-user sync.

Tech stack: JavaScript, TypeScript, Java, Python, C++, SQL, React, Next.js,
Redux, Node.js, Express, MongoDB, PostgreSQL, MySQL, Prisma, Supabase, Firebase,
REST APIs, MCP servers, RAG pipelines, Claude/OpenAI API integration, Docker,
Git, GitHub Actions, Vercel, Render.

Achievements: 500+ DSA problems solved (LeetCode rating 1800+), 99.41 percentile
Naukri Young Turks 2025, TCS CodeVita Season 13 rank ~8,552. Leadership: Sponsorship
& Outreach Lead at NIT Raipur Innovation Cell, Technical Events Coordinator at
Robotics Club, co-organized a 200+ participant national hackathon.

Strongest positioning: the AI-engineering layer (MCP servers, RAG, LLM API
integrations) that's usually missing from a typical MERN-fresher profile.
NOT a fit for: senior/staff/lead/principal roles, roles requiring 3+ years
of professional experience, unpaid internships.
"""


# ---------------------------------------------------------------------------
# Sources — jobspy sites
# ---------------------------------------------------------------------------

def fetch_jobspy_listings() -> pd.DataFrame:
    all_results = []
    for term in SEARCH_TERMS:
        for location in LOCATIONS:
            try:
                df = scrape_jobs(
                    site_name=SITES,
                    search_term=term,
                    google_search_term=f"{term} jobs near {location}",
                    location=location,
                    results_wanted=RESULTS_PER_SITE,
                    hours_old=HOURS_OLD,
                    country_indeed="India",
                    linkedin_fetch_description=True,
                )
                if df is not None and not df.empty:
                    all_results.append(df)
            except Exception as exc:
                print(f"[warn] scrape failed for '{term}' in '{location}': {exc}")

    if not all_results:
        return pd.DataFrame()

    combined = pd.concat(all_results, ignore_index=True)
    return combined[["job_url", "title", "company", "location", "description"]]


# ---------------------------------------------------------------------------
# Source — Internshala (paid internships)
# ---------------------------------------------------------------------------

def fetch_internshala_listings() -> pd.DataFrame:
    """
    Internshala's search pages are plain server-rendered HTML, so a simple
    request + BeautifulSoup parse works without a browser. We only keep
    listings that explicitly show a paid stipend — unpaid internships are
    dropped right here before anything else touches them.
    """
    rows = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for term in INTERNSHALA_SEARCH_TERMS:
        url = f"https://internshala.com/internships/{term}-internship/"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
        except Exception as exc:
            print(f"[warn] internshala fetch failed for '{term}': {exc}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div.individual_internship")

        for card in cards:
            title_el = card.select_one("h3.job-internship-name a")
            company_el = card.select_one("p.company-name")
            stipend_el = card.select_one("span.stipend")
            location_el = card.select_one("a.location_link")

            if not title_el:
                continue

            stipend_text = stipend_el.get_text(strip=True) if stipend_el else ""
            # Internshala marks unpaid ones explicitly — skip those outright
            if "unpaid" in stipend_text.lower():
                continue

            link = title_el.get("href", "")
            full_url = f"https://internshala.com{link}" if link.startswith("/") else link

            rows.append({
                "job_url": full_url,
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True) if company_el else "",
                "location": location_el.get_text(strip=True) if location_el else "India",
                "description": f"Internship. Stipend: {stipend_text}",
            })

        time.sleep(1)  # be polite between requests

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Source — Naukri (via their internal search API — not officially documented,
# so this is the most likely source to break if Naukri changes something)
# ---------------------------------------------------------------------------

def fetch_naukri_listings() -> pd.DataFrame:
    """
    Naukri's own site calls a JSON search API under the hood
    (naukri.com/jobapi/v3/search) rather than server-rendering everything.
    That's what we call here instead of parsing HTML. This endpoint isn't
    officially documented or supported by Naukri, so it can break without
    notice if they change headers, rate-limit harder, or restructure the
    response — treat it as the most fragile of the four sources.
    """
    rows = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "appid": "109",
        "systemid": "Naukri",
        "clientid": "d3skt0p",
    }

    for term in NAUKRI_SEARCH_TERMS:
        params = {
            "noOfResults": 20,
            "urlType": "search_by_key_loc",
            "searchType": "adv",
            "keyword": term,
            "location": "bangalore",
            "k": term,
            "l": "bangalore",
            "experience": 0,  # freshers only
        }
        try:
            resp = requests.get(
                "https://www.naukri.com/jobapi/v3/search",
                headers=headers,
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[warn] naukri fetch failed for '{term}': {exc}")
            continue

        for job in data.get("jobDetails", []):
            job_id = job.get("jobId", "")
            static_url = job.get("staticUrl", "")
            job_url = static_url or (
                f"https://www.naukri.com/job-listings-{job_id}" if job_id else ""
            )
            if not job_url:
                continue

            rows.append({
                "job_url": job_url,
                "title": job.get("title", ""),
                "company": job.get("companyName", ""),
                "location": job.get("placeholders", {}).get("location", "India")
                if isinstance(job.get("placeholders"), dict) else "India",
                "description": job.get("jobDescription", "") or job.get("title", ""),
            })

        time.sleep(1)  # be polite between requests

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Source — Wellfound (best-effort; Wellfound actively blocks scrapers with
# DataDome/Cloudflare, so this frequently returns nothing — that's expected,
# not a bug. See README for why this can't be made reliable without a paid
# anti-bot/proxy service.)
# ---------------------------------------------------------------------------

WELLFOUND_ROLE_SLUGS = ["software-engineer", "full-stack-engineer", "backend-engineer"]


def _find_job_like_dicts(node, found=None):
    """
    Recursively walks Wellfound's embedded __NEXT_DATA__ state looking for
    anything that looks like a job listing. We don't hardcode exact key
    paths here because Wellfound's internal schema isn't public and can
    shift — instead we duck-type: any dict with a title-like field and a
    slug/id gets treated as a candidate listing.
    """
    if found is None:
        found = []
    if isinstance(node, dict):
        has_title = any(k in node for k in ("title", "jobTitle"))
        has_identifier = any(k in node for k in ("slug", "jobListingSlug", "id"))
        if has_title and has_identifier:
            found.append(node)
        for value in node.values():
            _find_job_like_dicts(value, found)
    elif isinstance(node, list):
        for item in node:
            _find_job_like_dicts(item, found)
    return found


def fetch_wellfound_listings() -> pd.DataFrame:
    rows = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }

    for slug in WELLFOUND_ROLE_SLUGS:
        url = f"https://wellfound.com/role/{slug}"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            script_tag = soup.find("script", id="__NEXT_DATA__")
            if not script_tag or not script_tag.string:
                print(f"[warn] wellfound '{slug}': no __NEXT_DATA__ found — likely blocked (DataDome/CAPTCHA)")
                continue

            state = json.loads(script_tag.string)
            candidates = _find_job_like_dicts(state)

            for job in candidates:
                title = job.get("title") or job.get("jobTitle") or ""
                slug_val = job.get("slug") or job.get("jobListingSlug") or job.get("id") or ""
                if not title or not slug_val:
                    continue
                job_url = f"https://wellfound.com/jobs/{slug_val}" if not str(slug_val).startswith("http") else slug_val
                rows.append({
                    "job_url": job_url,
                    "title": title,
                    "company": job.get("companyName") or job.get("startupName") or "",
                    "location": job.get("locationNames") or job.get("location") or "India",
                    "description": job.get("description") or title,
                })
        except Exception as exc:
            print(f"[warn] wellfound fetch failed for '{slug}': {exc}")
            continue

        time.sleep(1)

    if not rows:
        print("[info] Wellfound returned 0 listings this run — most likely blocked by anti-bot protection, not a code bug")

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Source — LinkedIn recruiter posts (feed posts where recruiters announce
# openings directly, as opposed to formal LinkedIn Jobs listings). This is
# OPTIONAL and OFF BY DEFAULT: it only runs if LINKEDIN_LI_AT_COOKIE is set
# as a secret. Leave that secret unset to skip this entirely — nothing else
# in the pipeline depends on it.
#
# IMPORTANT RISK NOTE: this uses your personal LinkedIn session cookie
# (li_at) to call LinkedIn's internal search API. LinkedIn's feed content
# isn't visible to logged-out requests at all, so there's no way to do this
# without a real session. LinkedIn actively pursues legal action against
# scrapers and can flag/suspend accounts used for automated access. This
# was built at explicit request after that risk was flagged — if it ever
# causes account issues, remove the LINKEDIN_LI_AT_COOKIE secret and this
# source turns itself off with no other changes needed.
# ---------------------------------------------------------------------------

def fetch_linkedin_posts_listings() -> pd.DataFrame:
    if not LINKEDIN_LI_AT_COOKIE:
        print("[info] LINKEDIN_LI_AT_COOKIE not set — skipping recruiter-post source")
        return pd.DataFrame()

    rows = []
    session = requests.Session()
    session.cookies.set("li_at", LINKEDIN_LI_AT_COOKIE, domain=".linkedin.com")

    # LinkedIn requires the csrf-token header to match a JSESSIONID cookie
    # value. We fetch the feed once first just to receive that cookie.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "x-restli-protocol-version": "2.0.0",
    }

    try:
        session.get("https://www.linkedin.com/feed/", headers=headers, timeout=15)
        jsessionid = session.cookies.get("JSESSIONID", "").strip('"')
        if not jsessionid:
            print("[warn] linkedin posts: no JSESSIONID received — cookie likely expired or invalid")
            return pd.DataFrame()
        headers["csrf-token"] = jsessionid
    except Exception as exc:
        print(f"[warn] linkedin posts: session init failed: {exc}")
        return pd.DataFrame()

    for term in LINKEDIN_POST_SEARCH_TERMS:
        try:
            resp = session.get(
                "https://www.linkedin.com/voyager/api/search/dash/clusters",
                headers=headers,
                params={
                    "decorationId": "com.linkedin.voyager.dash.deco.search.SearchClusterCollection-166",
                    "origin": "GLOBAL_SEARCH_HEADER",
                    "q": "all",
                    "query": f"(keywords:{term},flagshipSearchIntent:SEARCH_SRP,"
                             f"queryParameters:(resultType:List(CONTENT)))",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[warn] linkedin posts search failed for '{term}': {exc}")
            continue

        # LinkedIn's Voyager response nests actual results inside "included" —
        # duck-type through it for anything that looks like a feed update
        # with commentary text, rather than relying on an exact fragile path.
        for item in data.get("included", []):
            text = (
                item.get("commentary", {}).get("text", {}).get("text", "")
                if isinstance(item.get("commentary"), dict) else ""
            )
            if not text or len(text) < 40:
                continue
            actor = item.get("actor", {}) if isinstance(item.get("actor"), dict) else {}
            author_name = actor.get("name", {}).get("text", "") if isinstance(actor.get("name"), dict) else ""
            permalink = item.get("permalink", "") or item.get("updateMetadata", {}).get("urn", "")

            if not permalink:
                continue

            rows.append({
                "job_url": permalink if str(permalink).startswith("http")
                else f"https://www.linkedin.com/feed/update/{permalink}",
                "title": text[:80],
                "company": author_name,
                "location": "India",
                "description": text,
            })

        time.sleep(2)  # LinkedIn rate-limits aggressively — pace conservatively

    if not rows:
        print("[info] LinkedIn recruiter-post search returned 0 — cookie may have expired or LinkedIn changed the API")

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Stage 1 — cheap keyword pre-filter (shrinks the list before paying for LLM calls)
# ---------------------------------------------------------------------------

def keyword_prefilter_score(row: pd.Series) -> int:
    title = str(row.get("title", "") or "").lower()
    description = str(row.get("description", "") or "").lower()
    company = str(row.get("company", "") or "").lower()
    full_text = f"{title} {description} {company}"

    seniority_hits = sum(term in title for term in SENIORITY_EXCLUSIONS) * 2
    seniority_hits += sum(term in description for term in SENIORITY_EXCLUSIONS)
    if seniority_hits >= 2:
        return 0

    score = 0
    score += sum(sig in full_text for sig in FRESHER_SIGNALS) * 4
    score += sum(kw in full_text for kw in PROFILE_KEYWORDS)
    if any(comp in full_text for comp in PRIORITY_COMPANIES):
        score += 3
    score -= seniority_hits
    return max(score, 0)


def prefilter(df: pd.DataFrame, min_score: int = 3) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["prefilter_score"] = df.apply(keyword_prefilter_score, axis=1)
    df = df[df["prefilter_score"] >= min_score].copy()
    df.sort_values("prefilter_score", ascending=False, inplace=True)
    return df.head(MAX_LLM_CANDIDATES)


# ---------------------------------------------------------------------------
# Stage 2 — Claude reads each JD against my actual resume/profile
# ---------------------------------------------------------------------------

GEMINI_MODEL = "gemini-2.5-flash-lite"  # free tier, generous daily quota
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


def llm_evaluate_job(title: str, company: str, description: str) -> dict:
    """
    Returns {"fit_score": int 0-100, "is_fresher_appropriate": bool, "reason": str}
    Falls back to a safe "skip" result if the API call fails, so one bad
    call doesn't crash the whole run.
    """
    prompt = f"""Here is a candidate's background:

{CANDIDATE_PROFILE}

Here is a job listing:
Title: {title}
Company: {company}
Description: {description[:3000]}

Judge whether this specific listing is a genuinely good fit for this candidate
— a fresher/final-year student — not just whether the tech stack overlaps.
Reject roles that need real professional experience even if titled "SDE 1" or
similar, and reject unpaid internships. Respond with ONLY a JSON object, no
other text, in this exact shape:
{{"fit_score": <0-100 integer>, "is_fresher_appropriate": <true/false>, "reason": "<one sentence>"}}"""

    try:
        resp = requests.post(
            GEMINI_URL,
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 200},
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)
    except Exception as exc:
        print(f"[warn] LLM evaluation failed for '{title}' @ '{company}': {exc}")
        return {"fit_score": 0, "is_fresher_appropriate": False, "reason": "evaluation failed"}


def llm_filter(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    results = []
    for _, row in df.iterrows():
        verdict = llm_evaluate_job(
            str(row.get("title", "")),
            str(row.get("company", "")),
            str(row.get("description", "")),
        )
        results.append(verdict)
        # Free-tier Gemini is rate-limited (~15 req/min on Flash-Lite) —
        # pace calls to stay comfortably under that instead of racing into 429s
        time.sleep(4.5)

    df = df.copy()
    df["fit_score"] = [r["fit_score"] for r in results]
    df["fresher_appropriate"] = [r["is_fresher_appropriate"] for r in results]
    df["reason"] = [r["reason"] for r in results]

    df = df[(df["fit_score"] >= LLM_FIT_THRESHOLD) & (df["fresher_appropriate"])].copy()
    df.sort_values("fit_score", ascending=False, inplace=True)
    return df


# ---------------------------------------------------------------------------
# Google Sheets — dedup log
# ---------------------------------------------------------------------------

def get_sheet():
    creds = ServiceAccountCredentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1


def get_seen_urls(sheet) -> set:
    urls = sheet.col_values(1)
    return set(urls[1:])


def log_new_jobs(sheet, df: pd.DataFrame):
    if df.empty:
        return
    rows = [
        [
            str(row.get("job_url") or ""),
            str(row.get("title") or ""),
            str(row.get("company") or ""),
            str(row.get("location") or ""),
            int(row.get("fit_score") or 0),
            str(row.get("reason") or ""),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ]
        for _, row in df.iterrows()
    ]
    sheet.append_rows(rows, value_input_option="USER_ENTERED")


# ---------------------------------------------------------------------------
# Gmail — send the digest
# ---------------------------------------------------------------------------

def get_gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    return build("gmail", "v1", credentials=creds)


def build_email_body(df: pd.DataFrame) -> str:
    if df.empty:
        return "No new matching listings today."

    lines = [f"{len(df)} new job(s) matched today (Gemini-reviewed):\n"]
    for _, row in df.iterrows():
        lines.append(
            f"- {row.get('title')} @ {row.get('company')} ({row.get('location')}) "
            f"— fit {row.get('fit_score')}/100\n"
            f"  Why: {row.get('reason')}\n"
            f"  {row.get('job_url')}\n"
        )
    return "\n".join(lines)


def send_email(service, body: str, job_count: int):
    subject = f"Job Alert — {job_count} new match(es), {datetime.now().strftime('%d %b')}"
    message = MIMEText(body)
    message["to"] = GMAIL_TO
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Fetching jobs from Indeed/LinkedIn/Google...")
    jobspy_df = fetch_jobspy_listings()
    print(f"  {len(jobspy_df)} listings")

    print("Fetching paid internships from Internshala...")
    internshala_df = fetch_internshala_listings()
    print(f"  {len(internshala_df)} listings")

    print("Fetching jobs from Naukri...")
    naukri_df = fetch_naukri_listings()
    print(f"  {len(naukri_df)} listings")

    print("Fetching jobs from Wellfound (best-effort, may return 0)...")
    wellfound_df = fetch_wellfound_listings()
    print(f"  {len(wellfound_df)} listings")

    print("Fetching LinkedIn recruiter posts (optional, cookie-gated)...")
    linkedin_posts_df = fetch_linkedin_posts_listings()
    print(f"  {len(linkedin_posts_df)} listings")

    raw_jobs = pd.concat(
        [jobspy_df, internshala_df, naukri_df, wellfound_df, linkedin_posts_df],
        ignore_index=True,
    )
    raw_jobs.drop_duplicates(subset=["job_url"], inplace=True)
    print(f"Pulled {len(raw_jobs)} raw listings total")

    shortlist = prefilter(raw_jobs)
    print(f"{len(shortlist)} passed the keyword pre-filter (sent to Claude for review)")

    if shortlist.empty:
        print("Nothing to review — no matches today.")
        return

    sheet = get_sheet()
    seen = get_seen_urls(sheet)
    unseen_shortlist = shortlist[~shortlist["job_url"].isin(seen)]
    print(f"{len(unseen_shortlist)} of those are new (not already logged)")

    if unseen_shortlist.empty:
        print("Everything in the shortlist was already logged before — nothing new to review.")
        return

    reviewed = llm_filter(unseen_shortlist)
    print(f"{len(reviewed)} passed Gemini's fit review (score >= {LLM_FIT_THRESHOLD})")

    log_new_jobs(sheet, reviewed)

    gmail = get_gmail_service()
    body = build_email_body(reviewed)
    send_email(gmail, body, len(reviewed))
    print("Email sent.")


if __name__ == "__main__":
    main()

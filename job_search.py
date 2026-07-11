"""
Daily job alert bot.

Pulls fresher/SDE-1 listings from Indeed, LinkedIn, Google Jobs (via
jobspy — Glassdoor and ZipRecruiter were tried and removed, both fully
blocked from GitHub Actions), Internshala (paid internships, all-India),
Naukri (via their internal search API), Wellfound (best-effort), optional
LinkedIn recruiter-post scraping (cookie-gated), company career pages via
Greenhouse/Lever public APIs, and optional YouTube job-alert channels (via
the official YouTube Data API, key-gated). Runs a cheap keyword pre-filter
to cut the list down, then sends the survivors to Gemini to actually read
each job description against my resume and decide real fit — not just
keyword overlap. If Gemini's retries are exhausted (e.g. daily quota),
falls back to my self-hosted multi-provider AI gateway
(github.com/rahulxgit/ai-gateway) as a last resort. For jobs that pass,
tries to find a real recruiter/company email — first from the JD text
itself, then optionally via Hunter.io — for cold-outreach/referral
purposes. Logs matches to a Google Sheet so I don't see repeats, and
emails me the digest.

Run manually with:  python job_search.py
Runs automatically every day at 8 AM IST via .github/workflows/job-alerts.yml
"""

import base64
import json
import os
import re
import time
from datetime import datetime, timedelta
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
SITES = ["indeed", "linkedin", "google"]  # glassdoor/zip_recruiter removed — confirmed 100% blocked from Actions, see README
RESULTS_PER_SITE = 30
HOURS_OLD = 24

INTERNSHALA_SEARCH_TERMS = ["full-stack-development", "software-development", "web-development"]
NAUKRI_SEARCH_TERMS = ["sde 1", "software developer fresher", "full stack developer fresher"]

# Company career pages via public ATS APIs — genuinely reliable (no anti-bot
# fight, these are real documented/semi-documented public endpoints), unlike
# Wellfound/Instahyre/Hirist. Only covers companies that use Greenhouse or
# Lever as their ATS — many Indian product companies (Flipkart, Swiggy,
# Zomato, etc.) run custom in-house career sites instead, which aren't
# covered here. Add a company's board token once you've confirmed it —
# wrong/missing tokens just return 0 results for that company, harmless.
#
# To find a token: visit job-boards.greenhouse.io/<token>/ or
# jobs.lever.co/<token> directly — if the page loads, that's the token.
GREENHOUSE_BOARDS = {
    "postman": "postman",  # confirmed working
    # "razorpay": "razorpay",   # unconfirmed — check before relying on it
    # "cred": "cred",           # unconfirmed
}
LEVER_BOARDS = {
    # "groww": "groww",         # unconfirmed — check before relying on it
}

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
MAX_LLM_CANDIDATES = 55
LLM_FIT_THRESHOLD = 60  # 0-100 scale; only keep jobs Gemini scores at or above this

SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GMAIL_TO = os.environ["ALERT_EMAIL_TO"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Optional — only set this if you want the LinkedIn recruiter-post scraper
# (see fetch_linkedin_posts_listings below). Leave unset to skip it entirely.
LINKEDIN_LI_AT_COOKIE = os.environ.get("LINKEDIN_LI_AT_COOKIE", "")
LINKEDIN_POST_SEARCH_TERMS = ["hiring software engineer fresher", "hiring sde 1", "hiring full stack developer"]

# Optional — only used if HUNTER_API_KEY is set. Free tier is ~25
# lookups/month, so this is capped hard per run to avoid burning the whole
# monthly quota on one day's jobs. Only called for jobs that already passed
# Gemini's review and don't already have an email found directly in the JD.
HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")
HUNTER_MAX_CALLS_PER_RUN = 1  # ~25/month free tier ÷ ~30 daily runs — 15 was blowing the whole month's quota in 2 days

# Common legal-entity suffixes to strip when guessing a company's domain
# from its name — imperfect heuristic, Hunter simply returns nothing useful
# if the guess is wrong, which is handled gracefully.
COMPANY_SUFFIXES_TO_STRIP = [
    " pvt ltd", " pvt. ltd.", " private limited", " limited", " llp",
    " inc.", " inc", " llc", " technologies", " technology", " labs",
    " solutions", " services", " systems", " india", " co.", " ltd",
]

# Optional — only used if YOUTUBE_API_KEY is set. Free quota is 10,000
# units/day; resolving a channel name costs 100 units (search.list), and
# reading its recent videos costs ~2 units, so ~21 channels is well within
# budget for one run/day. These job-alert-style channels typically post
# openings/links directly in the video description, so each recent video is
# treated as one candidate and fed through the same Gemini review as every
# other source — one video sometimes bundles multiple postings together,
# which is a known v1 simplification rather than parsing each one out.
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_NAMES = [
    "Placement Lelo", "DebugWithShubham", "Arsh Goyal", "PrepInsta",
    "College Wallah", "Unstop", "Face Prep", "Coding Ninjas", "GeeksforGeeks",
    "KN academy", "Placement Drive", "Jobs4Freshers", "Freshers Now",
    "Freshers Jobs", "Apna College", "Love Babbar CodeHelp",
    "Take U Forward Striver", "Kunal Kushwaha", "Anuj Bhaiya", "Coder Army",
    "Scaler",
]
YOUTUBE_MAX_VIDEOS_PER_CHANNEL = 3
YOUTUBE_VIDEO_MAX_AGE_HOURS = 48  # covers a daily run with some buffer

PROFILE_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "profile-data.json")

# Minimal fallback used only if profile-data.json is missing or malformed,
# so the pipeline degrades gracefully instead of crashing outright.
_FALLBACK_PROFILE = """
Final-year CSE student targeting SDE-1 / Junior Software Engineer roles and
paid internships at Indian product companies and AI-first startups.
NOT a fit for: senior/staff/lead/principal roles, roles requiring 3+ years
of professional experience, unpaid internships.
"""


def build_candidate_profile() -> str:
    """
    Builds the text block Gemini reads to judge job fit, directly from
    profile-data.json — the same source-of-truth file the resume-portfolio-sync
    skill uses. This means updating the resume/portfolio automatically flows
    through here too, instead of needing a manual edit to this script.
    """
    try:
        with open(PROFILE_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"[warn] could not load profile-data.json ({exc}) — using minimal fallback profile")
        return _FALLBACK_PROFILE

    lines = []

    name = data.get("contact", {}).get("name", "")
    headline = data.get("headline", "")
    target_roles = ", ".join(data.get("target_roles", []))
    target_focus = data.get("target_focus", "")
    lines.append(f"{name} — {headline}.")
    lines.append(f"Targeting: {target_roles} at {target_focus}.")

    for edu in data.get("education", []):
        lines.append(
            f"\nEducation: {edu.get('degree', '')}, {edu.get('institution', '')} "
            f"({edu.get('duration', '')}), {edu.get('gpa', '')}. {edu.get('notes', '')}"
        )

    for exp in data.get("experience", []):
        highlights = " ".join(exp.get("highlights", []))
        lines.append(
            f"\nExperience: {exp.get('role', '')} at {exp.get('company', '')} "
            f"({exp.get('duration', '')}, {exp.get('location', '')}). {highlights}"
        )

    if data.get("projects"):
        lines.append("\nKey projects:")
        for proj in data["projects"]:
            tech = ", ".join(proj.get("tech", []))
            lines.append(f"- {proj.get('name', '')}: {proj.get('tagline', '')}. Tech: {tech}.")

    skills = data.get("skills", {})
    if skills:
        all_skills = [s for group in skills.values() for s in group]
        lines.append(f"\nTech stack: {', '.join(all_skills)}.")

    if data.get("achievements"):
        lines.append(f"\nAchievements: {'; '.join(data['achievements'])}.")

    positioning = data.get("about_narrative", {}).get("positioning", "")
    if positioning:
        lines.append(f"\nStrongest positioning: {positioning}")

    lines.append(
        "\nNOT a fit for: senior/staff/lead/principal roles, roles requiring "
        "3+ years of professional experience, unpaid internships."
    )

    return "\n".join(lines)


CANDIDATE_PROFILE = build_candidate_profile()


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
    Internshala's search pages are server-rendered HTML, so a simple
    request + BeautifulSoup parse works without a browser — confirmed by
    directly fetching a live search page. Rather than trust a specific CSS
    class (which broke once already when Internshala's markup shifted),
    this anchors on the '/internship/detail/' URL pattern, which is a much
    more stable contract — Internshala can restyle the page freely without
    breaking this. We only keep listings that don't explicitly say
    "Unpaid" nearby — unpaid internships are dropped before anything else
    touches them.
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
        detail_links = soup.select('a[href*="/internship/detail/"]')

        seen_urls_this_page = set()
        for link_el in detail_links:
            title = link_el.get_text(strip=True)
            href = link_el.get("href", "")
            if not title or not href:
                continue

            full_url = f"https://internshala.com{href}" if href.startswith("/") else href
            if full_url in seen_urls_this_page:
                continue  # the title often appears as both a heading link and thumbnail link
            seen_urls_this_page.add(full_url)

            # Walk up to a reasonably-sized container to pull surrounding
            # context (stipend, location) without depending on exact class names.
            container = link_el.find_parent(["div", "li"])
            for _ in range(3):
                if container is None:
                    break
                text = container.get_text(" ", strip=True)
                if "₹" in text or "unpaid" in text.lower():
                    break
                container = container.find_parent(["div", "li"])

            context_text = container.get_text(" ", strip=True) if container else ""

            if "unpaid" in context_text.lower():
                continue  # drop unpaid internships before anything else touches them

            rows.append({
                "job_url": full_url,
                "title": title,
                "company": "",  # not reliably separable from context without a stable class; left blank rather than guessed wrong
                "location": "India",
                "description": context_text[:500] if context_text else title,
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.naukri.com/software-developer-fresher-jobs",
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


def _find_job_like_dicts(node, found=None, depth=0, max_depth=25):
    """
    Recursively walks Wellfound's embedded __NEXT_DATA__ state looking for
    anything that looks like a job listing. We don't hardcode exact key
    paths here because Wellfound's internal schema isn't public and can
    shift — instead we duck-type: any dict with a title-like field and a
    slug/id gets treated as a candidate listing. Depth-capped since Next.js
    state can nest deeply, and this should stay fast rather than risk
    eating into the run's time budget on a huge page.
    """
    if found is None:
        found = []
    if depth > max_depth:
        return found
    if isinstance(node, dict):
        has_title = any(k in node for k in ("title", "jobTitle"))
        has_identifier = any(k in node for k in ("slug", "jobListingSlug", "id"))
        if has_title and has_identifier:
            found.append(node)
        for value in node.values():
            _find_job_like_dicts(value, found, depth + 1, max_depth)
    elif isinstance(node, list):
        for item in node:
            _find_job_like_dicts(item, found, depth + 1, max_depth)
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
        session.get("https://www.linkedin.com/feed/", headers=headers, timeout=15, allow_redirects=True)
        jsessionid = session.cookies.get("JSESSIONID", "").strip('"')
        if not jsessionid:
            print("[warn] linkedin posts: no JSESSIONID received — cookie likely expired or invalid")
            return pd.DataFrame()
        headers["csrf-token"] = jsessionid
    except requests.exceptions.TooManyRedirects:
        print("[warn] linkedin posts: too many redirects — this means LINKEDIN_LI_AT_COOKIE is expired or "
              "invalid (LinkedIn keeps bouncing to the login page). Get a fresh li_at cookie value and "
              "update the secret.")
        return pd.DataFrame()
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
# Source — Company career pages, via public Greenhouse/Lever ATS APIs.
# This is the most reliable of the newer sources — these are real,
# semi-documented public JSON endpoints, not something fighting anti-bot
# protection. Coverage is limited to whichever priority companies actually
# use Greenhouse or Lever (see GREENHOUSE_BOARDS/LEVER_BOARDS above);
# companies running custom in-house career sites aren't covered.
# ---------------------------------------------------------------------------

def fetch_greenhouse_listings() -> pd.DataFrame:
    rows = []
    for company_name, token in GREENHOUSE_BOARDS.items():
        try:
            resp = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                params={"content": "true"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[warn] greenhouse fetch failed for '{company_name}' (token '{token}'): {exc}")
            continue

        for job in data.get("jobs", []):
            rows.append({
                "job_url": job.get("absolute_url", ""),
                "title": job.get("title", ""),
                "company": company_name,
                "location": job.get("location", {}).get("name", "India")
                if isinstance(job.get("location"), dict) else "India",
                "description": job.get("content", "") or job.get("title", ""),
            })
        time.sleep(1)

    return pd.DataFrame(rows)


def fetch_lever_listings() -> pd.DataFrame:
    rows = []
    for company_name, token in LEVER_BOARDS.items():
        try:
            resp = requests.get(
                f"https://api.lever.co/v0/postings/{token}",
                params={"mode": "json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[warn] lever fetch failed for '{company_name}' (token '{token}'): {exc}")
            continue

        for job in data:
            rows.append({
                "job_url": job.get("hostedUrl", ""),
                "title": job.get("text", ""),
                "company": company_name,
                "location": job.get("categories", {}).get("location", "India")
                if isinstance(job.get("categories"), dict) else "India",
                "description": job.get("descriptionPlain", "") or job.get("text", ""),
            })
        time.sleep(1)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Source — YouTube job-alert channels. Optional, off unless YOUTUBE_API_KEY
# is set. Uses the official YouTube Data API v3 (free tier, 10,000
# units/day) — no scraping, no ToS risk, same trust level as Gmail/Sheets.
#
# These channels typically post company/role/apply-link info directly in
# the video description, so each recent video becomes one candidate that
# flows through the same keyword pre-filter + Gemini review as every other
# source. A video that bundles several distinct openings together isn't
# split apart in this v1 — Gemini judges the video as a whole.
# ---------------------------------------------------------------------------

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def youtube_resolve_channel_id(channel_name: str) -> str:
    try:
        resp = requests.get(
            f"{YOUTUBE_API_BASE}/search",
            params={
                "key": YOUTUBE_API_KEY,
                "q": channel_name,
                "type": "channel",
                "part": "snippet",
                "maxResults": 1,
            },
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return ""

        resolved_title = items[0]["snippet"].get("title", "")
        # Sanity check: for generic/ambiguous names (Unstop, Scaler, Freshers
        # Now, etc.), YouTube's top search result could easily be an
        # unrelated channel. Flag it loudly rather than silently trusting a
        # possibly-wrong match — better to know than to quietly pull the
        # wrong channel's videos every day.
        significant_words = [w for w in channel_name.lower().split() if len(w) > 2]
        if significant_words and not any(w in resolved_title.lower() for w in significant_words):
            print(f"[warn] youtube: '{channel_name}' resolved to '{resolved_title}' — "
                  f"this looks like it might be the WRONG channel, worth checking manually")

        return items[0]["snippet"]["channelId"]
    except Exception as exc:
        print(f"[warn] youtube: couldn't resolve channel '{channel_name}': {exc}")
    return ""


def youtube_get_uploads_playlist(channel_id: str) -> str:
    try:
        resp = requests.get(
            f"{YOUTUBE_API_BASE}/channels",
            params={"key": YOUTUBE_API_KEY, "id": channel_id, "part": "contentDetails"},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if items:
            return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except Exception as exc:
        print(f"[warn] youtube: couldn't get uploads playlist for '{channel_id}': {exc}")
    return ""


def fetch_youtube_listings() -> pd.DataFrame:
    if not YOUTUBE_API_KEY:
        print("[info] YOUTUBE_API_KEY not set — skipping YouTube job-channel source")
        return pd.DataFrame()

    rows = []
    cutoff = datetime.utcnow() - timedelta(hours=YOUTUBE_VIDEO_MAX_AGE_HOURS)

    for channel_name in YOUTUBE_CHANNEL_NAMES:
        channel_id = youtube_resolve_channel_id(channel_name)
        if not channel_id:
            continue

        uploads_playlist = youtube_get_uploads_playlist(channel_id)
        if not uploads_playlist:
            continue

        try:
            resp = requests.get(
                f"{YOUTUBE_API_BASE}/playlistItems",
                params={
                    "key": YOUTUBE_API_KEY,
                    "playlistId": uploads_playlist,
                    "part": "snippet",
                    "maxResults": YOUTUBE_MAX_VIDEOS_PER_CHANNEL,
                },
                timeout=15,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except Exception as exc:
            print(f"[warn] youtube: couldn't fetch videos for '{channel_name}': {exc}")
            continue

        for item in items:
            snippet = item.get("snippet", {})
            published_at = snippet.get("publishedAt", "")
            try:
                published_dt = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                published_dt = None

            if published_dt and published_dt < cutoff:
                continue  # skip anything older than the daily window

            video_id = snippet.get("resourceId", {}).get("videoId", "")
            if not video_id:
                continue

            rows.append({
                "job_url": f"https://www.youtube.com/watch?v={video_id}",
                "title": snippet.get("title", ""),
                "company": channel_name,
                "location": "India",
                "description": snippet.get("description", ""),
            })

        time.sleep(0.3)

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

# Fallback tier — my own self-hosted multi-provider AI gateway
# (github.com/rahulxgit/ai-gateway), used ONLY when Gemini's retries are
# exhausted (e.g. daily free-tier quota exhausted). The gateway itself
# already fails over across 7+ providers internally, so one call here is
# effectively backed by multiple providers already — no retry loop needed
# on this side. No auth required (open endpoint on Render).
AI_GATEWAY_URL = os.environ.get("AI_GATEWAY_URL") or "https://ai-gateway-wx35.onrender.com"


def _build_fit_prompt(title: str, company: str, description: str) -> str:
    return f"""Here is a candidate's background:

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


def _parse_json_verdict(raw_text: str) -> dict:
    text = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


def gateway_evaluate_job(title: str, company: str, description: str) -> dict:
    """
    Fallback evaluation via the self-hosted AI gateway. Returns None (not a
    verdict dict) if the gateway itself is unreachable or errors, so the
    caller can distinguish "gateway also failed" from "gateway said no".
    """
    prompt = _build_fit_prompt(title, company, description)
    try:
        resp = requests.post(
            f"{AI_GATEWAY_URL}/chat",
            headers={"Content-Type": "application/json"},
            json={"messages": [{"role": "user", "content": prompt}], "taskType": "reasoning"},
            timeout=45,  # the gateway may itself be failing over across providers internally
        )
        resp.raise_for_status()
        data = resp.json()
        return _parse_json_verdict(data.get("content", ""))
    except Exception as exc:
        print(f"[warn] AI gateway fallback also failed for '{title}' @ '{company}': {exc}")
        return None


def llm_evaluate_job(title: str, company: str, description: str) -> dict:
    """
    Returns {"fit_score": int 0-100, "is_fresher_appropriate": bool, "reason": str}
    Tries Gemini first (with retry-with-backoff on 429), and only falls
    back to the self-hosted AI gateway if Gemini's retries are fully
    exhausted or the call fails outright — so the gateway is a genuine
    last resort, not a first choice, keeping normal-day behavior unchanged.
    """
    prompt = _build_fit_prompt(title, company, description)
    max_retries = 3
    backoff_seconds = 15

    for attempt in range(max_retries + 1):
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
            if resp.status_code == 429:
                if attempt < max_retries:
                    wait = int(resp.headers.get("Retry-After", backoff_seconds * (attempt + 1)))
                    print(f"[warn] rate limited on '{title}' — retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    continue
                else:
                    print(f"[warn] '{title}' @ '{company}' still rate-limited after {max_retries} retries — "
                          f"falling back to AI gateway")
                    fallback = gateway_evaluate_job(title, company, description)
                    if fallback is not None:
                        return fallback
                    return {"fit_score": 0, "is_fresher_appropriate": False,
                             "reason": "all LLM providers failed — not evaluated"}

            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return _parse_json_verdict(text)
        except Exception as exc:
            print(f"[warn] Gemini evaluation failed for '{title}' @ '{company}': {exc} — falling back to AI gateway")
            fallback = gateway_evaluate_job(title, company, description)
            if fallback is not None:
                return fallback
            return {"fit_score": 0, "is_fresher_appropriate": False,
                     "reason": "all LLM providers failed — not evaluated"}

    return {"fit_score": 0, "is_fresher_appropriate": False,
             "reason": "all LLM providers failed — not evaluated"}


CONSECUTIVE_RATE_LIMIT_BREAKER = 5  # stop early after this many in a row fail with 429 even after retries


def llm_filter(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    results = []
    consecutive_rate_limits = 0
    evaluated_rows = []

    for idx, row in df.iterrows():
        verdict = llm_evaluate_job(
            str(row.get("title", "")),
            str(row.get("company", "")),
            str(row.get("description", "")),
        )
        results.append(verdict)
        evaluated_rows.append(idx)

        if verdict.get("reason") == "all LLM providers failed — not evaluated":
            consecutive_rate_limits += 1
        else:
            consecutive_rate_limits = 0

        if consecutive_rate_limits >= CONSECUTIVE_RATE_LIMIT_BREAKER:
            remaining = len(df) - len(evaluated_rows)
            print(f"[warn] {CONSECUTIVE_RATE_LIMIT_BREAKER} candidates in a row failed on BOTH Gemini and the "
                  f"AI gateway fallback — this is a strong signal something more fundamental is down (not "
                  f"just Gemini's quota, since the gateway itself already fails over across 7+ providers). "
                  f"Stopping here rather than burning the rest of the run's time budget. {remaining} "
                  f"candidates were left unevaluated and will be picked up automatically on the next run, "
                  f"since they were never logged.")
            break

        # Free-tier Gemini is rate-limited (~15 req/min on Flash-Lite) —
        # pace calls to stay comfortably under that instead of racing into 429s
        time.sleep(4.5)

    # Only score the rows we actually attempted — anything left unevaluated
    # after an early break stays out of the sheet entirely, so it's picked
    # up fresh next run instead of being wrongly marked as reviewed-and-rejected.
    df = df.loc[evaluated_rows].copy()
    df["fit_score"] = [r["fit_score"] for r in results]
    df["fresher_appropriate"] = [r["is_fresher_appropriate"] for r in results]
    df["reason"] = [r["reason"] for r in results]

    df = df[(df["fit_score"] >= LLM_FIT_THRESHOLD) & (df["fresher_appropriate"])].copy()
    df.sort_values("fit_score", ascending=False, inplace=True)
    return df


# ---------------------------------------------------------------------------
# Stage 3 — find a recruiter/company email for outreach, on the final
# shortlist only (small, already Gemini-approved, so cheap to enrich).
#
# Two tiers, both real — no fabricated emails ever:
#   1. Regex-extract an email already published directly in the JD text.
#      This is the most reliable signal: if a recruiter put their own email
#      in the posting, it's meant for exactly this purpose.
#   2. Optional fallback via Hunter.io (only if HUNTER_API_KEY is set): a
#      real domain-search lookup, hard-capped per run to protect the free
#      tier's monthly quota. Labeled "generic (Hunter)" in the sheet since
#      it's a company-level pattern match, not confirmation this is the
#      specific recruiter who posted this specific job.
# ---------------------------------------------------------------------------

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def extract_email_from_text(text: str) -> str:
    if not text:
        return ""
    match = EMAIL_REGEX.search(text)
    return match.group(0) if match else ""


def guess_company_domain(company_name: str) -> str:
    name = (company_name or "").lower().strip()
    for suffix in COMPANY_SUFFIXES_TO_STRIP:
        name = name.replace(suffix, "")
    name = re.sub(r"[^a-z0-9]", "", name)
    return f"{name}.com" if name else ""


def hunter_domain_search(domain: str) -> str:
    if not domain:
        return ""
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": 1},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        emails = data.get("data", {}).get("emails", [])
        if emails:
            return emails[0].get("value", "")
        # fall back to the generic pattern Hunter infers even with no confirmed emails
        pattern = data.get("data", {}).get("pattern", "")
        if pattern:
            return f"(pattern: {pattern}@{domain})"
    except Exception as exc:
        print(f"[warn] hunter.io lookup failed for '{domain}': {exc}")
    return ""


def enrich_with_emails(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        df["recruiter_email"] = []
        return df

    df = df.copy()
    emails = []
    hunter_calls_used = 0

    for _, row in df.iterrows():
        jd_email = extract_email_from_text(str(row.get("description", "")))
        if jd_email:
            emails.append(jd_email)
            continue

        if HUNTER_API_KEY and hunter_calls_used < HUNTER_MAX_CALLS_PER_RUN:
            domain = guess_company_domain(str(row.get("company", "")))
            found = hunter_domain_search(domain)
            hunter_calls_used += 1
            emails.append(f"{found} (generic, Hunter)" if found else "")
            time.sleep(0.5)
        else:
            emails.append("")

    df["recruiter_email"] = emails
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
            str(row.get("recruiter_email") or ""),
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


def build_email_body(df: pd.DataFrame, source_counts: dict = None) -> str:
    lines = []

    if source_counts:
        health_line = " | ".join(f"{name}: {count}" for name, count in source_counts.items())
        lines.append(f"Sources today — {health_line}\n")

    if df.empty:
        lines.append("No new matching listings today.")
        return "\n".join(lines)

    lines.append(f"{len(df)} new job(s) matched today (Gemini-reviewed):\n")
    for _, row in df.iterrows():
        email = row.get("recruiter_email") or ""
        email_line = f"  Contact: {email}\n" if email else ""
        lines.append(
            f"- {row.get('title')} @ {row.get('company')} ({row.get('location')}) "
            f"— fit {row.get('fit_score')}/100\n"
            f"  Why: {row.get('reason')}\n"
            f"{email_line}"
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

    print("Fetching company career pages (Greenhouse + Lever)...")
    greenhouse_df = fetch_greenhouse_listings()
    lever_df = fetch_lever_listings()
    print(f"  {len(greenhouse_df) + len(lever_df)} listings")

    print("Fetching YouTube job-alert channels (optional, key-gated)...")
    youtube_df = fetch_youtube_listings()
    print(f"  {len(youtube_df)} listings")

    source_counts = {
        "Indeed/LinkedIn/Google": len(jobspy_df),
        "Internshala": len(internshala_df),
        "Naukri": len(naukri_df),
        "Wellfound": len(wellfound_df),
        "LinkedIn posts": len(linkedin_posts_df),
        "Career pages": len(greenhouse_df) + len(lever_df),
        "YouTube": len(youtube_df),
    }

    raw_jobs = pd.concat(
        [jobspy_df, internshala_df, naukri_df, wellfound_df, linkedin_posts_df,
         greenhouse_df, lever_df, youtube_df],
        ignore_index=True,
    )
    raw_jobs.drop_duplicates(subset=["job_url"], inplace=True)
    print(f"Pulled {len(raw_jobs)} raw listings total")

    shortlist = prefilter(raw_jobs)
    print(f"{len(shortlist)} passed the keyword pre-filter (sent to Claude for review)")

    if shortlist.empty:
        print("Nothing to review — no matches today.")
        gmail = get_gmail_service()
        send_email(gmail, build_email_body(pd.DataFrame(), source_counts), 0)
        return

    sheet = get_sheet()
    seen = get_seen_urls(sheet)
    unseen_shortlist = shortlist[~shortlist["job_url"].isin(seen)]
    print(f"{len(unseen_shortlist)} of those are new (not already logged)")

    if unseen_shortlist.empty:
        print("Everything in the shortlist was already logged before — nothing new to review.")
        gmail = get_gmail_service()
        send_email(gmail, build_email_body(pd.DataFrame(), source_counts), 0)
        return

    reviewed = llm_filter(unseen_shortlist)
    print(f"{len(reviewed)} passed Gemini's fit review (score >= {LLM_FIT_THRESHOLD})")

    # Defensive re-check: re-read the sheet right before writing and drop
    # anything that landed there since we first checked (e.g. an overlapping
    # run). Cheap insurance against duplicate rows beyond the concurrency
    # guard in the workflow itself.
    reviewed = reviewed.drop_duplicates(subset=["job_url"])
    latest_seen = get_seen_urls(sheet)
    reviewed = reviewed[~reviewed["job_url"].isin(latest_seen)]

    print("Looking for recruiter/company emails on the final shortlist...")
    reviewed = enrich_with_emails(reviewed)
    found_count = (reviewed["recruiter_email"] != "").sum()
    print(f"  found an email for {found_count}/{len(reviewed)} jobs")

    log_new_jobs(sheet, reviewed)

    gmail = get_gmail_service()
    body = build_email_body(reviewed, source_counts)
    send_email(gmail, body, len(reviewed))
    print("Email sent.")


if __name__ == "__main__":
    main()

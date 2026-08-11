"""
All configuration in one place: env vars, search terms, keyword lists,
tunable constants. Nothing here does any work — pure data, so it's cheap
to read and safe to import from anywhere without side effects.
"""
import os

# --- jobspy (LinkedIn/Google) ------------------------------------------------
SEARCH_TERMS = [
    "SDE 1", "Software Development Engineer", "Software Engineer",
    "Full Stack Developer", "Full Stack Engineer", "Backend Developer",
    "MERN Stack Developer", "Frontend Developer", "Frontend Engineer",
    "React Developer", "Next.js Developer", "Java Developer",
    "Node.js Developer", "Web Developer", "Java Full Stack Developer",
    "Associate Software Engineer", "Graduate Software Engineer",
    "Junior Software Engineer", "Junior Full Stack Developer",
    "Entry Level Software Engineer", "Product Engineer", "Application Developer",
]
# Kept at 2 deliberately — jobspy runs one search per term x location combo.
# 22 terms x 2 locations = 44 combos already; widening locations scales fast.
# See sources/jobspy_common.py for the combo-count math.
LOCATIONS = ["Bengaluru, India", "India"]
JOBSPY_SITES = ["linkedin", "google"]  # indeed removed at user request; glassdoor/zip_recruiter removed earlier — confirmed 100% blocked from Actions
RESULTS_PER_SITE = 30
HOURS_OLD = 24
JOBSPY_CALL_TIMEOUT_SECONDS = 90

# --- Internshala -------------------------------------------------------------
INTERNSHALA_SEARCH_TERMS = [
    "full-stack-development", "software-development", "web-development",
    "react-js-development", "java-development", "node-js-development",
    # last three are plausible category slugs, unverified — check
    # internshala.com directly if they consistently return nothing
]

# --- Naukri --------------------------------------------------------------
NAUKRI_SEARCH_TERMS = [
    "sde 1", "software developer fresher", "full stack developer fresher",
    "react developer fresher", "java developer fresher", "node js developer fresher",
]

# --- Wellfound (best-effort) ------------------------------------------------
WELLFOUND_ROLE_SLUGS = ["software-engineer", "full-stack-engineer", "backend-engineer"]

# --- Company career pages (Greenhouse/Lever) --------------------------------
# Add a company once its board token is confirmed: visit
# job-boards.greenhouse.io/<token>/ or jobs.lever.co/<token> — if it loads,
# that's the token. Wrong/missing tokens just return 0, harmless.
# These two sources are the most reliable in the whole pipeline — real public
# APIs, no anti-bot, no rate limiting. Was previously just {"postman": "postman"}
# and {} — basically unconfigured. Expanded to companies that (a) are known to
# use Greenhouse/Lever and (b) actually hire freshers/SDE-1s. Tokens are
# best-effort; a wrong token just returns 0 for that company (harmless), so
# it's safe to add more over time — verify by visiting the board URL above.
GREENHOUSE_BOARDS = {
    "postman": "postman",
    "razorpay": "razorpay",
    "browserstack": "browserstack",
    "freshworks": "freshworks",
    "cred": "cred",
    "meesho": "meesho",
    "groww": "groww",
    "sprinklr": "sprinklr",
    "clearbit": "clearbit",
    "gitlab": "gitlab",
    "notion": "notion",
    "airbyte": "airbyte",
    "grafanalabs": "grafanalabs",
    "cockroachlabs": "cockroachlabs",
    "hashicorp": "hashicorp",
    "figma": "figma",
    "asana": "asana",
    "coinbase": "coinbase",
    "discord": "discord",
    "reddit": "reddit",
    "robinhood": "robinhood",
    "stripe": "stripe",
    "affirm": "affirm",
    "brex": "brex",
    "plaid": "plaid",
    "rippling": "rippling",
    "webflow": "webflow",
    "zapier": "zapier",
}
LEVER_BOARDS = {
    "sarvam": "sarvam",
    "zepto": "zepto",
    "urbancompany": "urbancompany",
    "spinny": "spinny",
    "khatabook": "khatabook",
    "cure.fit": "curefit",
    "netskope": "netskope",
    "highradius": "highradius",
    "clearfeed": "clearfeed",
    "leena-ai": "leenaai",
    "attentive": "attentive",
    "loom": "loom",
    "ramp": "ramp",
    "vanta": "vanta",
    "mixpanel": "mixpanel",
    "amplitude": "amplitude",
    "netlify": "netlify",
    "plaid": "plaid",
}

# --- Arbeitnow (free, public, no auth, no rate limit) -----------------------
# https://arbeitnow.com/api/job-board-api — mostly remote/EU-friendly roles,
# but genuinely open and unrestricted, so worth the coverage.
ARBEITNOW_KEYWORDS = [
    "react", "node", "full stack", "frontend", "backend", "javascript",
    "typescript", "software engineer", "junior", "graduate",
]

# --- RemoteOK (free, public, no auth, no rate limit) -------------------------
# https://remoteok.com/api — global remote listings, filtered client-side
# by tag/title since the API itself has no query params.
REMOTEOK_KEYWORDS = [
    "react", "node", "full stack", "frontend", "backend", "javascript",
    "typescript", "junior", "entry level", "software engineer",
]

# --- Firecrawl (web research/extraction — additive discovery source) ------
# Firecrawl's /v2/search endpoint (verified against Firecrawl's current API
# reference) returns search results with page content scraped in the same
# call, so a single request per query gives back both the URL and enough
# text to build a real JobListing.description without a second scrape
# round-trip. This is purely additive coverage on top of the dedicated
# Naukri/LinkedIn/Greenhouse/etc. sources, not a replacement.
#
# /v2/search has no cursor/offset pagination — limit is capped at 100 per
# call. Breadth comes from running many distinct queries
# (FIRECRAWL_MAX_QUERIES), not from paging one query.
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_ENABLED = os.environ.get("FIRECRAWL_ENABLED", "true").lower() != "false"
FIRECRAWL_MAX_RESULTS_PER_QUERY = min(int(os.environ.get("FIRECRAWL_MAX_RESULTS_PER_QUERY", "10")), 100)
FIRECRAWL_MAX_QUERIES = int(os.environ.get("FIRECRAWL_MAX_QUERIES", "20"))
FIRECRAWL_MAX_TOTAL_RESULTS = int(os.environ.get("FIRECRAWL_MAX_TOTAL_RESULTS", "150"))
FIRECRAWL_TIMEOUT = int(os.environ.get("FIRECRAWL_TIMEOUT", "30"))

FIRECRAWL_ROLE_TERMS = [
    "React Developer", "React.js Developer", "Frontend Developer",
    "Frontend Engineer", "Full Stack Developer", "Full Stack Engineer",
    "Software Developer", "Software Engineer", "MERN Developer",
    "Associate Software Engineer", "Graduate Software Engineer",
]
FIRECRAWL_LOCATIONS = ["Bangalore", "Pune", "India"]

# Built as one combined list at import time rather than nested loops
# scattered through the source module — easier to read, easier to trim.
# Capped by FIRECRAWL_MAX_QUERIES at call time, not here, so this list can
# stay expressive without needing to hand-count it.
FIRECRAWL_SEARCH_QUERIES = [
    f"{role} fresher {location}"
    for location in FIRECRAWL_LOCATIONS
    for role in FIRECRAWL_ROLE_TERMS
]

# Domains Firecrawl results are scored/ordered by, tier 1 first — used only
# to sort which queries' results get scraped first if a run is trimmed down
# by FIRECRAWL_MAX_TOTAL_RESULTS, not to exclude anything outright.
FIRECRAWL_PRIORITY_DOMAINS = [
    "naukri.com",  # tier 1
    "greenhouse.io", "lever.co", "myworkdayjobs.com",  # tier 2 — company career pages
    "linkedin.com",  # tier 3
    "indeed.com", "wellfound.com",  # tier 4
]

# --- YouTube ------------------------------------------------------------
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_URLS = [
    "https://www.youtube.com/@knacademy20",
    "https://www.youtube.com/@AnuSharma02",
    "https://www.youtube.com/@LokeshBagora",
    "https://www.youtube.com/@OnlineStudy4u",
    "https://www.youtube.com/@learningwithram1299",
    "https://www.youtube.com/@hiremeplz",
    "https://www.youtube.com/@ashishcode",
    "https://www.youtube.com/@Foundthejob",
    "https://www.youtube.com/@HireWithHarsh",
]
YOUTUBE_VIDEO_URLS = []  # one-off video links, not whole channels
YOUTUBE_MAX_VIDEOS_PER_CHANNEL = 3
YOUTUBE_VIDEO_MAX_AGE_HOURS = 48

# --- LinkedIn recruiter posts (optional, cookie-gated, higher risk) ---------
LINKEDIN_LI_AT_COOKIE = os.environ.get("LINKEDIN_LI_AT_COOKIE", "")
LINKEDIN_POST_SEARCH_TERMS = ["hiring software engineer fresher", "hiring sde 1", "hiring full stack developer"]

# --- Matching / scoring ---------------------------------------------------
PROFILE_KEYWORDS = [
    "react", "react.js", "reactjs", "next.js", "nextjs", "node", "node.js",
    "express", "express.js", "typescript", "javascript", "es6", "es2023",
    "mongodb", "postgresql", "prisma", "mysql", "supabase", "firebase",
    "rest api", "mern", "full stack", "fullstack", "ai agents",
    "rag", "llm", "mcp", "docker", "git", "github", "github actions",
    "ci/cd", "python", "java", "core java", "c++", "html", "css", "sql",
    "redux", "redux toolkit", "react hooks", "react router", "context api",
    "react query", "tanstack query", "spa", "component based architecture",
    "async await", "fetch api", "axios", "json", "crud", "mvc", "jwt",
    "authentication", "database design", "api development", "oop",
    "collections", "multithreading", "spring", "spring boot", "hibernate",
    "jdbc", "maven", "gradle", "tailwindcss", "responsive design",
    "framer motion", "postman", "vercel", "vs code", "data structures",
    "algorithms", "dsa", "operating systems", "dbms", "computer networks",
    "system design",
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
MAX_LLM_CANDIDATES = 60
LLM_FIT_THRESHOLD = 60
CONSECUTIVE_RATE_LIMIT_BREAKER = 5

# --- AI providers ----------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
AI_GATEWAY_URL = os.environ.get("AI_GATEWAY_URL") or "https://ai-gateway-wx35.onrender.com"

# --- Recruiter email enrichment ---------------------------------------------
HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")
HUNTER_MAX_CALLS_PER_RUN = 1  # ~25/month free tier ÷ ~30 daily runs
APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")
APOLLO_MAX_CALLS_PER_RUN = 1  # ~50/month free tier ÷ ~30 daily runs
APOLLO_TARGET_TITLES = ["Recruiter", "Talent Acquisition", "HR", "Hiring Manager", "Human Resources"]
COMPANY_SUFFIXES_TO_STRIP = [
    " pvt ltd", " pvt. ltd.", " private limited", " limited", " llp",
    " inc.", " inc", " llc", " technologies", " technology", " labs",
    " solutions", " services", " systems", " india", " co.", " ltd",
]

# --- Google Sheets / Gmail ---------------------------------------------------
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")
GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN = os.environ.get("GMAIL_REFRESH_TOKEN", "")

# --- Paths -----------------------------------------------------------------
PROFILE_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "profile-data.json")

_REQUIRED_FOR_REAL_RUN = [
    "GEMINI_API_KEY", "GOOGLE_SHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON",
    "GMAIL_TO", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN",
]


def validate():
    """Fails fast with a clear error listing exactly what's missing.
    Called explicitly by main.py at real startup — NOT at import time —
    so tests and other tooling can import config/models/pure-logic
    modules freely without every secret being set."""
    missing = [name for name in _REQUIRED_FOR_REAL_RUN if not globals().get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

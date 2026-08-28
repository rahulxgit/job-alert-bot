"""
All configuration in one place: env vars, search terms, keyword lists,
tunable constants. Nothing here does any work — pure data, so it's cheap
to read and safe to import from anywhere without side effects.
"""
import os

# --- Common Search Parameters ---
COMMON_SEARCH_TERMS = ["Software Engineer Walk in", "Developer Walk in", "IT Walk in", "Software Engineer Walk-in"]
COMMON_LOCATIONS = ["Pune"]

# --- jobspy (LinkedIn/Google) ---
SEARCH_TERMS = COMMON_SEARCH_TERMS
LOCATIONS = COMMON_LOCATIONS
JOBSPY_SITES = ["linkedin", "google"]
RESULTS_PER_SITE = int(os.environ.get("JOBSPY_RESULTS_PER_SITE", "15"))
HOURS_OLD = 24
JOBSPY_CALL_TIMEOUT_SECONDS = int(os.environ.get("JOBSPY_CALL_TIMEOUT_SECONDS", "60"))
JOBSPY_MAX_COMBINATIONS = int(os.environ.get("JOBSPY_MAX_COMBINATIONS", "24"))

INTERNSHALA_SEARCH_TERMS = COMMON_SEARCH_TERMS
NAUKRI_SEARCH_TERMS = COMMON_SEARCH_TERMS
WELLFOUND_ROLE_SLUGS = [term.lower().replace(' ', '-') for term in COMMON_SEARCH_TERMS]
GREENHOUSE_BOARDS = {
    "postman": "postman", "razorpay": "razorpay", "browserstack": "browserstack",
    "freshworks": "freshworks", "cred": "cred", "meesho": "meesho", "groww": "groww",
    "sprinklr": "sprinklr", "clearbit": "clearbit", "gitlab": "gitlab", "notion": "notion",
    "airbyte": "airbyte", "grafanalabs": "grafanalabs", "cockroachlabs": "cockroachlabs",
    "hashicorp": "hashicorp", "figma": "figma", "asana": "asana", "coinbase": "coinbase",
    "discord": "discord", "reddit": "reddit", "robinhood": "robinhood", "stripe": "stripe",
    "affirm": "affirm", "brex": "brex", "plaid": "plaid", "rippling": "rippling",
    "webflow": "webflow", "zapier": "zapier",
}
LEVER_BOARDS = {
    "sarvam": "sarvam", "zepto": "zepto", "urbancompany": "urbancompany", "spinny": "spinny",
    "khatabook": "khatabook", "cure.fit": "curefit", "netskope": "netskope",
    "highradius": "highradius", "clearfeed": "clearfeed", "leena-ai": "leenaai",
    "attentive": "attentive", "loom": "loom", "ramp": "ramp", "vanta": "vanta",
    "mixpanel": "mixpanel", "amplitude": "amplitude", "netlify": "netlify", "plaid": "plaid",
}
ARBEITNOW_KEYWORDS = COMMON_SEARCH_TERMS
REMOTEOK_KEYWORDS = COMMON_SEARCH_TERMS

# --- Firecrawl ---------------------------------------------------------------
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_ENABLED = os.environ.get("FIRECRAWL_ENABLED", "true").lower() != "false"
FIRECRAWL_MAX_RESULTS_PER_QUERY = min(int(os.environ.get("FIRECRAWL_MAX_RESULTS_PER_QUERY", "10")), 100)
FIRECRAWL_MAX_TOTAL_RESULTS = int(os.environ.get("FIRECRAWL_MAX_TOTAL_RESULTS", "150"))
FIRECRAWL_TIMEOUT = int(os.environ.get("FIRECRAWL_TIMEOUT", "30"))
FIRECRAWL_MAX_AGGREGATE_EXPANSIONS = int(os.environ.get("FIRECRAWL_MAX_AGGREGATE_EXPANSIONS", "10"))
FIRECRAWL_MAX_LINKS_PER_AGGREGATE = int(os.environ.get("FIRECRAWL_MAX_LINKS_PER_AGGREGATE", "5"))
FIRECRAWL_MAX_DETAIL_PAGES = int(os.environ.get("FIRECRAWL_MAX_DETAIL_PAGES", "50"))
FIRECRAWL_ROLE_TERMS = COMMON_SEARCH_TERMS
FIRECRAWL_LOCATIONS = COMMON_LOCATIONS
FIRECRAWL_EXPERIENCE_TERMS = ["fresher", "new grad", "graduate", "0-1 years", "0-2 years", "entry level", "junior", "associate", "early career"]
_role_location_combos = [(role, location) for location in FIRECRAWL_LOCATIONS for role in FIRECRAWL_ROLE_TERMS]
FIRECRAWL_TECH_COMBOS = ["React + Node", "React + TypeScript", "Next.js + Node", "MERN", "JavaScript + React", "TypeScript + React", "LLM + Python", "LLM + JavaScript", "AI + React", "AI + Node", "RAG", "MCP", "generative AI", "AI agents"]
_tech_location_combos = [(tech, location) for location in FIRECRAWL_LOCATIONS for tech in FIRECRAWL_TECH_COMBOS]
_TECH_LOCATION_QUERIES = [f"{tech} {FIRECRAWL_EXPERIENCE_TERMS[i % len(FIRECRAWL_EXPERIENCE_TERMS)]} {location}" for i, (tech, location) in enumerate(_tech_location_combos)]
_ROLE_LOCATION_QUERIES = [f"{role} {FIRECRAWL_EXPERIENCE_TERMS[i % len(FIRECRAWL_EXPERIENCE_TERMS)]} {location}" for i, (role, location) in enumerate(_role_location_combos)]
_SITE_TARGETED_QUERIES = [
    "software engineer fresher India site:naukri.com", "full stack developer fresher India site:linkedin.com/jobs",
    "software engineer entry level India site:boards.greenhouse.io", "frontend developer fresher India site:jobs.lever.co",
    "graduate software engineer India site:indeed.com", "AI engineer fresher India site:wellfound.com",
    "react developer fresher India site:internshala.com", "software developer entry level India site:glassdoor.co.in",
    "SDE 1 India site:cutshort.io", "software engineer 0-1 years India site:simplyhired.co.in",
]
FIRECRAWL_SEARCH_QUERIES = _ROLE_LOCATION_QUERIES + _TECH_LOCATION_QUERIES + _SITE_TARGETED_QUERIES
FIRECRAWL_MAX_QUERIES = int(os.environ.get("FIRECRAWL_MAX_QUERIES", str(len(FIRECRAWL_SEARCH_QUERIES))))
FIRECRAWL_PRIORITY_DOMAINS = ["naukri.com", "greenhouse.io", "lever.co", "myworkdayjobs.com", "linkedin.com", "indeed.com", "wellfound.com"]

# --- Crawl4AI ---------------------------------------------------------------
CRAWL_PROVIDER = os.environ.get("CRAWL_PROVIDER", "auto").lower()
CRAWL4AI_TIMEOUT = int(os.environ.get("CRAWL4AI_TIMEOUT", "30"))
CRAWL4AI_MAX_DETAIL_PAGES = int(os.environ.get("CRAWL4AI_MAX_DETAIL_PAGES", "25"))
CRAWL4AI_MIN_DESCRIPTION_CHARS = int(os.environ.get("CRAWL4AI_MIN_DESCRIPTION_CHARS", "300"))
CRAWL4AI_DISCOVERY_ENABLED = os.environ.get("CRAWL4AI_DISCOVERY_ENABLED", "true").lower() == "true"
CRAWL4AI_DISCOVERY_TIMEOUT = int(os.environ.get("CRAWL4AI_DISCOVERY_TIMEOUT", "30"))
CRAWL4AI_DISCOVERY_MAX_SEEDS = int(os.environ.get("CRAWL4AI_DISCOVERY_MAX_SEEDS", "20"))
CRAWL4AI_DISCOVERY_MAX_PAGES = int(os.environ.get("CRAWL4AI_DISCOVERY_MAX_PAGES", "100"))
CRAWL4AI_DISCOVERY_MAX_DEPTH = int(os.environ.get("CRAWL4AI_DISCOVERY_MAX_DEPTH", "2"))
CRAWL4AI_DISCOVERY_MAX_DETAIL_PAGES = int(os.environ.get("CRAWL4AI_DISCOVERY_MAX_DETAIL_PAGES", "1000"))
CRAWL4AI_DISCOVERY_MIN_DESCRIPTION_CHARS = int(os.environ.get("CRAWL4AI_DISCOVERY_MIN_DESCRIPTION_CHARS", "250"))
CRAWL4AI_DISCOVERY_MAX_DESCRIPTION_CHARS = int(os.environ.get("CRAWL4AI_DISCOVERY_MAX_DESCRIPTION_CHARS", "6000"))
CRAWL4AI_DISCOVERY_LOCATIONS = COMMON_LOCATIONS
CRAWL4AI_DISCOVERY_SEED_URLS = [
    "https://internshala.com/jobs/software-engineering-jobs/",
    "https://www.ycombinator.com/jobs/role/software-engineer",
    "https://wellfound.com/jobs",
    "https://in.indeed.com/jobs?q=Software+Engineer&l=India",
    "https://www.glassdoor.co.in/Job/india-software-engineer-jobs-SRCH_IL.0,5_IN115_KO6,23.htm",
    "https://www.simplyhired.co.in/search?q=Software+Engineer",
    "https://cutshort.io/jobs/software-engineer-jobs",
    "https://www.naukri.com/software-engineer-jobs-in-india",
    "https://www.foundit.in/srp/results?query=Software+Engineer",
    "https://www.hirist.tech/search/software-engineer",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs",
    "https://remoteok.com/remote-software-engineer-jobs",
    "https://arc.dev/remote-jobs/software-engineer",
    "https://www.instahyre.com/search-jobs/",
    "https://hasjob.co/",
    "https://hiringcafe.com/",
    "https://jobs.lever.co/",
    "https://boards.greenhouse.io/",
]
CRAWL4AI_DISCOVERY_ALLOWED_DOMAINS = [
    "internshala.com", "www.internshala.com", "ycombinator.com", "www.ycombinator.com",
    "wellfound.com", "www.wellfound.com", "in.indeed.com", "indeed.com", "www.indeed.com",
    "glassdoor.co.in", "www.glassdoor.co.in", "simplyhired.co.in", "www.simplyhired.co.in",
    "cutshort.io", "www.cutshort.io", "naukri.com", "www.naukri.com", "foundit.in", "www.foundit.in",
    "hirist.tech", "www.hirist.tech", "weworkremotely.com", "remoteok.com", "arc.dev",
    "instahyre.com", "www.instahyre.com", "hasjob.co", "hiringcafe.com", "www.hiringcafe.com",
    "boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com", "linkedin.com", "www.linkedin.com"
]
CRAWL4AI_DISCOVERY_SEED_CONCURRENCY = int(os.environ.get("CRAWL4AI_DISCOVERY_SEED_CONCURRENCY", "4"))
CRAWL4AI_DISCOVERY_HEALTHCHECK_ENABLED = os.environ.get("CRAWL4AI_DISCOVERY_HEALTHCHECK_ENABLED", "true").lower() == "true"
CRAWL4AI_DISCOVERY_HEALTHCHECK_URL = os.environ.get("CRAWL4AI_DISCOVERY_HEALTHCHECK_URL", "https://example.com/")

# --- Canonical master profile -----------------------------------------------
# Normalized to forward slashes so path checks/logging are stable across
# Windows dev machines and the Linux CI runner.
PROFILE_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "rahul-master-profile.json").replace("\\", "/")

# --- YouTube -----------------------------------------------------------------
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_URLS = [
    "https://www.youtube.com/@knacademy20", "https://www.youtube.com/@AnuSharma02", "https://www.youtube.com/@LokeshBagora",
    "https://www.youtube.com/@OnlineStudy4u", "https://www.youtube.com/@learningwithram1299", "https://www.youtube.com/@hiremeplz",
    "https://www.youtube.com/@ashishcode", "https://www.youtube.com/@Foundthejob", "https://www.youtube.com/@HireWithHarsh",
]
YOUTUBE_VIDEO_URLS = []
YOUTUBE_MAX_VIDEOS_PER_CHANNEL = 3
YOUTUBE_VIDEO_MAX_AGE_HOURS = 48

# --- LinkedIn recruiter posts ------------------------------------------------
LINKEDIN_LI_AT_COOKIE = os.environ.get("LINKEDIN_LI_AT_COOKIE", "")
LINKEDIN_POST_SEARCH_TERMS = COMMON_SEARCH_TERMS

# --- Matching / scoring -----------------------------------------------------
PROFILE_KEYWORDS = [
    "react", "react.js", "reactjs", "next.js", "nextjs", "node", "node.js", "express", "express.js",
    "typescript", "javascript", "es6", "es2023", "mongodb", "postgresql", "prisma", "mysql", "supabase",
    "firebase", "rest api", "mern", "full stack", "fullstack", "ai agents", "rag", "llm", "mcp",
    "docker", "git", "github", "github actions", "ci/cd", "python", "java", "core java", "c++", "html", "css",
    "sql", "redux", "redux toolkit", "react hooks", "react router", "context api", "react query", "tanstack query",
    "spa", "component based architecture", "async await", "fetch api", "axios", "json", "crud", "mvc", "jwt",
    "authentication", "database design", "api development", "oop", "collections", "multithreading", "spring",
    "spring boot", "hibernate", "jdbc", "maven", "gradle", "tailwindcss", "responsive design", "framer motion",
    "postman", "vercel", "vs code", "data structures", "algorithms", "dsa", "operating systems", "dbms",
    "computer networks", "system design",
]
FRESHER_SIGNALS = ["sde 1", "sde-1", "sde i", "software development engineer i", "fresher", "0-1 year", "0-2 year", "0 - 2 year", "0-2 yrs", "entry level", "entry-level", "graduate engineer", "graduate trainee", "junior", "campus hire", "new grad", "intern"]
SENIORITY_EXCLUSIONS = ["senior", "sr.", "sr ", "staff", "principal", "lead", "architect", "manager", "director", "head of", "vp ", "9-12 yr", "6-9 yr", "5-8 yr", "8+ year", "10+ year", "7+ year", "6+ year", "5+ year", "4+ year"]

MAX_LLM_CANDIDATES = int(os.environ.get("MAX_LLM_CANDIDATES", "300"))
LLM_FIT_THRESHOLD = 70
MIN_LIGHTWEIGHT_SCORE = int(os.environ.get("MIN_LIGHTWEIGHT_SCORE", "6"))
MIN_CANDIDATES_PER_SOURCE = int(os.environ.get("MIN_CANDIDATES_PER_SOURCE", "5"))
CONSECUTIVE_RATE_LIMIT_BREAKER = 5

ROLE_MATCH_TERMS = [
    "software engineer", "software development engineer", "software developer", "sde",
    "full stack developer", "full stack engineer", "fullstack developer", "frontend developer",
    "frontend engineer", "backend developer", "backend engineer", "mern developer",
    "mern stack developer", "react developer", "react.js developer", "node.js developer",
    "javascript developer", "typescript developer", "product engineer", "application developer",
    "associate software engineer", "graduate software engineer", "junior software engineer",
    "junior developer", "web developer", "developer walk", "it walk", "fresher walk"
]
CORE_TECH_TERMS = [
    "react", "react.js", "reactjs", "node", "node.js", "express", "express.js", "javascript",
    "typescript", "next.js", "nextjs", "mern", "mongodb", "rest api", "api development", "html",
    "css", "sql", "postgresql", "mysql", "supabase", "firebase", "redux", "react query", "tailwindcss",
    "docker", "git", "github",
]
PREFERRED_LOCATIONS = COMMON_LOCATIONS
NON_PREFERRED_LOCATION_SIGNALS = ["united states", "usa", "canada", "uk", "united kingdom", "australia", "germany", "france", "singapore", "dubai", "uae", "europe"]
EDUCATION_HARD_EXCLUSION_SIGNALS = [
    "b.tech in computer science only", "b.e. in computer science only", "b.e./b.tech in computer science only",
    "b.e./b.tech in cse only", "b.tech in cse only", "b.tech in information technology only",
    "b.e./b.tech in cs/it only", "computer science degree required", "computer science or information technology degree required",
    "only candidates with computer science",
]
EDUCATION_OPEN_SIGNALS = [
    "any engineering branch", "all engineering branches", "any branch", "any degree", "bachelor's degree",
    "bachelors degree", "engineering degree", "technology or engineering", "computer science or related field",
]
FRESHNESS_DAYS = int(os.environ.get("PREFILTER_FRESHNESS_DAYS", "30"))

# AI profile mode: condensed is the default to keep evaluation prompts small.
AI_PROFILE_MODE = os.environ.get("AI_PROFILE_MODE", "condensed")

LLM_EVALUATION_BUDGET_SECONDS = int(os.environ.get("LLM_EVALUATION_BUDGET_SECONDS", "86400"))

# --- AI provider resilience -------------------------------------------------
# The gateway is a self-hosted multi-provider failover chain (github.com/
# rahulxgit/ai-gateway) on Render's free tier: a cold provider can take
# 30-90s to wake up before the gateway's own internal failover even kicks
# in (see that repo's timeout-override.test.ts for a measured 61s NVIDIA
# NIM cold start). A 12s client-side timeout killed almost every request
# before the gateway had a chance to succeed, forcing a same-request
# fallback to Gemini on nearly every job and burning Gemini's tight quota.
AI_GATEWAY_TIMEOUT_SECONDS = int(os.environ.get("AI_GATEWAY_TIMEOUT_SECONDS", "75"))
AI_GATEWAY_MAX_RETRIES = int(os.environ.get("AI_GATEWAY_MAX_RETRIES", "1"))
AI_GATEWAY_RETRY_DELAY_SECONDS = float(os.environ.get("AI_GATEWAY_RETRY_DELAY_SECONDS", "3"))
# The gateway defaults to 1024 output tokens per request when no maxTokens
# is supplied (see OpenAICompatibleAdapter DEFAULT_MAX_TOKENS in that repo).
# Our fit-evaluation JSON (8 scores + decision + why[] + gaps[]) can exceed
# that, so the response gets cut off mid-JSON and fails to parse. Ask for
# more headroom explicitly.
AI_GATEWAY_MAX_TOKENS = int(os.environ.get("AI_GATEWAY_MAX_TOKENS", "2048"))
GEMINI_TIMEOUT_SECONDS = int(os.environ.get("GEMINI_TIMEOUT_SECONDS", "45"))
GEMINI_MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "1"))
GEMINI_MAX_RETRY_WAIT_SECONDS = int(os.environ.get("GEMINI_MAX_RETRY_WAIT_SECONDS", "10"))
GEMINI_QUOTA_COOLDOWN_SECONDS = int(os.environ.get("GEMINI_QUOTA_COOLDOWN_SECONDS", "3600"))
# Same truncation risk as the gateway — 512 tokens was too tight for the
# full structured verdict and was a major source of "did not contain a
# JSON object" failures even though responseMimeType=application/json was
# already set.
GEMINI_MAX_OUTPUT_TOKENS = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "1536"))

# --- AI throughput / observability ------------------------------------------
AI_MAX_CONCURRENCY = max(1, int(os.environ.get("AI_MAX_CONCURRENCY", "4")))
AI_METRICS_ENABLED = os.environ.get("AI_METRICS_ENABLED", "true").lower() == "true"

# --- AI provider backpressure ------------------------------------------------
GATEWAY_MAX_CONCURRENCY = max(1, int(os.environ.get("GATEWAY_MAX_CONCURRENCY", str(AI_MAX_CONCURRENCY))))
GEMINI_MAX_CONCURRENCY = max(1, int(os.environ.get("GEMINI_MAX_CONCURRENCY", "2")))
GEMINI_SHARED_BACKOFF_SECONDS = max(1.0, float(os.environ.get("GEMINI_SHARED_BACKOFF_SECONDS", "10")))
GATEWAY_SHARED_BACKOFF_SECONDS = max(0.0, float(os.environ.get("GATEWAY_SHARED_BACKOFF_SECONDS", "2")))

# --- AI providers ------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

GROQ_TIMEOUT_SECONDS = int(os.environ.get("GROQ_TIMEOUT_SECONDS", "30"))
GROQ_MAX_RETRIES = int(os.environ.get("GROQ_MAX_RETRIES", "1"))
GROQ_MAX_RETRY_WAIT_SECONDS = int(os.environ.get("GROQ_MAX_RETRY_WAIT_SECONDS", "5"))
GROQ_MAX_OUTPUT_TOKENS = int(os.environ.get("GROQ_MAX_OUTPUT_TOKENS", "1536"))
GROQ_SHARED_BACKOFF_SECONDS = max(1.0, float(os.environ.get("GROQ_SHARED_BACKOFF_SECONDS", "5")))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

AI_GATEWAY_SHARED_BACKOFF_SECONDS = max(1.0, float(os.environ.get("AI_GATEWAY_SHARED_BACKOFF_SECONDS", "30")))
AI_GATEWAY_URL = os.environ.get("AI_GATEWAY_URL") or "https://ai-gateway-wx35.onrender.com"

# --- Recruiter email enrichment ---------------------------------------------
HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")
HUNTER_MAX_CALLS_PER_RUN = 1
APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")
APOLLO_MAX_CALLS_PER_RUN = 1
APOLLO_TARGET_TITLES = ["Recruiter", "Talent Acquisition", "HR", "Hiring Manager", "Human Resources"]
COMPANY_SUFFIXES_TO_STRIP = [" pvt ltd", " pvt. ltd.", " private limited", " limited", " llp", " inc.", " inc", " llc", " technologies", " technology", " labs", " solutions", " services", " systems", " india", " co.", " ltd"]

# --- Google Sheets / Gmail ---------------------------------------------------
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")
GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN = os.environ.get("GMAIL_REFRESH_TOKEN", "")


def validate():
    missing = []
    if not GOOGLE_SHEET_ID:
        missing.append("GOOGLE_SHEET_ID")
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not GMAIL_TO:
        missing.append("ALERT_EMAIL_TO")
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
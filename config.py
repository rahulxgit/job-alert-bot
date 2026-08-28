"""
All configuration in one place: env vars, search terms, keyword lists,
tunable constants. Nothing here does any work — pure data, so it's cheap
to read and safe to import from anywhere without side effects.
"""
import os

# --- Common Search Parameters ---
COMMON_SEARCH_TERMS = [
    # Primary Role Family
    "software engineer", "software development engineer", "sde", "sde 1",
    "sde-1", "junior software engineer", "associate software engineer",
    "graduate software engineer", "software developer", "junior software developer",
    "entry level software engineer", "graduate engineer",
    # Full-Stack Family
    "full stack developer", "full-stack developer", "full stack engineer",
    "fullstack developer", "mern developer", "web developer",
    # Frontend Family
    "frontend developer", "front-end developer", "frontend engineer",
    "react developer", "react.js developer", "javascript developer", "typescript developer",
    # Backend Family
    "backend developer", "back-end developer", "backend engineer",
    "node.js developer", "api developer",
    # AI Family
    "ai engineer", "ai software engineer", "generative ai engineer"
]

COMMON_LOCATIONS = ["Pune", "Bengaluru", "Hyderabad", "Gurugram", "Remote", "India"]

# --- Walk-in Specific Configuration ---
WALKIN_SEARCH_TERMS = [
    "software engineer walk-in", "software developer walk-in", "sde walk-in",
    "sde 1 walk-in", "associate software engineer walk-in", "graduate software engineer walk-in",
    "junior software engineer walk-in", "full stack developer walk-in", "frontend developer walk-in",
    "backend developer walk-in", "react developer walk-in", "node.js developer walk-in",
    "software engineer hiring drive", "software developer hiring drive", "sde hiring drive",
    "fresher hiring drive", "off campus hiring drive", "walk-in interview software engineer",
    "offline hiring drive software engineer", "direct walk-in software developer"
]
WALKIN_LOCATIONS = [
    "Pune", "Hinjewadi Pune", "Kharadi Pune", "Hadapsar Pune", 
    "Viman Nagar Pune", "Baner Pune", "Wakad Pune", "Magarpatta Pune", "Kothrud Pune"
]
WALKIN_POSITIVE_SIGNALS = [
    "walk-in", "walk in", "walkin", "hiring drive", "walk-in drive",
    "offline hiring drive", "offline interview", "direct walk-in", "open interview",
    "mega walk-in", "immediate joiner"
]
WALKIN_NEGATIVE_SIGNALS = [
    "customer support", "voice process", "non-it operations", "bpo",
    "technical support", "service desk", "manual testing", "data entry"
]

PUNE_WALKIN_COMPANY_SEEDS = [
    "PletraTech", "Pratiti Technologies", "MultiGenesys", "Neilsoft",
    "AccioJob", "HummingBird Technologies", "VibrantMinds", "Infosys BPM"
]

# --- Environmental Toggles ---
HOURS_OLD = int(os.environ.get("HOURS_OLD", "168"))
WALKIN_MAX_AGE_DAYS = int(os.environ.get("WALKIN_MAX_AGE_DAYS", "30"))
WALKIN_PRIORITY_ENABLED = os.environ.get("WALKIN_PRIORITY_ENABLED", "true").lower() == "true"
PUNE_WALKIN_PRIORITY = os.environ.get("PUNE_WALKIN_PRIORITY", "true").lower() == "true"
FRESHER_ONLY_MODE = os.environ.get("FRESHER_ONLY_MODE", "false").lower() == "true"

# --- jobspy (LinkedIn/Google) ---
SEARCH_TERMS = COMMON_SEARCH_TERMS + WALKIN_SEARCH_TERMS
LOCATIONS = WALKIN_LOCATIONS + ["Bengaluru", "Hyderabad"]
JOBSPY_SITES = ["linkedin", "google"]
RESULTS_PER_SITE = int(os.environ.get("JOBSPY_RESULTS_PER_SITE", "15"))
JOBSPY_CALL_TIMEOUT_SECONDS = int(os.environ.get("JOBSPY_CALL_TIMEOUT_SECONDS", "60"))
JOBSPY_MAX_COMBINATIONS = int(os.environ.get("JOBSPY_MAX_COMBINATIONS", "24"))

INTERNSHALA_SEARCH_TERMS = COMMON_SEARCH_TERMS
NAUKRI_SEARCH_TERMS = COMMON_SEARCH_TERMS
WELLFOUND_ROLE_SLUGS = [term.lower().replace(' ', '-') for term in ["software engineer", "full stack developer", "react developer", "node developer", "ai engineer"]]

GREENHOUSE_BOARDS = {
    "postman": "postman", "groww": "groww", "gitlab": "gitlab", "grafanalabs": "grafanalabs", 
    "cockroachlabs": "cockroachlabs", "figma": "figma", "asana": "asana", "coinbase": "coinbase", 
    "discord": "discord", "reddit": "reddit", "robinhood": "robinhood", "stripe": "stripe", 
    "affirm": "affirm", "brex": "brex", "webflow": "webflow"
}

LEVER_BOARDS = {}

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

# Curated High-Priority Firecrawl Queries
_CURATED_QUERIES = [
    "Pune walk-in SDE",
    "Pune walk-in software engineer",
    "Pune walk-in software developer",
    "Pune walk-in full stack",
    "Pune walk-in React",
    "Pune walk-in Node.js",
    "Pune hiring drive fresher",
    "Pune offline hiring software engineer",
    "Pune SDE fresher",
    "Pune software engineer 0-1 years",
    "Pune software developer 0-2 years",
    "Pune associate software engineer Pune",
    "Pune graduate software engineer",
    "Pune junior software engineer"
]

FIRECRAWL_SEARCH_QUERIES = _CURATED_QUERIES + [f"{role} fresher {loc}" for role in ["Software Engineer", "React Developer", "AI Engineer"] for loc in ["Bengaluru", "Hyderabad", "Gurugram", "Remote"]]
FIRECRAWL_MAX_QUERIES = int(os.environ.get("FIRECRAWL_MAX_QUERIES", str(len(FIRECRAWL_SEARCH_QUERIES))))
FIRECRAWL_PRIORITY_DOMAINS = ["naukri.com", "linkedin.com", "indeed.com", "internshala.com", "wellfound.com", "cutshort.io", "instahyre.com", "hiringcafe.com"]

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
    "https://www.naukri.com/software-engineer-fresher-jobs-in-pune",
    "https://www.naukri.com/walkin-software-developer-jobs-in-pune",
    "https://in.indeed.com/jobs?q=Software+Engineer+Walk+In&l=Pune",
    "https://in.indeed.com/jobs?q=Fresher+Software+Engineer&l=Pune",
    "https://internshala.com/jobs/software-engineering-jobs-in-pune/",
    "https://wellfound.com/jobs",
    "https://cutshort.io/jobs/software-engineer-jobs-in-pune",
    "https://www.foundit.in/srp/results?query=Software+Engineer+Walk+in&locations=Pune",
    "https://www.hirist.tech/search/software-engineer-pune",
    "https://www.instahyre.com/search-jobs/",
    "https://hiringcafe.com/",
    "https://boards.greenhouse.io/",
    "https://jobs.ashbyhq.com/",
    "https://www.ycombinator.com/jobs/role/software-engineer"
]

CRAWL4AI_DISCOVERY_ALLOWED_DOMAINS = [
    "naukri.com", "www.naukri.com", "indeed.com", "in.indeed.com", "www.indeed.com",
    "internshala.com", "www.internshala.com", "wellfound.com", "www.wellfound.com",
    "cutshort.io", "www.cutshort.io", "foundit.in", "www.foundit.in",
    "hirist.tech", "www.hirist.tech", "instahyre.com", "www.instahyre.com",
    "hiringcafe.com", "www.hiringcafe.com", "boards.greenhouse.io", "jobs.ashbyhq.com",
    "ycombinator.com", "www.ycombinator.com", "linkedin.com", "www.linkedin.com"
]

CRAWL4AI_DISCOVERY_SEED_CONCURRENCY = int(os.environ.get("CRAWL4AI_DISCOVERY_SEED_CONCURRENCY", "4"))
CRAWL4AI_DISCOVERY_HEALTHCHECK_ENABLED = os.environ.get("CRAWL4AI_DISCOVERY_HEALTHCHECK_ENABLED", "true").lower() == "true"
CRAWL4AI_DISCOVERY_HEALTHCHECK_URL = os.environ.get("CRAWL4AI_DISCOVERY_HEALTHCHECK_URL", "https://example.com/")

# --- Canonical master profile -----------------------------------------------
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
    "JavaScript", "TypeScript", "React", "React.js", "Next.js", "Node.js", "Node",
    "Express", "Express.js", "MongoDB", "MongoDB Atlas", "PostgreSQL", "SQL", "SQLite",
    "REST API", "REST APIs", "API development", "MERN", "full stack", "frontend", "backend",
    "Redux", "Redux Toolkit", "Zustand", "React Query", "TanStack Query", "Tailwind CSS",
    "Firebase", "Supabase", "Git", "GitHub", "Docker", "Docker Compose", "Vercel", "Render",
    "MCP", "Model Context Protocol", "LLM", "LLM APIs", "AI Engineering", "AI agents",
    "AI infrastructure", "RAG", "generative AI", "OpenAI", "Anthropic", "Claude", "Gemini",
    "Groq", "OpenRouter", "DeepSeek", "Mistral", "SSE", "Server-Sent Events", "Jest", "testing",
    "system design", "data structures", "algorithms", "DSA", "OOP", "DBMS", "operating systems",
    "JWT", "authentication", "Cloudinary", "Multer", "bcrypt", "async processing", 
    "error classification", "failover", "provider routing", "token streaming"
]

FRESHER_SIGNALS = [
    "fresher", "freshers", "entry level", "entry-level", "0 year", "0 years", "0-1 year",
    "0–1 year", "0-2 years", "0–2 years", "0-1 yrs", "0-2 yrs", "new grad", "new graduate",
    "graduate", "graduate engineer", "graduate trainee", "software trainee", "GET",
    "junior", "associate", "campus hire", "campus recruitment", "2026 batch", "2025 batch",
    "recent graduate", "immediate joiner", "early career", "trainee engineer"
]

SENIORITY_EXCLUSIONS = [
    "senior", "sr.", "staff", "principal", "lead", "tech lead", "team lead", "architect",
    "manager", "director", "head", "vp", "5+ years", "6+ years", "7+ years", "8+ years", "10+ years"
]

MAX_LLM_CANDIDATES = int(os.environ.get("MAX_LLM_CANDIDATES", "300"))
LLM_FIT_THRESHOLD = 70
MIN_LIGHTWEIGHT_SCORE = int(os.environ.get("MIN_LIGHTWEIGHT_SCORE", "6"))
MIN_CANDIDATES_PER_SOURCE = int(os.environ.get("MIN_CANDIDATES_PER_SOURCE", "5"))
CONSECUTIVE_RATE_LIMIT_BREAKER = 5

ROLE_MATCH_TERMS = [
    "software engineer", "software development engineer", "software developer", "SDE",
    "SDE 1", "SDE-1", "SDE I", "software development engineer I", "junior software engineer",
    "associate software engineer", "graduate software engineer", "entry level software engineer",
    "entry-level software engineer", "junior software developer", "graduate software developer",
    "software engineer trainee", "graduate engineer trainee", "GET", "software development engineer trainee",
    "developer", "web developer", "full stack developer", "full-stack developer", "full stack engineer",
    "full-stack engineer", "fullstack developer", "fullstack engineer", "MERN developer",
    "MERN stack developer", "frontend developer", "front-end developer", "frontend engineer",
    "front-end engineer", "React developer", "React.js developer", "React engineer", "Next.js developer",
    "JavaScript developer", "TypeScript developer", "backend developer", "back-end developer",
    "backend engineer", "back-end engineer", "Node.js developer", "Node.js engineer", "API developer",
    "product engineer", "application developer", "AI engineer", "AI software engineer", "AI developer",
    "generative AI engineer", "LLM engineer", "AI application engineer"
]

CORE_TECH_TERMS = [
    "react", "react.js", "reactjs", "next.js", "nextjs", "typescript", "javascript", "node", "node.js",
    "express", "express.js", "mern", "mongodb", "mongodb atlas", "postgresql", "sql", "sqlite",
    "rest api", "rest apis", "api development", "redux", "redux toolkit", "zustand", "react query",
    "tanstack query", "tailwind css", "firebase", "supabase", "docker", "docker compose", "git", "github",
    "mcp", "model context protocol", "llm", "llm apis", "ai engineering", "ai agents", "rag", "generative ai",
    "python", "java"
]

PREFERRED_LOCATIONS = [
    "Pune", "Hinjewadi", "Kharadi", "Hadapsar", "Magarpatta", "Baner", "Wakad", "Viman Nagar", "Kothrud", "Pimpri-Chinchwad",
    "Bengaluru", "Hyderabad", "Gurugram", "Remote"
]
NON_PREFERRED_LOCATION_SIGNALS = ["united states", "usa", "canada", "uk", "united kingdom", "australia", "germany", "france", "singapore", "dubai", "uae", "europe"]

EDUCATION_OPEN_SIGNALS = [
    "any engineering branch", "all engineering branches", "any branch", "any degree", "bachelor's degree",
    "bachelors degree", "engineering degree", "technology or engineering", "computer science or related field",
    "b.tech", "b.e."
]
FRESHNESS_DAYS = int(os.environ.get("PREFILTER_FRESHNESS_DAYS", "30"))

# AI profile mode: condensed is the default to keep evaluation prompts small.
AI_PROFILE_MODE = os.environ.get("AI_PROFILE_MODE", "condensed")

LLM_EVALUATION_BUDGET_SECONDS = int(os.environ.get("LLM_EVALUATION_BUDGET_SECONDS", "86400"))

# --- AI provider resilience -------------------------------------------------
AI_GATEWAY_TIMEOUT_SECONDS = int(os.environ.get("AI_GATEWAY_TIMEOUT_SECONDS", "75"))
AI_GATEWAY_MAX_RETRIES = int(os.environ.get("AI_GATEWAY_MAX_RETRIES", "1"))
AI_GATEWAY_RETRY_DELAY_SECONDS = float(os.environ.get("AI_GATEWAY_RETRY_DELAY_SECONDS", "3"))
AI_GATEWAY_MAX_TOKENS = int(os.environ.get("AI_GATEWAY_MAX_TOKENS", "2048"))
GEMINI_TIMEOUT_SECONDS = int(os.environ.get("GEMINI_TIMEOUT_SECONDS", "45"))
GEMINI_MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "1"))
GEMINI_MAX_RETRY_WAIT_SECONDS = int(os.environ.get("GEMINI_MAX_RETRY_WAIT_SECONDS", "10"))
GEMINI_QUOTA_COOLDOWN_SECONDS = int(os.environ.get("GEMINI_QUOTA_COOLDOWN_SECONDS", "3600"))
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

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
LOCATIONS = ["Bengaluru, India", "India"]
JOBSPY_SITES = ["linkedin", "google"]
RESULTS_PER_SITE = int(os.environ.get("JOBSPY_RESULTS_PER_SITE", "15"))
HOURS_OLD = 24
JOBSPY_CALL_TIMEOUT_SECONDS = int(os.environ.get("JOBSPY_CALL_TIMEOUT_SECONDS", "60"))
JOBSPY_MAX_COMBINATIONS = int(os.environ.get("JOBSPY_MAX_COMBINATIONS", "24"))

INTERNSHALA_SEARCH_TERMS = [
    "full-stack-development", "software-development", "web-development",
    "react-js-development", "java-development", "node-js-development",
]
NAUKRI_SEARCH_TERMS = [
    "sde 1", "software developer fresher", "full stack developer fresher",
    "react developer fresher", "java developer fresher", "node js developer fresher",
]
WELLFOUND_ROLE_SLUGS = ["software-engineer", "full-stack-engineer", "backend-engineer"]
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
ARBEITNOW_KEYWORDS = ["react", "node", "full stack", "frontend", "backend", "javascript", "typescript", "software engineer", "junior", "graduate"]
REMOTEOK_KEYWORDS = ["react", "node", "full stack", "frontend", "backend", "javascript", "typescript", "junior", "entry level", "software engineer"]

# --- Firecrawl ---------------------------------------------------------------
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_ENABLED = os.environ.get("FIRECRAWL_ENABLED", "true").lower() != "false"
FIRECRAWL_MAX_RESULTS_PER_QUERY = min(int(os.environ.get("FIRECRAWL_MAX_RESULTS_PER_QUERY", "10")), 100)
FIRECRAWL_MAX_TOTAL_RESULTS = int(os.environ.get("FIRECRAWL_MAX_TOTAL_RESULTS", "150"))
FIRECRAWL_TIMEOUT = int(os.environ.get("FIRECRAWL_TIMEOUT", "30"))
FIRECRAWL_MAX_AGGREGATE_EXPANSIONS = int(os.environ.get("FIRECRAWL_MAX_AGGREGATE_EXPANSIONS", "10"))
FIRECRAWL_MAX_LINKS_PER_AGGREGATE = int(os.environ.get("FIRECRAWL_MAX_LINKS_PER_AGGREGATE", "5"))
FIRECRAWL_MAX_DETAIL_PAGES = int(os.environ.get("FIRECRAWL_MAX_DETAIL_PAGES", "50"))
FIRECRAWL_ROLE_TERMS = [
    "SDE", "SDE-1", "Software Engineer", "Software Developer", "Full Stack Engineer",
    "Full Stack Developer", "Frontend Engineer", "React Developer", "React.js Developer",
    "Next.js Developer", "Node.js Developer", "Backend Engineer", "Backend Developer",
    "AI Engineer", "AI/ML Engineer", "GenAI Engineer", "LLM Engineer", "Applied AI Engineer",
    "AI Software Engineer", "Product Engineer", "Associate Software Engineer",
    "Graduate Software Engineer", "Junior Software Engineer", "New Grad Engineer",
    "Graduate Engineer Trainee",
]
FIRECRAWL_LOCATIONS = ["Bengaluru", "Bangalore", "Pune", "Hyderabad", "Gurugram", "Gurgaon", "Noida", "Delhi NCR", "Mumbai", "Chennai", "Kolkata", "Ahmedabad", "Remote", "India"]
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
CRAWL4AI_DISCOVERY_ENABLED = os.environ.get("CRAWL4AI_DISCOVERY_ENABLED", "false").lower() == "true"
CRAWL4AI_DISCOVERY_TIMEOUT = int(os.environ.get("CRAWL4AI_DISCOVERY_TIMEOUT", "20"))
CRAWL4AI_DISCOVERY_MAX_SEEDS = int(os.environ.get("CRAWL4AI_DISCOVERY_MAX_SEEDS", "3"))
CRAWL4AI_DISCOVERY_MAX_PAGES = int(os.environ.get("CRAWL4AI_DISCOVERY_MAX_PAGES", "20"))
CRAWL4AI_DISCOVERY_MAX_DEPTH = int(os.environ.get("CRAWL4AI_DISCOVERY_MAX_DEPTH", "2"))
CRAWL4AI_DISCOVERY_MAX_DETAIL_PAGES = int(os.environ.get("CRAWL4AI_DISCOVERY_MAX_DETAIL_PAGES", "12"))
CRAWL4AI_DISCOVERY_MIN_DESCRIPTION_CHARS = int(os.environ.get("CRAWL4AI_DISCOVERY_MIN_DESCRIPTION_CHARS", "400"))
CRAWL4AI_DISCOVERY_MAX_DESCRIPTION_CHARS = int(os.environ.get("CRAWL4AI_DISCOVERY_MAX_DESCRIPTION_CHARS", "6000"))
CRAWL4AI_DISCOVERY_LOCATIONS = ["Bengaluru", "Bangalore", "Pune", "Hyderabad", "Gurugram", "Gurgaon", "Noida", "Delhi NCR", "Mumbai", "Chennai", "Kolkata", "Ahmedabad", "Remote", "India"]
CRAWL4AI_DISCOVERY_SEED_URLS = ["https://boards.greenhouse.io/", "https://jobs.lever.co/", "https://jobs.ashbyhq.com/"]
CRAWL4AI_DISCOVERY_ALLOWED_DOMAINS = ["boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com"]

# --- Canonical master profile -----------------------------------------------
# ONLY data/rahul-master-profile.json is used for candidate/job-match context.
PROFILE_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "rahul-master-profile.json")

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
LINKEDIN_POST_SEARCH_TERMS = ["hiring software engineer fresher", "hiring sde 1", "hiring full stack developer"]

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
PRIORITY_COMPANIES = ["razorpay", "sarvam", "groww", "meesho", "zepto", "cred", "swiggy", "zomato", "flipkart", "postman", "browserstack", "freshworks"]
MAX_LLM_CANDIDATES = int(os.environ.get("MAX_LLM_CANDIDATES", "100"))
LLM_FIT_THRESHOLD = 70
MIN_LIGHTWEIGHT_SCORE = 3
CONSECUTIVE_RATE_LIMIT_BREAKER = 5

# --- AI providers -----------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
AI_GATEWAY_URL = os.environ.get("AI_GATEWAY_URL") or "https://ai-gateway-wx35.onrender.com"
LLM_EVALUATION_BUDGET_SECONDS = int(os.environ.get("LLM_EVALUATION_BUDGET_SECONDS", "1200"))

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
_REQUIRED_FOR_REAL_RUN = ["GEMINI_API_KEY", "GOOGLE_SHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON", "GMAIL_TO", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"]


def validate():
    missing = [name for name in _REQUIRED_FOR_REAL_RUN if not globals().get(name)]
    if missing:
        raise RuntimeError(", ".join(missing))

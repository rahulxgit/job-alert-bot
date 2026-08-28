import re
from datetime import date, datetime
from dateutil import parser
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

WALKIN_DATE_CONTEXT_PATTERNS = [
    r"\bwalk[-\s]?in\b.{0,80}",
    r"\bwalk[-\s]?in interview\b.{0,80}",
    r"\bwalk[-\s]?in drive\b.{0,80}",
    r"\bhiring drive\b.{0,80}",
    r"\binterview date\b.{0,80}",
    r"\bdrive date\b.{0,80}",
    r"\bhiring date\b.{0,80}",
    r"\binterview\b.{0,50}",
    r"\bdrive\b.{0,50}",
    r"\bon\b\s+.*?walk[-\s]?in",
]

HISTORICAL_DATE_CONTEXT = [
    r"\bprevious\b",
    r"\blast\b",
    r"\bheld on\b",
    r"\bconducted on\b",
    r"\bpast\b",
    r"\bearlier\b",
    r"\bin 202[0-5]\b",
    r"\bwas held\b",
    r"\bhad been held\b",
    r"\bestablished\b",
    r"\bfounded\b",
    r"\bincorporated\b",
    r"\bexperience\b",
    r"\bgraduation\b",
    r"\bjoining date\b",
    r"\bdeadline\b"
]

DATE_PATTERN = re.compile(
    r"\b(?:"
    r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}"
    r"|"
    r"\d{1,2}[-/]\d{1,2}[-/]20\d{2}"
    r"|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+20\d{2}"
    r"|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+"
    r"\d{1,2}(?:st|nd|rd|th)?\s+20\d{2}"
    r")\b",
    re.IGNORECASE,
)

RANGE_PATTERN = re.compile(
    r"\b(\d{1,2}(?:st|nd|rd|th)?)\s*(?:-|to|and)\s*(\d{1,2}(?:st|nd|rd|th)?)\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+20\d{2})\b",
    re.IGNORECASE,
)

def _extract_walkin_date(text: str) -> tuple[date|None, date|None]:
    if not text:
        return None, None

    normalized = " ".join(text.split())
    candidates = []

    for match in RANGE_PATTERN.finditer(normalized):
        start, end = match.span()
        context_start = max(0, start - 120)
        context_end = min(len(normalized), end + 120)
        context = normalized[context_start:context_end].lower()

        if not any(re.search(p, context, re.IGNORECASE) for p in WALKIN_DATE_CONTEXT_PATTERNS):
            continue

        tight_context = normalized[max(0, start-40):min(len(normalized), end+40)].lower()
        if any(re.search(p, tight_context, re.IGNORECASE) for p in HISTORICAL_DATE_CONTEXT):
            continue
        
        try:
            day1_str = match.group(1)
            day2_str = match.group(2)
            month_year_str = match.group(3)
            day1_str = re.sub(r'(st|nd|rd|th)', '', day1_str, flags=re.IGNORECASE)
            day2_str = re.sub(r'(st|nd|rd|th)', '', day2_str, flags=re.IGNORECASE)
            d1 = parser.parse(f"{day1_str} {month_year_str}", fuzzy=True).date()
            d2 = parser.parse(f"{day2_str} {month_year_str}", fuzzy=True).date()
            candidates.append((d1, d2))
        except Exception:
            continue

    for match in DATE_PATTERN.finditer(normalized):
        start, end = match.span()
        context_start = max(0, start - 120)
        context_end = min(len(normalized), end + 120)
        context = normalized[context_start:context_end].lower()

        if not any(re.search(p, context, re.IGNORECASE) for p in WALKIN_DATE_CONTEXT_PATTERNS):
            continue
            
        tight_context = normalized[max(0, start-40):min(len(normalized), end+40)].lower()
        if any(re.search(p, tight_context, re.IGNORECASE) for p in HISTORICAL_DATE_CONTEXT):
            continue

        try:
            d = parser.parse(match.group(0), fuzzy=True).date()
            if any(r[0] <= d <= r[1] for r in candidates if r[1]):
                continue
            candidates.append((d, d))
        except Exception:
            continue

    if not candidates:
        return None, None

    today = datetime.now(IST).date()
    active_or_upcoming = [c for c in candidates if c[1] >= today]
    
    if active_or_upcoming:
        return min(active_or_upcoming, key=lambda x: x[0])
    
    return max(candidates, key=lambda x: x[1])

print(_extract_walkin_date("Our company was established on 10 March 2018. Walk-in interview: 30 August 2026."))
print(_extract_walkin_date("Company founded 10 March 2018. Walk-in interview details will be announced soon."))
print(_extract_walkin_date("Previous walk-in was held on 10 August 2026."))
print(_extract_walkin_date("Walk-in interview: 28-30 August 2026."))

import sys
import re

with open('ai/evaluator.py', 'r', encoding='utf-8') as f:
    text = f.read()

new_func = '''
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
from dateutil import parser
from datetime import date, datetime

IST = ZoneInfo("Asia/Kolkata")

WALKIN_DATE_CONTEXT_PATTERNS = [
    r"\\\\bwalk[-\\\\s]?in\\\\b",
    r"\\\\bwalk[-\\\\s]?in interview\\\\b",
    r"\\\\bwalk[-\\\\s]?in drive\\\\b",
    r"\\\\bhiring drive\\\\b",
    r"\\\\binterview date\\\\b",
    r"\\\\bdrive date\\\\b",
    r"\\\\bhiring date\\\\b",
    r"\\\\binterview\\\\b",
    r"\\\\bdrive\\\\b",
]

HISTORICAL_DATE_CONTEXT = [
    r"\\\\bprevious\\\\b",
    r"\\\\blast\\\\b",
    r"\\\\bheld on\\\\b",
    r"\\\\bconducted on\\\\b",
    r"\\\\bpast\\\\b",
    r"\\\\bearlier\\\\b",
    r"\\\\bwas held\\\\b",
    r"\\\\bhad been held\\\\b",
    r"\\\\bestablished\\\\b",
    r"\\\\bfounded\\\\b",
    r"\\\\bincorporated\\\\b",
    r"\\\\bexperience\\\\b",
    r"\\\\bgraduation\\\\b",
    r"\\\\bjoining date\\\\b",
    r"\\\\bdeadline\\\\b"
]

DATE_PATTERN = re.compile(
    r"\\\\b(?:"
    r"20\\\\d{2}[-/]\\\\d{1,2}[-/]\\\\d{1,2}"
    r"|"
    r"\\\\d{1,2}[-/]\\\\d{1,2}[-/]20\\\\d{2}"
    r"|"
    r"\\\\d{1,2}(?:st|nd|rd|th)?\\\\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\\\s+20\\\\d{2}"
    r"|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\\\s+"
    r"\\\\d{1,2}(?:st|nd|rd|th)?\\\\s+20\\\\d{2}"
    r")\\\\b",
    re.IGNORECASE,
)

RANGE_PATTERN = re.compile(
    r"\\\\b(\\\\d{1,2}(?:st|nd|rd|th)?)\\\\s*(?:-|to|and)\\\\s*(\\\\d{1,2}(?:st|nd|rd|th)?)\\\\s+((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\\\s+20\\\\d{2})\\\\b",
    re.IGNORECASE,
)

def _get_min_distance(patterns, text, match_center):
    import re
    min_dist = float('inf')
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            center = (m.start() + m.end()) / 2
            dist = abs(center - match_center)
            if dist < min_dist:
                min_dist = dist
    return min_dist

def _extract_walkin_date(text: str) -> tuple[date | None, date | None]:
    if not text:
        return None, None

    normalized = " ".join(text.split()).replace("–", "-").replace("—", "-")
    candidates = []
    
    import re
    from dateutil import parser
    from datetime import datetime

    def process_match(start, end, d1, d2):
        match_center = (start + end) / 2
        pos_dist = _get_min_distance(WALKIN_DATE_CONTEXT_PATTERNS, normalized, match_center)
        neg_dist = _get_min_distance(HISTORICAL_DATE_CONTEXT, normalized, match_center)
        if pos_dist > 150:
            return
        if neg_dist < pos_dist:
            return
        candidates.append((min(d1, d2), max(d1, d2)))

    for match in RANGE_PATTERN.finditer(normalized):
        try:
            day1_str = re.sub(r'(st|nd|rd|th)', '', match.group(1), flags=re.IGNORECASE)
            day2_str = re.sub(r'(st|nd|rd|th)', '', match.group(2), flags=re.IGNORECASE)
            month_year_str = match.group(3)
            d1 = parser.parse(f"{day1_str} {month_year_str}", fuzzy=True).date()
            d2 = parser.parse(f"{day2_str} {month_year_str}", fuzzy=True).date()
            process_match(match.start(), match.end(), d1, d2)
        except Exception:
            continue

    for match in DATE_PATTERN.finditer(normalized):
        try:
            d = parser.parse(match.group(0), fuzzy=True).date()
            if any(r[0] <= d <= r[1] for r in candidates if r[1]):
                continue
            process_match(match.start(), match.end(), d, d)
        except Exception:
            continue

    if not candidates:
        return None, None

    today = datetime.now(IST).date()
    active_or_upcoming = [c for c in candidates if c[1] >= today]
    
    if active_or_upcoming:
        return min(active_or_upcoming, key=lambda x: x[0])
    
    return max(candidates, key=lambda x: x[1])
'''

text = text.replace('def keyword_prefilter_score(listing: JobListing) -> int:', new_func.replace('\\\\', '\\') + '\ndef keyword_prefilter_score(listing: JobListing) -> int:')

prefilter_old = '''        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        date_pattern = r"\\b(?:20\\d{2}[-/]\\d{2}[-/]\\d{2}|\\d{1,2}[-/]\\d{1,2}[-/]20\\d{2}|\\d{1,2}(?:st|nd|rd|th)?\\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\s+20\\d{2})\\b"
        matches = re.findall(date_pattern, description)
        
        # If we find a date, we try to parse it (very roughly) just to see if it's expired
        for match_str in matches:
            try:
                from dateutil import parser
                parsed_date = parser.parse(match_str, fuzzy=True).date()
                if (today - parsed_date).days > 0:
                    # Found a date in the past, highly likely an expired walk-in
                    # Reject it immediately
                    return 0
            except Exception:
                pass'''

prefilter_new = '''        start_date, end_date = _extract_walkin_date(description)
        if end_date:
            today = datetime.now(IST).date()
            if end_date < today:
                return 0'''

text = text.replace(prefilter_old.replace('\\\\', '\\'), prefilter_new)

verdict_old = '''        if raw_date and re.search(r"(\d{4}-\d{2}-\d{2})", raw_date):
            match = re.search(r"(\d{4}-\d{2}-\d{2})", raw_date)
            try:
                wd = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
                age = (today - wd).days
                listing.walkin_date = match.group(1)
                
                if age > 0:
                    listing.verification_status = "expired"
                    # Expired walk-ins cannot be surfaced as high priority
                    # But the prompt specifically says:
                    # "past date -> expired -> reject from actionable results"
                    # Reject it immediately
                    listing.fit_score = 0
                    listing.fresher_appropriate = False
                    listing.reason = "Walk-in drive has expired."
                    listing.fit_tier = "Reject"
                    return False
                elif age == 0:
                    listing.verification_status = "active"
                else:
                    listing.verification_status = "upcoming"
            except ValueError:
                pass'''

verdict_new = '''        start_date, end_date = _extract_walkin_date(listing.description or "")
        valid_date = None
        if raw_date and re.search(r"(\d{4}-\d{2}-\d{2})", raw_date):
            match = re.search(r"(\d{4}-\d{2}-\d{2})", raw_date)
            try:
                wd = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                if not start_date and not end_date:
                    valid_date = wd
                elif start_date and end_date and start_date <= wd <= end_date:
                    valid_date = wd
                elif start_date and end_date:
                    valid_date = start_date
            except ValueError:
                pass
        elif start_date:
            valid_date = start_date

        if valid_date:
            today = datetime.now(IST).date()
            listing.walkin_date = valid_date.strftime("%Y-%m-%d")
            effective_end = end_date if end_date else valid_date
            effective_start = start_date if start_date else valid_date
            
            if (today - effective_end).days > 0:
                listing.verification_status = "expired"
                listing.fit_score = 0
                listing.fresher_appropriate = False
                listing.reason = "Walk-in drive has expired."
                listing.fit_tier = "Reject"
                return False
            elif (today - effective_start).days >= 0 and (today - effective_end).days <= 0:
                listing.verification_status = "active"
            else:
                listing.verification_status = "upcoming"'''

text = text.replace(verdict_old, verdict_new)

with open('ai/evaluator.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")

"""Shared data models used across the whole pipeline."""
from dataclasses import dataclass, field, asdict


def _normalize_text(value) -> str:
    """Normalize source-provided scalar/list values into safe text fields."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item).strip() for item in value if item is not None and str(item).strip())
    return str(value)


@dataclass
class JobListing:
    """One job/internship candidate, regardless of which source found it."""
    job_url: str
    title: str
    company: str = ""
    location: str = "India"
    description: str = ""
    source: str = "Unknown"

    # populated later in the pipeline
    prefilter_score: int = 0
    fit_score: int = 0
    fresher_appropriate: bool = False
    reason: str = ""
    recruiter_email: str = ""

    # optional metadata
    posting_date: str = ""
    employment_type: str = ""

    # structured matching dimensions
    role_match: int = 0
    experience_match: int = 0
    technical_match: int = 0
    project_match: int = 0
    education_match: int = 0
    location_match: int = 0
    company_quality: int = 0

    fit_tier: str = ""
    gaps: list[str] = field(default_factory=list)

    # Walk-in specifics
    is_walkin: bool = False
    walkin_date: str = ""
    walkin_end_date: str = ""
    reporting_time: str = ""
    venue: str = ""
    contact_person: str = ""
    registration_required: bool = False
    verification_status: str = ""

    def __post_init__(self) -> None:
        # External job sources occasionally return list-valued location/company
        # fields. Normalize at the model boundary so one malformed listing
        # cannot crash downstream scoring or AI prompt construction.
        self.job_url = _normalize_text(self.job_url).strip()
        self.title = _normalize_text(self.title).strip()
        self.company = _normalize_text(self.company).strip()
        self.location = _normalize_text(self.location).strip() or "India"
        self.description = _normalize_text(self.description)
        self.source = _normalize_text(self.source).strip() or "Unknown"
        self.posting_date = _normalize_text(self.posting_date).strip()
        self.employment_type = _normalize_text(self.employment_type).strip()
        self.reason = _normalize_text(self.reason)
        self.recruiter_email = _normalize_text(self.recruiter_email).strip()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FitVerdict:
    """Result of an AI provider judging one JobListing against the candidate profile."""
    fit_score: int = 0
    is_fresher_appropriate: bool = False
    reason: str = "evaluation failed"
    hit_rate_limit: bool = False

    # Structured scoring fields
    role_match: int = 0
    experience_match: int = 0
    technical_match: int = 0
    project_match: int = 0
    education_match: int = 0
    location_match: int = 0
    company_quality: int = 0

    # Walk-in extraction fields
    is_walkin: bool = False
    walkin_date: str = ""
    walkin_end_date: str = ""
    reporting_time: str = ""
    venue: str = ""
    contact_person: str = ""
    registration_required: bool = False
    verification_status: str = ""

    decision: str = ""
    why: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

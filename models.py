"""Shared data models used across the whole pipeline."""
from dataclasses import dataclass, field, asdict


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
    company_confidence: str = "unknown"
    freshness_confidence: str = "unknown"

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

    decision: str = ""
    why: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

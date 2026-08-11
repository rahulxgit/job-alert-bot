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

    # optional metadata — not every source can populate these, so both
    # default to "" and nothing downstream should assume they're set
    posting_date: str = ""
    employment_type: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FitVerdict:
    """Result of an AI provider judging one JobListing against the candidate profile."""
    fit_score: int = 0
    is_fresher_appropriate: bool = False
    reason: str = "evaluation failed"
    hit_rate_limit: bool = False  # signals the caller to adapt (skip retries on subsequent calls)

"""Common interface every source module implements. Each source is fully
independent — if one fails or times out, it returns an empty list rather
than raising, so the rest of the pipeline is unaffected."""
from abc import ABC, abstractmethod
from models import JobListing


class JobSource(ABC):
    name: str = "unknown"

    @abstractmethod
    def fetch_listings(self) -> list[JobListing]:
        """Must never raise — catch internally, log, return [] on failure."""
        ...

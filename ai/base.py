"""AI provider interface — any provider (Gemini, the gateway, a future
addition) implements evaluate() and returns a FitVerdict."""
from abc import ABC, abstractmethod
from models import FitVerdict


class AIProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def evaluate(self, prompt: str) -> FitVerdict:
        """Must never raise — catch internally, return a FitVerdict with
        hit_rate_limit or a failure reason set."""
        ...

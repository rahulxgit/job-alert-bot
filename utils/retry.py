"""Generic retry/backoff decorator for transient network failures."""
import time
import functools
from utils.logging_setup import get_logger

log = get_logger("retry")


def retry_on_exception(max_retries: int = 2, backoff_seconds: float = 2.0, exceptions=(Exception,)):
    """Retries a function on failure with linear backoff. Logs and re-raises
    (or returns None, caller's choice) after retries are exhausted — does
    NOT swallow errors silently, since callers need to know a source failed."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        wait = backoff_seconds * (attempt + 1)
                        log.warning(f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {exc} — retrying in {wait}s")
                        time.sleep(wait)
            log.warning(f"{func.__name__} failed after {max_retries + 1} attempts: {last_exc}")
            raise last_exc
        return wrapper
    return decorator

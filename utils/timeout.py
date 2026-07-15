"""
Hard per-call timeout via a daemon thread.

Confirmed necessary by a real incident: a single jobspy scrape call hung
silently for 21+ minutes (LinkedIn/Google stalling the connection instead
of failing cleanly) until GitHub's own job timeout killed the whole run.

Daemon thread specifically matters here — Python can't force-kill a thread
stuck on a blocking network call. A *non-daemon* thread left behind would
block the script's own process exit at the very end; a daemon thread gets
torn down automatically by the interpreter instead, so an abandoned call
can only ever cost `timeout_seconds`, never the whole run.
"""
import threading
from utils.logging_setup import get_logger

log = get_logger("timeout")


def run_with_timeout(func, args=(), kwargs=None, timeout_seconds=90, label=""):
    """Runs func(*args, **kwargs) with a hard timeout. Returns the result,
    or None if it timed out or raised — logs either case, never raises."""
    kwargs = kwargs or {}
    box = {}

    def _worker():
        try:
            box["result"] = func(*args, **kwargs)
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        log.warning(f"{label or func.__name__} TIMED OUT after {timeout_seconds}s — moving on rather than hanging the run")
        return None
    if "error" in box:
        log.warning(f"{label or func.__name__} failed: {box['error']}")
        return None
    return box.get("result")

"""
Shared jobspy plumbing used by linkedin.py and google.py — they
all go through one scrape_jobs() call per term/location combo (that's how
the jobspy library batches multiple sites in a single request), so rather
than triplicate the fetch loop, this module does the real work and the
three thin source modules just filter the result by site.
"""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from jobspy import scrape_jobs

import config
from models import JobListing
from utils.timeout import run_with_timeout
from utils.logging_setup import get_logger

log = get_logger("jobspy")

import threading
import hashlib
from concurrent.futures import Future

_cached_df = None
_fetch_lock = threading.Lock()
_fetch_future = None

def _get_google_query(term: str, location: str) -> str:
    forms = [
        f"{term} fresher jobs {location}",
        f"{term} 0-2 years {location}",
        f"{term} {location} fresher",
        f"{term} hiring {location}",
        f"{term} walk-in {location}",
    ]
    idx = int(hashlib.md5(f"{term}:{location}".encode()).hexdigest(), 16) % len(forms)
    return forms[idx]

def _scrape_one_combo(term: str, location: str):
    google_term = _get_google_query(term, location)
    return scrape_jobs(
        site_name=config.JOBSPY_SITES,
        search_term=term,
        google_search_term=google_term,
        location=location,
        results_wanted=config.RESULTS_PER_SITE,
        hours_old=config.HOURS_OLD,
        linkedin_fetch_description=True,
    )


def _run_combo(term: str, location: str):
    """Execute one bounded JobSpy call without changing its timeout semantics."""
    return run_with_timeout(
        _scrape_one_combo,
        args=(term, location),
        timeout_seconds=config.JOBSPY_CALL_TIMEOUT_SECONDS,
        label=f"jobspy '{term}' in '{location}'",
    )


def fetch_all_jobspy_listings() -> pd.DataFrame:
    """Fetch a bounded set of JobSpy term/location combinations once.

    The search breadth is intentionally unchanged: JOBSPY_MAX_COMBINATIONS
    still controls the exact number of combinations. Independent combinations
    are now executed with a small bounded worker pool so wall-clock time is
    reduced without reducing the number of searches or results requested.
    """
    global _cached_df, _fetch_future
    
    with _fetch_lock:
        if _cached_df is not None:
            return _cached_df
        if _fetch_future is None:
            _fetch_future = Future()
            first_thread = True
        else:
            first_thread = False

    if not first_thread:
        return _fetch_future.result()

    try:
        max_combinations = max(1, int(config.JOBSPY_MAX_COMBINATIONS))
        
        # Distribute combinations round-robin across locations to prevent starvation
        pools = [[(term, loc) for term in config.SEARCH_TERMS] for loc in config.LOCATIONS]
        combinations = []
        idx = 0
        while len(combinations) < max_combinations and any(pools):
            pool = pools[idx % len(pools)]
            if pool:
                combinations.append(pool.pop(0))
            idx += 1

        if not combinations:
            _cached_df = pd.DataFrame()
            _fetch_future.set_result(_cached_df)
            with _fetch_lock:
                _fetch_future = None
            return _cached_df

        configured_concurrency = int(os.environ.get("JOBSPY_MAX_CONCURRENCY", "4"))
        concurrency = max(1, min(len(combinations), configured_concurrency))
        log.info(
            "[JobSpy] Running %s bounded combinations with concurrency=%s (budget=%s)",
            len(combinations),
            concurrency,
            max_combinations,
        )

        all_results = []
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="jobspy") as executor:
            futures_map = {
                executor.submit(_run_combo, term, location): (term, location)
                for term, location in combinations
            }
            for future in as_completed(futures_map):
                term, location = futures_map[future]
                try:
                    df = future.result()
                except Exception as exc:
                    log.warning("[JobSpy] '%s' in '%s' failed: %s", term, location, exc)
                    continue
                if df is not None and not df.empty:
                    all_results.append(df)

        log.info(
            "[JobSpy] Completed %s bounded combinations (budget=%s)",
            len(combinations),
            max_combinations,
        )

        if not all_results:
            _cached_df = pd.DataFrame()
            _fetch_future.set_result(_cached_df)
            with _fetch_lock:
                _fetch_future = None
            return _cached_df

        combined = pd.concat(all_results, ignore_index=True)
        site_col = combined.get("site")
        if site_col is None:
            site_col = pd.Series("jobspy", index=combined.index)
        combined["source"] = site_col.fillna("jobspy").astype(str).str.capitalize()
        _cached_df = combined[["job_url", "title", "company", "location", "description", "source"]]
        _fetch_future.set_result(_cached_df)
        with _fetch_lock:
            _fetch_future = None
        return _cached_df
    except Exception as exc:
        _fetch_future.set_exception(exc)
        with _fetch_lock:
            _fetch_future = None
        raise


def dataframe_to_listings(df: pd.DataFrame, site_filter: str = None) -> list[JobListing]:
    if df.empty:
        return []
    if site_filter:
        df = df[df["source"].str.lower() == site_filter.lower()]
    return [
        JobListing(
            job_url=str(row.get("job_url") or ""),
            title=str(row.get("title") or ""),
            company=str(row.get("company") or ""),
            location=str(row.get("location") or "India"),
            description=str(row.get("description") or ""),
            source=str(row.get("source") or "Unknown"),
        )
        for _, row in df.iterrows() if row.get("job_url")
    ]

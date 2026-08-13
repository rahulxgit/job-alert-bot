"""
Shared jobspy plumbing used by linkedin.py and google.py — they
all go through one scrape_jobs() call per term/location combo (that's how
the jobspy library batches multiple sites in a single request), so rather
than triplicate the fetch loop, this module does the real work and the
three thin source modules just filter the result by site.
"""
import pandas as pd
from jobspy import scrape_jobs

import config
from models import JobListing
from utils.timeout import run_with_timeout
from utils.logging_setup import get_logger

log = get_logger("jobspy")

_cached_df = None


def _scrape_one_combo(term: str, location: str):
    return scrape_jobs(
        site_name=config.JOBSPY_SITES,
        search_term=term,
        google_search_term=f"{term} jobs near {location}",
        location=location,
        results_wanted=config.RESULTS_PER_SITE,
        hours_old=config.HOURS_OLD,
        linkedin_fetch_description=True,
    )


def fetch_all_jobspy_listings() -> pd.DataFrame:
    """Fetch a bounded set of JobSpy term/location combinations once.

    The old implementation expanded every search term against every location
    on every run. With 22 terms x 2 locations, one run could issue 44 JobSpy
    calls before downstream processing. JOBSPY_MAX_COMBINATIONS provides a
    hard execution budget while keeping the search terms/location order
    configurable. The result is still cached so LinkedIn and Google sources
    never trigger a second scrape in the same process.
    """
    global _cached_df
    if _cached_df is not None:
        return _cached_df

    all_results = []
    max_combinations = max(1, int(config.JOBSPY_MAX_COMBINATIONS))
    combinations_run = 0

    for term in config.SEARCH_TERMS:
        for location in config.LOCATIONS:
            if combinations_run >= max_combinations:
                log.info(
                    "[JobSpy] Combination budget reached: %s/%s; stopping cleanly",
                    combinations_run,
                    max_combinations,
                )
                break

            combinations_run += 1
            df = run_with_timeout(
                _scrape_one_combo,
                args=(term, location),
                timeout_seconds=config.JOBSPY_CALL_TIMEOUT_SECONDS,
                label=f"jobspy '{term}' in '{location}'",
            )
            if df is not None and not df.empty:
                all_results.append(df)
        if combinations_run >= max_combinations:
            break

    log.info(
        "[JobSpy] Completed %s bounded combinations (budget=%s)",
        combinations_run,
        max_combinations,
    )

    if not all_results:
        _cached_df = pd.DataFrame()
        return _cached_df

    combined = pd.concat(all_results, ignore_index=True)
    combined["source"] = combined.get("site", "jobspy").astype(str).str.capitalize()
    _cached_df = combined[["job_url", "title", "company", "location", "description", "source"]]
    return _cached_df


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

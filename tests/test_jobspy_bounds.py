"""Tests for the bounded JobSpy execution budget."""
from unittest.mock import patch

import config
import sources.jobspy_common as jobspy_common


def test_jobspy_stops_at_combination_budget():
    calls = []

    def fake_scrape(term, location):
        calls.append((term, location))
        return None

    old_cache = jobspy_common._cached_df
    old_limit = config.JOBSPY_MAX_COMBINATIONS
    try:
        jobspy_common._cached_df = None
        config.JOBSPY_MAX_COMBINATIONS = 3
        with patch.object(jobspy_common, "_scrape_one_combo", side_effect=fake_scrape):
            result = jobspy_common.fetch_all_jobspy_listings()
        assert result.empty
        assert len(calls) == 3
    finally:
        jobspy_common._cached_df = old_cache
        config.JOBSPY_MAX_COMBINATIONS = old_limit


def test_jobspy_result_is_cached_between_sources():
    old_cache = jobspy_common._cached_df
    try:
        sentinel = object()
        jobspy_common._cached_df = sentinel
        assert jobspy_common.fetch_all_jobspy_listings() is sentinel
    finally:
        jobspy_common._cached_df = old_cache

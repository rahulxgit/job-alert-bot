import threading
import time
from unittest.mock import patch

import config
import sources.jobspy_common as jobspy_common


def test_jobspy_runs_bounded_combinations_concurrently(monkeypatch):
    old_cache = jobspy_common._cached_df
    old_future = jobspy_common._fetch_future
    monkeypatch.setattr(config, "JOBSPY_MAX_COMBINATIONS", 4)
    monkeypatch.setenv("JOBSPY_MAX_CONCURRENCY", "4")

    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_run(term, location):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return None

    try:
        jobspy_common._cached_df = None
        jobspy_common._fetch_future = None
        with patch.object(jobspy_common, "_run_combo", side_effect=fake_run):
            result = jobspy_common.fetch_all_jobspy_listings()
        assert result.empty
        assert max_active > 1
    finally:
        jobspy_common._cached_df = old_cache
        jobspy_common._fetch_future = old_future

import threading
import time
import pandas as pd
import pytest
from unittest.mock import patch
import sources.jobspy_common as jobspy_common

def test_jobspy_future_lifecycle_success_cache():
    # Clear state
    jobspy_common._cached_df = None
    jobspy_common._fetch_future = None

    df_result = pd.DataFrame({
        "job_url": ["http://test.com/1"],
        "title": ["Engineer"],
        "company": ["Corp"],
        "location": ["Pune"],
        "description": ["Desc"],
        "site": ["linkedin"]
    })

    call_count = 0
    def fake_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return df_result

    with patch.object(jobspy_common, "_run_combo", side_effect=fake_run):
        res1 = jobspy_common.fetch_all_jobspy_listings()
        assert not res1.empty
        assert call_count > 0
        
        initial_calls = call_count
        
        res2 = jobspy_common.fetch_all_jobspy_listings()
        assert len(res1) == len(res2)
        assert call_count == initial_calls
        
        assert jobspy_common._fetch_future is None

def test_jobspy_future_lifecycle_failure_retry():
    # Clear state
    jobspy_common._cached_df = None
    jobspy_common._fetch_future = None

    def fake_run(*args, **kwargs):
        return pd.DataFrame({
            "job_url": ["http://test.com/1"],
            "title": ["Engineer"],
            "company": ["Corp"],
            "location": ["Pune"],
            "description": ["Desc"],
            "site": ["linkedin"]
        })

    with patch.object(jobspy_common, "_run_combo", side_effect=fake_run):
        with patch("pandas.concat", side_effect=ValueError("Concat Error")):
            with pytest.raises(ValueError, match="Concat Error"):
                jobspy_common.fetch_all_jobspy_listings()
        
            assert jobspy_common._fetch_future is None
            
            with pytest.raises(ValueError, match="Concat Error"):
                jobspy_common.fetch_all_jobspy_listings()

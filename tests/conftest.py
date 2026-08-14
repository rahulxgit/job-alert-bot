import pytest
from unittest.mock import patch


@pytest.fixture
def mock_post():
    """Shared Firecrawl POST mock for tests that request it by fixture name."""
    with patch("sources.firecrawl.requests.post") as mocked:
        yield mocked

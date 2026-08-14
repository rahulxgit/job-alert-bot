from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import sources.crawl4ai_discovery as discovery


def test_healthcheck_validates_real_crawl_result(monkeypatch):
    monkeypatch.setattr(discovery.config, "CRAWL4AI_DISCOVERY_HEALTHCHECK_URL", "https://example.com/")
    result = SimpleNamespace(success=True, markdown="# Example Domain\n" + "x" * 100, error_message="")

    class FakeCrawler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        arun = AsyncMock(return_value=result)

    with patch.object(discovery, "AsyncWebCrawler", return_value=FakeCrawler()) as crawler_cls:
        assert discovery.run_healthcheck() == "https://example.com/"
        crawler_cls.assert_called_once()


def test_healthcheck_rejects_empty_markdown():
    result = SimpleNamespace(success=True, markdown="", error_message="")

    class FakeCrawler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        arun = AsyncMock(return_value=result)

    with patch.object(discovery, "AsyncWebCrawler", return_value=FakeCrawler()):
        try:
            discovery.run_healthcheck()
        except RuntimeError as exc:
            assert "insufficient markdown" in str(exc)
        else:
            raise AssertionError("empty health-check content was accepted")

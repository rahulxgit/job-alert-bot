from models import JobListing
from sources import crawl4ai


def test_batch_crawler_reuses_single_browser(monkeypatch):
    class FakeCrawler:
        enter_count = 0
        exit_count = 0

        async def __aenter__(self):
            FakeCrawler.enter_count += 1
            return self

        async def __aexit__(self, exc_type, exc, tb):
            FakeCrawler.exit_count += 1

        async def arun(self, *, url, config):
            class Result:
                success = True
                error_message = ""
                markdown = f"content for {url}"

            return Result()

    monkeypatch.setattr(crawl4ai, "AsyncWebCrawler", lambda **kwargs: FakeCrawler())
    rows = crawl4ai.crawl_urls(["https://example.com/1", "https://example.com/2"])

    assert len(rows) == 2
    assert FakeCrawler.enter_count == 1
    assert FakeCrawler.exit_count == 1
    assert all(isinstance(row, JobListing) for row in rows)


def test_batch_crawler_isolates_failed_url(monkeypatch):
    class FakeCrawler:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def arun(self, *, url, config):
            if url.endswith("/bad"):
                raise RuntimeError("boom")

            class Result:
                success = True
                error_message = ""
                markdown = "good job description"

            return Result()

    monkeypatch.setattr(crawl4ai, "AsyncWebCrawler", lambda **kwargs: FakeCrawler())
    rows = crawl4ai.crawl_urls(["https://example.com/good", "https://example.com/bad"])

    assert [row.job_url for row in rows] == ["https://example.com/good"]

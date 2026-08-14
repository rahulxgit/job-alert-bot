from ai.evaluator import keyword_prefilter_score
from models import JobListing


def test_list_valued_location_is_normalized_before_prefilter():
    listing = JobListing(
        job_url="https://example.com/jobs/1",
        title="Software Engineer",
        company="Example Co",
        location=["Bengaluru", "Remote"],
        description="React Node.js MongoDB fresher entry level",
        source="Test",
    )

    assert listing.location == "Bengaluru, Remote"
    assert isinstance(keyword_prefilter_score(listing), int)

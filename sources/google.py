from models import JobListing
from sources.base import JobSource
from sources.jobspy_common import fetch_all_jobspy_listings, dataframe_to_listings


class GoogleJobsSource(JobSource):
    name = "Google"

    def fetch_listings(self) -> list[JobListing]:
        return dataframe_to_listings(fetch_all_jobspy_listings(), site_filter="google")

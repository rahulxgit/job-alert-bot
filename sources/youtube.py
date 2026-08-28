"""
YouTube job-alert channels — official Data API, no scraping, key-gated.
Channel resolution is URL-based and deterministic: /channel/ and /@handle
links resolve exactly (cheap, 1 API unit), no fuzzy name-matching risk.
Each video's description is parsed for individual job/apply links — every
real link found becomes its own candidate, not the whole video as one lump.
Falls back to treating the video itself as one candidate if no links parse.
"""
import re
import time
from datetime import datetime, timedelta
import requests

import config
from models import JobListing
from sources.base import JobSource, NotConfiguredError
from utils.text import extract_job_links_from_description
from utils.logging_setup import get_logger

log = get_logger("youtube")

API_BASE = "https://www.googleapis.com/youtube/v3"


def _resolve_channel_id(channel_url: str) -> str:
    channel_url = channel_url.strip().rstrip("/")

    m = re.search(r"/channel/([A-Za-z0-9_-]+)", channel_url)
    if m:
        return m.group(1)

    m = re.search(r"/@([A-Za-z0-9_.-]+)", channel_url)
    if m:
        handle = m.group(1)
        try:
            resp = requests.get(f"{API_BASE}/channels", params={"key": config.YOUTUBE_API_KEY, "forHandle": handle, "part": "id"}, timeout=15)
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if items:
                return items[0]["id"]
            log.warning(f"no channel found for handle '@{handle}'")
        except Exception as exc:
            log.warning(f"couldn't resolve handle '@{handle}': {exc}")
        return ""

    m = re.search(r"/(?:c|user)/([A-Za-z0-9_.-]+)", channel_url)
    if m:
        try:
            resp = requests.get(f"{API_BASE}/search", params={"key": config.YOUTUBE_API_KEY, "q": m.group(1), "type": "channel", "part": "snippet", "maxResults": 1}, timeout=15)
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if items:
                return items[0]["snippet"]["channelId"]
        except Exception as exc:
            log.warning(f"couldn't resolve legacy URL '{channel_url}': {exc}")
        return ""

    log.warning(f"couldn't parse channel URL format: '{channel_url}'")
    return ""


def _channel_info(channel_id: str) -> tuple:
    try:
        resp = requests.get(f"{API_BASE}/channels", params={"key": config.YOUTUBE_API_KEY, "id": channel_id, "part": "contentDetails,snippet"}, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if items:
            return items[0]["contentDetails"]["relatedPlaylists"]["uploads"], items[0]["snippet"].get("title", "")
    except Exception as exc:
        log.warning(f"couldn't get channel info for '{channel_id}': {exc}")
    return "", ""


def _rows_from_video(video_url: str, video_title: str, channel_label: str, description: str) -> list[JobListing]:
    job_links = extract_job_links_from_description(description, video_title)
    if not job_links:
        return [JobListing(job_url=video_url, title=video_title, company=channel_label, location="India", description=description, source="YouTube")]
    return [
        JobListing(
            job_url=job_url, title=title_guess, company=channel_label, location="India",
            description=f"{title_guess}\n\n(From YouTube video: {video_title})\n\n{description[:2000]}",
            source="YouTube",
        )
        for job_url, title_guess in job_links
    ]


class YouTubeSource(JobSource):
    name = "YouTube"

    def fetch_listings(self) -> list[JobListing]:
        if not config.YOUTUBE_API_KEY:
            raise NotConfiguredError("YOUTUBE_API_KEY not set")

        rows = []
        rows.extend(self._fetch_channels())
        rows.extend(self._fetch_direct_videos())
        return rows

    def _fetch_channels(self) -> list[JobListing]:
        if not config.YOUTUBE_CHANNEL_URLS:
            return []
        rows = []
        cutoff = datetime.utcnow() - timedelta(hours=config.YOUTUBE_VIDEO_MAX_AGE_HOURS)

        for channel_url in config.YOUTUBE_CHANNEL_URLS:
            channel_id = _resolve_channel_id(channel_url)
            if not channel_id:
                continue
            uploads_playlist, channel_title = _channel_info(channel_id)
            if not uploads_playlist:
                continue
            try:
                resp = requests.get(f"{API_BASE}/playlistItems", params={"key": config.YOUTUBE_API_KEY, "playlistId": uploads_playlist, "part": "snippet", "maxResults": config.YOUTUBE_MAX_VIDEOS_PER_CHANNEL}, timeout=15)
                resp.raise_for_status()
                items = resp.json().get("items", [])
            except Exception as exc:
                log.warning(f"couldn't fetch videos for '{channel_url}': {exc}")
                continue

            for item in items:
                snippet = item.get("snippet", {})
                try:
                    published_dt = datetime.strptime(snippet.get("publishedAt", ""), "%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    published_dt = None
                if published_dt and published_dt < cutoff:
                    continue
                video_id = snippet.get("resourceId", {}).get("videoId", "")
                if not video_id:
                    continue
                rows.extend(_rows_from_video(
                    f"https://www.youtube.com/watch?v={video_id}", snippet.get("title", ""),
                    channel_title or channel_url, snippet.get("description", ""),
                ))
            time.sleep(0.3)
        return rows

    def _fetch_direct_videos(self) -> list[JobListing]:
        if not config.YOUTUBE_VIDEO_URLS:
            return []
        rows = []
        for video_url in config.YOUTUBE_VIDEO_URLS:
            m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", video_url) or re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", video_url)
            if not m:
                log.warning(f"couldn't parse video ID from '{video_url}'")
                continue
            video_id = m.group(1)
            try:
                resp = requests.get(f"{API_BASE}/videos", params={"key": config.YOUTUBE_API_KEY, "id": video_id, "part": "snippet"}, timeout=15)
                resp.raise_for_status()
                items = resp.json().get("items", [])
            except Exception as exc:
                log.warning(f"couldn't fetch video '{video_url}': {exc}")
                continue
            if not items:
                log.warning(f"video '{video_url}' not found (deleted, private, or bad ID)")
                continue
            snippet = items[0].get("snippet", {})
            rows.extend(_rows_from_video(
                f"https://www.youtube.com/watch?v={video_id}", snippet.get("title", ""),
                snippet.get("channelTitle", "") or video_url, snippet.get("description", ""),
            ))
            time.sleep(0.2)
        return rows

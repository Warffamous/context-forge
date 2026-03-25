"""Parser for YouTube data from Google Takeout exports.

Handles:
- Watch history (HTML and JSON formats)
- Liked videos (JSON)
- Subscriptions (JSON/CSV)
"""

import csv
import json
import os
import re
from datetime import datetime
from html.parser import HTMLParser


class WatchHistoryHTMLParser(HTMLParser):
    """Parse YouTube watch-history.html from Google Takeout."""

    def __init__(self):
        super().__init__()
        self.entries = []
        self._current = {}
        self._in_content = False
        self._in_link = False
        self._depth = 0
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "div" and attrs_dict.get("class") == "outer-cell mdl-cell mdl-cell--12-col mdl-shadow--2dp":
            self._current = {}
            self._depth = 0
        if tag == "div" and "content-cell" in attrs_dict.get("class", ""):
            self._in_content = True
            self._text_parts = []
        if tag == "a" and self._in_content:
            href = attrs_dict.get("href", "")
            if "youtube.com/watch" in href or "youtu.be/" in href:
                self._current["url"] = href
                video_id = extract_video_id(href)
                if video_id:
                    self._current["video_id"] = video_id
            elif "youtube.com/channel" in href or "youtube.com/@" in href:
                self._current["channel_url"] = href
            self._in_link = True

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            self._in_link = False
        if tag == "div" and self._in_content:
            self._in_content = False
            text = " ".join(self._text_parts).strip()
            # Try to extract timestamp from the text
            ts = _extract_timestamp(text)
            if ts:
                self._current["timestamp"] = ts
            if self._current.get("url"):
                self.entries.append(dict(self._current))

    def handle_data(self, data):
        if self._in_content:
            self._text_parts.append(data.strip())
            if self._in_link and "url" in self._current and "title" not in self._current:
                self._current["title"] = data.strip()
            elif self._in_link and "channel_url" in self._current and "channel" not in self._current:
                self._current["channel"] = data.strip()


def _extract_timestamp(text: str) -> str | None:
    """Try to extract a timestamp from text like 'Mar 15, 2025, 10:30:00 AM EST'."""
    # Common Google Takeout timestamp formats
    patterns = [
        r"(\w{3}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}:\d{2}\s*[AP]M)",
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})",
        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def parse_watch_history_html(filepath: str) -> list[dict]:
    """Parse YouTube watch-history.html file."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    parser = WatchHistoryHTMLParser()
    parser.feed(content)
    return parser.entries


def parse_watch_history_json(filepath: str) -> list[dict]:
    """Parse YouTube watch-history.json file (newer Takeout format)."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = []
    for item in data:
        title = item.get("title", "")
        # Skip "Visited" entries and ad views
        if title.startswith("Visited") or title.startswith("Searched for"):
            continue

        url = ""
        video_id = None
        if "titleUrl" in item:
            url = item["titleUrl"]
            video_id = extract_video_id(url)

        # Clean title — remove "Watched " prefix
        if title.startswith("Watched "):
            title = title[8:]

        channel = ""
        subtitles = item.get("subtitles", [])
        if subtitles:
            channel = subtitles[0].get("name", "")

        entry = {
            "title": title,
            "url": url,
            "channel": channel,
            "timestamp": item.get("time", ""),
        }
        if video_id:
            entry["video_id"] = video_id

        entries.append(entry)

    return entries


def parse_watch_history(takeout_dir: str) -> list[dict]:
    """Parse YouTube watch history from a Takeout directory. Tries JSON first, then HTML."""
    # Try different known paths — covers standard structure and variations
    yt_folders = ["YouTube and YouTube Music", "YouTube"]
    paths = []
    for yt in yt_folders:
        yt_dir = os.path.join(takeout_dir, yt)
        paths.extend([
            os.path.join(yt_dir, "history", "watch-history.json"),
            os.path.join(yt_dir, "history", "watch-history.html"),
            os.path.join(yt_dir, "watch-history.json"),
            os.path.join(yt_dir, "watch-history.html"),
        ])

    for path in paths:
        if os.path.exists(path):
            if path.endswith(".json"):
                return parse_watch_history_json(path)
            else:
                return parse_watch_history_html(path)

    return []


def parse_liked_videos(takeout_dir: str) -> list[dict]:
    """Parse YouTube liked videos playlist from Takeout."""
    paths = [
        os.path.join(takeout_dir, "YouTube and YouTube Music", "playlists", "Liked videos.json"),
        os.path.join(takeout_dir, "YouTube", "playlists", "Liked videos.json"),
    ]

    for path in paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            entries = []
            # Liked videos JSON has a different structure
            items = data if isinstance(data, list) else data.get("items", data.get("contentDetails", []))
            for item in items:
                if isinstance(item, dict):
                    url = item.get("contentDetails", {}).get("videoId", "")
                    if not url and "snippet" in item:
                        url = item["snippet"].get("resourceId", {}).get("videoId", "")
                    title = item.get("snippet", {}).get("title", "")

                    # Handle simple format: list of video IDs or URLs
                    if not url and isinstance(item.get("contentDetails"), str):
                        url = item["contentDetails"]

                    video_id = extract_video_id(url) if "youtube" in url or "youtu.be" in url else url

                    entries.append({
                        "title": title,
                        "url": f"https://youtube.com/watch?v={video_id}" if video_id else url,
                        "video_id": video_id,
                    })
            return entries

    return []


def parse_subscriptions(takeout_dir: str) -> list[dict]:
    """Parse YouTube subscriptions from Takeout."""
    paths = [
        os.path.join(takeout_dir, "YouTube and YouTube Music", "subscriptions", "subscriptions.json"),
        os.path.join(takeout_dir, "YouTube and YouTube Music", "subscriptions", "subscriptions.csv"),
        os.path.join(takeout_dir, "YouTube", "subscriptions", "subscriptions.json"),
        os.path.join(takeout_dir, "YouTube", "subscriptions", "subscriptions.csv"),
    ]

    for path in paths:
        if os.path.exists(path):
            if path.endswith(".json"):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entries = []
                items = data if isinstance(data, list) else data.get("items", [])
                for item in items:
                    if isinstance(item, dict):
                        snippet = item.get("snippet", item)
                        entries.append({
                            "channel_name": snippet.get("title", snippet.get("channelTitle", "")),
                            "channel_id": snippet.get("resourceId", {}).get("channelId",
                                          snippet.get("channelId", "")),
                            "channel_url": snippet.get("channelUrl",
                                           f"https://youtube.com/channel/{snippet.get('resourceId', {}).get('channelId', '')}"),
                        })
                return entries

            elif path.endswith(".csv"):
                entries = []
                with open(path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        entries.append({
                            "channel_name": row.get("Channel title", row.get("Title", "")),
                            "channel_id": row.get("Channel Id", row.get("Channel ID", "")),
                            "channel_url": row.get("Channel Url", row.get("Channel URL", "")),
                        })
                return entries

    return []


def find_youtube_data(takeout_dir: str) -> dict:
    """Scan a Takeout directory for available YouTube data types and their paths.

    Handles multiple Takeout variations:
    - Standard: YouTube and YouTube Music/history/watch-history.json
    - Older: YouTube/history/watch-history.html
    - Multi-part exports: YouTube folder may exist but history/ is in another part
    - Localized folder names
    """
    found = {}

    yt_dirs = [
        os.path.join(takeout_dir, "YouTube and YouTube Music"),
        os.path.join(takeout_dir, "YouTube"),
    ]

    for yt_dir in yt_dirs:
        if not os.path.isdir(yt_dir):
            continue

        found["_yt_dir"] = yt_dir  # Track which folder was found (for diagnostics)

        # Watch history — check multiple known locations
        watch_history_paths = [
            os.path.join(yt_dir, "history", "watch-history.json"),
            os.path.join(yt_dir, "history", "watch-history.html"),
            # Some exports put history directly in the root
            os.path.join(yt_dir, "watch-history.json"),
            os.path.join(yt_dir, "watch-history.html"),
        ]
        for path in watch_history_paths:
            if os.path.exists(path):
                found["watch_history"] = path
                break

        # Search history
        search_history_paths = [
            os.path.join(yt_dir, "history", "search-history.json"),
            os.path.join(yt_dir, "history", "search-history.html"),
            os.path.join(yt_dir, "search-history.json"),
            os.path.join(yt_dir, "search-history.html"),
        ]
        for path in search_history_paths:
            if os.path.exists(path):
                found["search_history"] = path
                break

        # Liked videos — check multiple naming conventions
        liked_paths = [
            os.path.join(yt_dir, "playlists", "Liked videos.json"),
            os.path.join(yt_dir, "playlists", "liked-videos.json"),
            os.path.join(yt_dir, "playlists", "Likes.json"),
            os.path.join(yt_dir, "likes", "Liked videos.json"),
        ]
        for path in liked_paths:
            if os.path.exists(path):
                found["liked_videos"] = path
                break

        # Subscriptions
        sub_paths = [
            os.path.join(yt_dir, "subscriptions", "subscriptions.json"),
            os.path.join(yt_dir, "subscriptions", "subscriptions.csv"),
            os.path.join(yt_dir, "subscriptions.json"),
            os.path.join(yt_dir, "subscriptions.csv"),
        ]
        for path in sub_paths:
            if os.path.exists(path):
                found["subscriptions"] = path
                break

        # If we found the YT dir but nothing inside, do a recursive file discovery
        # to help diagnose what data IS actually there (multi-part export case)
        if len(found) <= 1:  # Only _yt_dir set, no actual data files
            found["_available_files"] = _discover_youtube_files(yt_dir)

        break  # Use first found YT directory

    return found


def _discover_youtube_files(yt_dir: str) -> list[str]:
    """Walk a YouTube Takeout directory and list all files found.

    Used for diagnostics when no known data files are found at expected paths.
    """
    files = []
    for root, _dirs, filenames in os.walk(yt_dir):
        for fname in filenames:
            rel_path = os.path.relpath(os.path.join(root, fname), yt_dir)
            files.append(rel_path)
    return sorted(files)

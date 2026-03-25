"""Parser for Chrome data from Google Takeout exports.

Handles:
- Bookmarks (HTML format)
- Browsing history (JSON format)
"""

import json
import os
import re
from html.parser import HTMLParser


class BookmarkHTMLParser(HTMLParser):
    """Parse Chrome Bookmarks.html from Google Takeout."""

    def __init__(self):
        super().__init__()
        self.bookmarks = []
        self._folder_stack = []
        self._current_url = None
        self._current_add_date = None
        self._in_link = False
        self._in_folder_title = False
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "h3":
            self._in_folder_title = True
            self._text = []
        elif tag == "a":
            self._current_url = attrs_dict.get("href", "")
            self._current_add_date = attrs_dict.get("add_date", "")
            self._in_link = True
            self._text = []
        elif tag == "dl":
            pass  # folder contents start

    def handle_endtag(self, tag):
        if tag == "h3" and self._in_folder_title:
            folder_name = "".join(self._text).strip()
            self._folder_stack.append(folder_name)
            self._in_folder_title = False
        elif tag == "a" and self._in_link:
            title = "".join(self._text).strip()
            if self._current_url:
                self.bookmarks.append({
                    "title": title,
                    "url": self._current_url,
                    "folder": "/".join(self._folder_stack) if self._folder_stack else "Unsorted",
                    "add_date": self._current_add_date or "",
                })
            self._in_link = False
            self._current_url = None
        elif tag == "dl" and self._folder_stack:
            self._folder_stack.pop()

    def handle_data(self, data):
        if self._in_link or self._in_folder_title:
            self._text.append(data)


def parse_bookmarks_html(filepath: str) -> list[dict]:
    """Parse Chrome Bookmarks.html file."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    parser = BookmarkHTMLParser()
    parser.feed(content)
    return parser.bookmarks


def parse_browsing_history_json(filepath: str) -> list[dict]:
    """Parse Chrome BrowsingHistory.json file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = []
    items = data.get("Browser History", data) if isinstance(data, dict) else data

    if isinstance(items, list):
        for item in items:
            entries.append({
                "title": item.get("title", ""),
                "url": item.get("url", item.get("page_url", "")),
                "timestamp": item.get("time_usec", item.get("timestamp", "")),
                "visit_count": item.get("visit_count", 1),
            })

    return entries


def find_chrome_data(takeout_dir: str) -> dict:
    """Scan a Takeout directory for Chrome data."""
    found = {}

    chrome_dir = os.path.join(takeout_dir, "Chrome")
    if not os.path.isdir(chrome_dir):
        return found

    bookmarks_path = os.path.join(chrome_dir, "Bookmarks.html")
    if os.path.exists(bookmarks_path):
        found["bookmarks"] = bookmarks_path

    history_path = os.path.join(chrome_dir, "BrowsingHistory.json")
    if os.path.exists(history_path):
        found["browsing_history"] = history_path

    return found

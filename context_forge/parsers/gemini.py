"""Parser for Gemini conversation data from Google Takeout.

Gemini conversations are stored in Takeout as individual HTML files in the
Gemini Apps/ folder, or as JSON in newer exports.
"""

import json
import os
import re
from datetime import datetime
from html.parser import HTMLParser


class GeminiHTMLParser(HTMLParser):
    """Parse a single Gemini conversation HTML file."""

    def __init__(self):
        super().__init__()
        self.messages = []
        self._current_role = None
        self._current_text = []
        self._in_message = False
        self._in_text = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        if "user-message" in cls or "human-message" in cls:
            self._current_role = "user"
            self._in_message = True
            self._current_text = []
        elif "model-message" in cls or "assistant-message" in cls or "ai-message" in cls:
            self._current_role = "assistant"
            self._in_message = True
            self._current_text = []

        if self._in_message and tag in ("p", "div", "span", "li", "code", "pre"):
            self._in_text = True

    def handle_endtag(self, tag):
        if self._in_text and tag in ("p", "div"):
            self._current_text.append("\n")
            self._in_text = False

        if self._in_message and tag == "div":
            text = "".join(self._current_text).strip()
            if text and self._current_role:
                self.messages.append({
                    "role": self._current_role,
                    "content": text,
                })
            self._in_message = False
            self._current_text = []

    def handle_data(self, data):
        if self._in_message:
            self._current_text.append(data)


def parse_gemini_html(filepath: str) -> dict:
    """Parse a single Gemini conversation HTML file into normalized format."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Try to extract title from HTML <title> or filename
    title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
    title = title_match.group(1) if title_match else os.path.splitext(os.path.basename(filepath))[0]

    parser = GeminiHTMLParser()
    parser.feed(content)

    # Try to get timestamp from file metadata
    mtime = os.path.getmtime(filepath)
    created_at = datetime.fromtimestamp(mtime).isoformat()

    return {
        "source": "gemini",
        "id": os.path.splitext(os.path.basename(filepath))[0],
        "title": title,
        "messages": parser.messages,
        "created_at": created_at,
        "updated_at": created_at,
        "file_path": filepath,
    }


def parse_gemini_json(filepath: str) -> list[dict]:
    """Parse Gemini conversations from a JSON export file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    conversations = []
    items = data if isinstance(data, list) else [data]

    for item in items:
        messages = []
        for msg in item.get("messages", item.get("turns", [])):
            role = msg.get("role", msg.get("author", ""))
            if role in ("model", "assistant", "gemini"):
                role = "assistant"
            elif role in ("human", "user"):
                role = "user"

            content = msg.get("content", msg.get("text", ""))
            if isinstance(content, list):
                content = "\n".join(
                    p.get("text", str(p)) for p in content if isinstance(p, dict)
                ) or str(content)

            if content:
                messages.append({
                    "role": role,
                    "content": content,
                    "timestamp": msg.get("timestamp", msg.get("create_time", "")),
                })

        conversations.append({
            "source": "gemini",
            "id": item.get("id", item.get("conversation_id", "")),
            "title": item.get("title", item.get("name", "Untitled")),
            "messages": messages,
            "created_at": item.get("create_time", item.get("created_at", "")),
            "updated_at": item.get("update_time", item.get("updated_at", "")),
        })

    return conversations


def find_gemini_data(takeout_dir: str) -> dict:
    """Scan a Takeout directory for Gemini conversation data."""
    found = {}

    gemini_dirs = [
        os.path.join(takeout_dir, "Gemini Apps"),
        os.path.join(takeout_dir, "Google Bard"),
        os.path.join(takeout_dir, "Gemini"),
    ]

    for gdir in gemini_dirs:
        if not os.path.isdir(gdir):
            continue

        # Check for individual HTML conversation files
        html_files = [f for f in os.listdir(gdir) if f.endswith(".html")]
        json_files = [f for f in os.listdir(gdir) if f.endswith(".json")]

        if html_files:
            found["conversations_html"] = [os.path.join(gdir, f) for f in html_files]
        if json_files:
            found["conversations_json"] = [os.path.join(gdir, f) for f in json_files]

        # Check for a conversations subfolder
        conv_dir = os.path.join(gdir, "conversations")
        if os.path.isdir(conv_dir):
            sub_html = [os.path.join(conv_dir, f) for f in os.listdir(conv_dir) if f.endswith(".html")]
            sub_json = [os.path.join(conv_dir, f) for f in os.listdir(conv_dir) if f.endswith(".json")]
            if sub_html:
                found.setdefault("conversations_html", []).extend(sub_html)
            if sub_json:
                found.setdefault("conversations_json", []).extend(sub_json)

        if found:
            break

    return found


def parse_all_gemini(takeout_dir: str) -> list[dict]:
    """Parse all Gemini conversations from a Takeout directory."""
    data = find_gemini_data(takeout_dir)
    conversations = []

    for json_file in data.get("conversations_json", []):
        try:
            conversations.extend(parse_gemini_json(json_file))
        except (json.JSONDecodeError, KeyError):
            pass

    for html_file in data.get("conversations_html", []):
        try:
            conversations.append(parse_gemini_html(html_file))
        except Exception:
            pass

    return conversations

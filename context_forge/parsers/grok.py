"""Parser for Grok conversation exports from X/Twitter.

Grok export format is not yet standardized. This parser handles common
formats: JSON conversations and potential HTML exports.
"""

import json
import os
from datetime import datetime


def parse_grok_json(filepath: str) -> list[dict]:
    """Parse Grok conversations from a JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    conversations = []
    items = data if isinstance(data, list) else [data]

    for item in items:
        messages = []
        for msg in item.get("messages", item.get("turns", [])):
            role = msg.get("role", msg.get("sender", ""))
            if role in ("grok", "assistant", "model"):
                role = "assistant"
            elif role in ("human", "user"):
                role = "user"

            content = msg.get("content", msg.get("text", msg.get("message", "")))
            if isinstance(content, list):
                content = "\n".join(str(p) for p in content)

            if content:
                messages.append({
                    "role": role,
                    "content": content,
                    "timestamp": msg.get("timestamp", msg.get("created_at", "")),
                })

        conversations.append({
            "source": "grok",
            "id": str(item.get("id", item.get("conversation_id", ""))),
            "title": item.get("title", item.get("name", "Untitled")),
            "messages": messages,
            "created_at": item.get("created_at", item.get("create_time", "")),
            "updated_at": item.get("updated_at", item.get("update_time", "")),
        })

    return conversations


def find_grok_data(export_dir: str) -> dict:
    """Scan a Grok export directory for conversation data."""
    found = {}

    if not os.path.isdir(export_dir):
        return found

    json_files = []
    for root, _dirs, files in os.walk(export_dir):
        for f in files:
            if f.endswith(".json"):
                json_files.append(os.path.join(root, f))

    if json_files:
        found["conversations"] = json_files

    return found


def parse_all_grok(export_dir: str) -> list[dict]:
    """Parse all Grok conversations from an export directory."""
    data = find_grok_data(export_dir)
    conversations = []

    for json_file in data.get("conversations", []):
        try:
            conversations.extend(parse_grok_json(json_file))
        except (json.JSONDecodeError, KeyError):
            pass

    return conversations

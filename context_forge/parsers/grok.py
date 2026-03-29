"""Parser for Grok conversation exports from X/Twitter.

Grok exports come as JSON files (e.g. prod-grok-backend.json) containing
conversation data. This parser handles both single files and directories.
"""

import json
import os
from datetime import datetime


def parse_grok_json(filepath: str) -> list[dict]:
    """Parse Grok conversations from a JSON file.

    Handles multiple JSON structures:
    - Array of conversation objects (each with messages/turns)
    - Array of flat message objects (grouped by conversation_id)
    - Single conversation object
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data if isinstance(data, list) else [data]

    if not items:
        return []

    # Detect format: are these top-level conversation objects with messages,
    # or flat message records that need grouping?
    first = items[0]
    if "messages" in first or "turns" in first:
        return _parse_conversation_objects(items)
    elif "conversation_id" in first or "conversationId" in first:
        return _parse_flat_messages(items)
    else:
        # Try as conversation objects anyway (best effort)
        return _parse_conversation_objects(items)


def _parse_conversation_objects(items: list[dict]) -> list[dict]:
    """Parse items that are conversation objects with nested messages."""
    conversations = []

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


def _parse_flat_messages(items: list[dict]) -> list[dict]:
    """Parse flat message records and group by conversation_id."""
    from collections import OrderedDict

    groups = OrderedDict()
    for msg in items:
        conv_id = str(msg.get("conversation_id", msg.get("conversationId", "unknown")))
        if conv_id not in groups:
            groups[conv_id] = []
        groups[conv_id].append(msg)

    conversations = []
    for conv_id, msgs in groups.items():
        # Sort by timestamp if available
        msgs.sort(key=lambda m: m.get("timestamp", m.get("created_at", m.get("createdAt", ""))))

        messages = []
        for msg in msgs:
            role = msg.get("role", msg.get("sender", ""))
            if role in ("grok", "assistant", "model"):
                role = "assistant"
            elif role in ("human", "user"):
                role = "user"

            content = msg.get("content", msg.get("text", msg.get("message", "")))
            if isinstance(content, list):
                content = "\n".join(str(p) for p in content)

            if content:
                timestamp = msg.get("timestamp", msg.get("created_at", msg.get("createdAt", "")))
                messages.append({
                    "role": role,
                    "content": content,
                    "timestamp": str(timestamp) if timestamp else "",
                })

        # Derive title from first user message
        title = "Untitled"
        for m in messages:
            if m["role"] == "user" and m["content"]:
                title = m["content"][:80].split("\n")[0]
                break

        timestamps = [m["timestamp"] for m in messages if m.get("timestamp")]
        created = min(timestamps) if timestamps else ""
        updated = max(timestamps) if timestamps else ""

        conversations.append({
            "source": "grok",
            "id": conv_id,
            "title": title,
            "messages": messages,
            "created_at": created,
            "updated_at": updated,
        })

    return conversations


def find_grok_data(path: str) -> dict:
    """Check if a Grok export exists and get basic info.

    Accepts:
    - Path to a single JSON file (e.g. prod-grok-backend.json)
    - Path to a directory containing JSON files
    """
    found = {}

    if os.path.isfile(path) and path.endswith(".json"):
        found["conversations"] = [path]
        return found

    if not os.path.isdir(path):
        return found

    json_files = []
    for root, _dirs, files in os.walk(path):
        for f in files:
            if f.endswith(".json"):
                json_files.append(os.path.join(root, f))

    if json_files:
        found["conversations"] = json_files

    return found


def parse_all_grok(path: str) -> list[dict]:
    """Parse all Grok conversations from a file or directory.

    Args:
        path: Path to a single .json file or a directory containing JSON files.
    """
    data = find_grok_data(path)
    conversations = []

    for json_file in data.get("conversations", []):
        try:
            conversations.extend(parse_grok_json(json_file))
        except (json.JSONDecodeError, KeyError):
            pass

    return conversations

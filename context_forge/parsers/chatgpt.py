"""Parser for ChatGPT conversation exports.

ChatGPT exports come as a conversations.json file containing all conversations
with their full message trees.
"""

import json
import os
from datetime import datetime


def parse_conversations_json(filepath: str) -> list[dict]:
    """Parse ChatGPT conversations.json into normalized conversation format."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    conversations = []

    for conv in data:
        title = conv.get("title", "Untitled")
        conv_id = conv.get("id", conv.get("conversation_id", ""))
        create_time = conv.get("create_time")
        update_time = conv.get("update_time")

        # ChatGPT stores messages as a tree in "mapping"
        messages = _extract_messages_from_mapping(conv.get("mapping", {}))

        # Extract project/folder info if available
        project = conv.get("project", conv.get("folder", None))
        if project and isinstance(project, dict):
            project = project.get("name", project.get("title", ""))

        conversations.append({
            "source": "chatgpt",
            "id": conv_id,
            "title": title,
            "messages": messages,
            "created_at": _format_timestamp(create_time),
            "updated_at": _format_timestamp(update_time),
            "project": project or "",
        })

    return conversations


def _extract_messages_from_mapping(mapping: dict) -> list[dict]:
    """Extract ordered messages from ChatGPT's tree-based mapping structure."""
    if not mapping:
        return []

    # Build parent-child relationships
    children_map = {}
    for node_id, node in mapping.items():
        parent = node.get("parent")
        if parent:
            children_map.setdefault(parent, []).append(node_id)

    # Find root node (no parent)
    root_id = None
    for node_id, node in mapping.items():
        if node.get("parent") is None:
            root_id = node_id
            break

    if root_id is None:
        return []

    # Walk the tree depth-first, following the last child at each level
    # (ChatGPT conversations are linear — each message has at most one active child)
    messages = []
    current_id = root_id

    while current_id:
        node = mapping.get(current_id, {})
        message = node.get("message")

        if message and message.get("content"):
            role = message.get("author", {}).get("role", "")
            content = message["content"]

            # Content can be a dict with "parts" or a string
            if isinstance(content, dict):
                parts = content.get("parts", [])
                text = "\n".join(
                    str(p) for p in parts
                    if isinstance(p, str) and p.strip()
                )
            elif isinstance(content, str):
                text = content
            else:
                text = str(content)

            if text.strip() and role in ("user", "assistant"):
                timestamp = message.get("create_time")
                messages.append({
                    "role": role,
                    "content": text.strip(),
                    "timestamp": _format_timestamp(timestamp),
                })

        # Move to next message (first/only child)
        child_ids = children_map.get(current_id, [])
        current_id = child_ids[0] if child_ids else None

    return messages


def _format_timestamp(ts) -> str:
    """Convert a Unix timestamp to ISO format string."""
    if ts is None:
        return ""
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts).isoformat()
        return str(ts)
    except (ValueError, OSError):
        return str(ts)


def find_chatgpt_data(path: str) -> dict:
    """Check if a ChatGPT export file exists and get basic info."""
    found = {}

    if os.path.isfile(path) and path.endswith(".json"):
        found["conversations"] = path
    elif os.path.isdir(path):
        conv_path = os.path.join(path, "conversations.json")
        if os.path.exists(conv_path):
            found["conversations"] = conv_path

    return found

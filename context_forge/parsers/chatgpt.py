"""Parser for ChatGPT conversation exports.

ChatGPT exports come as a conversations.json file containing all conversations
with their full message trees.
"""

import glob
import json
import os
from datetime import datetime


def parse_conversations_json(filepath: str) -> list[dict]:
    """Parse ChatGPT conversations.json (or multiple split files) into normalized format.

    Args:
        filepath: Path to a single .json file, or a directory containing
                  conversations-*.json split files.
    """
    data = _load_chatgpt_json(filepath)
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


def _load_chatgpt_json(filepath: str) -> list[dict]:
    """Load ChatGPT conversation data from a single file or directory of split files.

    OpenAI exports large histories as numbered files:
    conversations-000.json, conversations-001.json, ..., conversations-013.json

    Args:
        filepath: A single .json file path, or a directory containing split files.

    Returns:
        Merged list of raw conversation dicts.
    """
    if os.path.isdir(filepath):
        return _load_split_files(filepath)

    if os.path.isfile(filepath):
        # Check if this is one file in a set of split files
        parent_dir = os.path.dirname(filepath)
        basename = os.path.basename(filepath)

        # If it's a split file (conversations-NNN.json), load all siblings
        if _is_split_filename(basename):
            return _load_split_files(parent_dir)

        # Single file
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else [data]

    return []


def _is_split_filename(filename: str) -> bool:
    """Check if a filename matches the split pattern: conversations-NNN.json."""
    import re
    return bool(re.match(r"conversations-\d+\.json$", filename))


def _load_split_files(directory: str) -> list[dict]:
    """Load and merge all conversations-*.json split files from a directory."""
    patterns = [
        os.path.join(directory, "conversations-*.json"),
        os.path.join(directory, "conversations.json"),
    ]

    files = set()
    for pattern in patterns:
        files.update(glob.glob(pattern))

    if not files:
        return []

    all_conversations = []
    for fpath in sorted(files):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                all_conversations.extend(data)
            else:
                all_conversations.append(data)
        except (json.JSONDecodeError, IOError):
            pass

    return all_conversations


def find_chatgpt_data(path: str) -> dict:
    """Check if a ChatGPT export exists and get basic info.

    Accepts:
    - Path to a single conversations.json file
    - Path to a directory containing conversations.json or conversations-NNN.json split files
    """
    found = {}

    if os.path.isfile(path) and path.endswith(".json"):
        found["conversations"] = path
        # Count split siblings if this is one of them
        parent_dir = os.path.dirname(path)
        basename = os.path.basename(path)
        if _is_split_filename(basename):
            split_files = glob.glob(os.path.join(parent_dir, "conversations-*.json"))
            found["file_count"] = len(split_files)
        else:
            found["file_count"] = 1

    elif os.path.isdir(path):
        # Check for split files first (more specific), then single file
        split_files = glob.glob(os.path.join(path, "conversations-*.json"))
        single_file = os.path.join(path, "conversations.json")

        if split_files:
            found["conversations"] = path  # Pass directory — parser handles it
            found["file_count"] = len(split_files)
        elif os.path.exists(single_file):
            found["conversations"] = single_file
            found["file_count"] = 1

    return found

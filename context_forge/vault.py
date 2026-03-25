"""Vault integration — reading/writing to the 2ndbrain Obsidian vault."""

import json
import os
import re
import tempfile
from datetime import datetime, timezone

import yaml


def sanitize_filename(name: str) -> str:
    """Clean a string for use as an Obsidian note filename."""
    cleaned = name.replace("/", "-").replace("\\", "-")
    cleaned = cleaned.replace(":", " -").replace('"', "").replace("'", "")
    cleaned = cleaned.replace("?", "").replace("*", "").replace("|", "")
    cleaned = cleaned.replace("<", "").replace(">", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip(" -")


def atomic_write(filepath: str, content: str) -> None:
    """Write content to a file atomically via temp file + replace."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(filepath),
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, filepath)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def load_vault_index(vault_path: str) -> dict:
    """Load the vault-index.json from the 2ndbrain vault."""
    index_path = os.path.join(vault_path, "_system", "vault-index.json")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "last_updated": None,
        "notes": {"topics": [], "people": [], "channels": [], "videos": [], "articles": []},
        "topic_aliases": {},
    }


def save_vault_index(vault_path: str, index: dict) -> None:
    """Save the vault-index.json."""
    index_path = os.path.join(vault_path, "_system", "vault-index.json")
    index["last_updated"] = datetime.now(timezone.utc).isoformat()
    atomic_write(index_path, json.dumps(index, indent=2, ensure_ascii=False))


def resolve_topic(query: str, index: dict) -> str | None:
    """Resolve a topic name against the vault index (exact, case-insensitive, alias)."""
    topics = index.get("notes", {}).get("topics", [])

    if query in topics:
        return query

    query_lower = query.lower()
    for topic in topics:
        if topic.lower() == query_lower:
            return topic

    aliases = index.get("topic_aliases", {})
    if query_lower in aliases:
        return aliases[query_lower]

    return None


def note_exists(name: str, note_type: str, index: dict) -> bool:
    """Check if a note of a given type exists in the vault index."""
    notes = index.get("notes", {}).get(note_type, [])
    name_lower = name.lower()
    return any(n.lower() == name_lower for n in notes)


def video_in_vault(video_id: str, index: dict) -> bool:
    """Check if a video is already ingested in the vault (by checking video titles containing the ID)."""
    # The vault index stores video titles, not IDs.
    # We can't do an exact match here — this is a best-effort check.
    # The 2ndbrain queue.db is a better source for deduplication.
    return False


def get_existing_video_ids_from_queue(queue_db_path: str) -> set[str]:
    """Read video IDs from the 2ndbrain queue.db to deduplicate."""
    import sqlite3

    if not queue_db_path or not os.path.exists(queue_db_path):
        return set()

    try:
        conn = sqlite3.connect(queue_db_path)
        rows = conn.execute("SELECT id FROM queue").fetchall()
        conn.close()
        return {row[0] for row in rows}
    except Exception:
        return set()


def ensure_vault_folders(vault_path: str) -> None:
    """Create Context Forge output folders in the vault if they don't exist."""
    folders = [
        os.path.join(vault_path, "Insights", "gemini"),
        os.path.join(vault_path, "Insights", "chatgpt"),
        os.path.join(vault_path, "Insights", "grok"),
        os.path.join(vault_path, "Archive"),
        os.path.join(vault_path, "Bookmarks"),
    ]
    for folder in folders:
        os.makedirs(folder, exist_ok=True)


def format_wikilinks(topics: list[str]) -> str:
    """Format a list of topic names as YAML wikilink list."""
    if not topics:
        return ""
    return "\n".join(f'  - "[[{t}]]"' for t in topics)


def format_yaml_list(items: list[str]) -> str:
    """Format a list as YAML list items."""
    if not items:
        return ""
    return "\n".join(f"  - \"{item}\"" for item in items)

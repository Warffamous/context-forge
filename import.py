#!/usr/bin/env python3
"""
import.py — Context Forge Importer (Program 2)

Processes selected data through appropriate pipelines and outputs
Obsidian-compatible markdown into the vault.

Usage:
    python import.py --youtube-history    # Feed watch history into 2ndbrain queue
    python import.py --youtube-liked      # Import liked videos (priority)
    python import.py --youtube-subs       # Import subscriptions to watch list
    python import.py --gemini             # Extract knowledge from Gemini conversations
    python import.py --chatgpt            # Extract knowledge from ChatGPT conversations
    python import.py --grok               # Extract knowledge from Grok conversations
    python import.py --bookmarks          # Import Chrome bookmarks
    python import.py --topics-index       # Generate topic index archives
    python import.py --status             # Show import queue status
    python import.py --resume             # Resume interrupted import
"""

import argparse
import json
import os
import sys

from context_forge.config import load_config, validate_config
from context_forge.queue_db import ImportQueueDB
from context_forge.vault import ensure_vault_folders, load_vault_index
from context_forge.importers.youtube_bridge import (
    bridge_liked_videos,
    bridge_subscriptions,
    bridge_watch_history,
)
from context_forge.importers.chat_extractor import process_conversations
from context_forge.importers.bookmarks import import_bookmarks
from context_forge.importers.topics_index import generate_all_indexes
from context_forge.parsers.gemini import parse_all_gemini
from context_forge.parsers.chatgpt import parse_conversations_json, find_chatgpt_data
from context_forge.parsers.grok import parse_all_grok


def get_db(config: dict) -> ImportQueueDB:
    """Create and initialize the import queue database."""
    vault_path = config.get("vault_path", "")
    if vault_path:
        db_path = os.path.join(vault_path, "_system", "import-queue.db")
    else:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "import-queue.db")

    db = ImportQueueDB(db_path)
    db.init_db()
    return db


def get_secondbrain_queue_path(config: dict) -> str:
    """Resolve the path to 2ndbrain's queue.db."""
    path = config.get("secondbrain_queue_db", "")
    if path and os.path.exists(path):
        return path

    vault_path = config.get("vault_path", "")
    if vault_path:
        candidate = os.path.join(vault_path, "_system", "queue.db")
        if os.path.exists(candidate):
            return candidate

    return ""


def cmd_youtube_history(config: dict):
    """Import YouTube watch history into 2ndbrain queue."""
    takeout_dirs = [d for d in config.get("takeout_dirs", []) if d and os.path.isdir(d)]
    if not takeout_dirs:
        print("Error: No valid takeout_dirs configured.", file=sys.stderr)
        return

    queue_path = get_secondbrain_queue_path(config)
    if not queue_path:
        print("Error: 2ndbrain queue.db not found. Set secondbrain_queue_db in config.yaml", file=sys.stderr)
        return

    print("Importing YouTube watch history → 2ndbrain queue...")
    result = bridge_watch_history(
        takeout_dirs, queue_path,
        min_watch_seconds=config.get("youtube_min_watch_seconds", 30),
    )
    print(f"  Added: {result['added']}, Skipped: {result['skipped']}, Errors: {result['errors']}")
    print(f"  Total parsed: {result['total_parsed']}")
    print("Run 2ndbrain's ingest.py to process the queued videos.")


def cmd_youtube_liked(config: dict):
    """Import YouTube liked videos into 2ndbrain queue."""
    takeout_dirs = [d for d in config.get("takeout_dirs", []) if d and os.path.isdir(d)]
    if not takeout_dirs:
        print("Error: No valid takeout_dirs configured.", file=sys.stderr)
        return

    queue_path = get_secondbrain_queue_path(config)
    if not queue_path:
        print("Error: 2ndbrain queue.db not found.", file=sys.stderr)
        return

    print("Importing YouTube liked videos → 2ndbrain queue (priority)...")
    result = bridge_liked_videos(takeout_dirs, queue_path)
    print(f"  Added: {result['added']}, Skipped: {result['skipped']}")


def cmd_youtube_subs(config: dict):
    """Import YouTube subscriptions."""
    takeout_dirs = [d for d in config.get("takeout_dirs", []) if d and os.path.isdir(d)]
    if not takeout_dirs:
        print("Error: No valid takeout_dirs configured.", file=sys.stderr)
        return

    print("Importing YouTube subscriptions...")
    result = bridge_subscriptions(takeout_dirs, config)
    subs = result["subscriptions"]

    print(f"  Found {result['total']} subscriptions")
    if subs:
        print("\n  Subscriptions:")
        for sub in subs:
            name = sub.get("channel_name", "Unknown")
            cid = sub.get("channel_id", "")
            print(f"    - {name} ({cid})")
        print(f"\n  To add these to the 2ndbrain watch system, use:")
        print(f"  python watch.py --subscribe <channel_url>")


def cmd_gemini(config: dict):
    """Extract knowledge from Gemini conversations."""
    errors = validate_config(config, require_api_key=True)
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return

    takeout_dirs = [d for d in config.get("takeout_dirs", []) if d and os.path.isdir(d)]
    vault_path = config["vault_path"]

    print("Parsing Gemini conversations...")
    conversations = []
    for tdir in takeout_dirs:
        conversations.extend(parse_all_gemini(tdir))

    if not conversations:
        print("  No Gemini conversations found.")
        return

    print(f"  Found {len(conversations)} conversations")

    db = get_db(config)
    try:
        result = process_conversations(conversations, config, db, vault_path, "gemini")
        print(f"\n  Results: {result['scored']} scored, {result['extracted']} extracted, {result['written']} notes written")
    finally:
        db.close()


def cmd_chatgpt(config: dict):
    """Extract knowledge from ChatGPT conversations."""
    errors = validate_config(config, require_api_key=True)
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return

    chatgpt_path = config.get("chatgpt_export")
    if not chatgpt_path:
        print("Error: chatgpt_export not configured.", file=sys.stderr)
        return

    vault_path = config["vault_path"]

    print("Parsing ChatGPT conversations...")
    data = find_chatgpt_data(chatgpt_path)
    if "conversations" not in data:
        print(f"  No conversations.json found at: {chatgpt_path}")
        return

    conversations = parse_conversations_json(data["conversations"])
    if not conversations:
        print("  No conversations found.")
        return

    print(f"  Found {len(conversations)} conversations")

    db = get_db(config)
    try:
        result = process_conversations(conversations, config, db, vault_path, "chatgpt")
        print(f"\n  Results: {result['scored']} scored, {result['extracted']} extracted, {result['written']} notes written")
    finally:
        db.close()


def cmd_grok(config: dict):
    """Extract knowledge from Grok conversations."""
    errors = validate_config(config, require_api_key=True)
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return

    grok_path = config.get("grok_export")
    if not grok_path:
        print("Error: grok_export not configured.", file=sys.stderr)
        return

    vault_path = config["vault_path"]

    print("Parsing Grok conversations...")
    conversations = parse_all_grok(grok_path)
    if not conversations:
        print("  No Grok conversations found.")
        return

    print(f"  Found {len(conversations)} conversations")

    db = get_db(config)
    try:
        result = process_conversations(conversations, config, db, vault_path, "grok")
        print(f"\n  Results: {result['scored']} scored, {result['extracted']} extracted, {result['written']} notes written")
    finally:
        db.close()


def cmd_bookmarks(config: dict):
    """Import Chrome bookmarks into vault."""
    takeout_dirs = [d for d in config.get("takeout_dirs", []) if d and os.path.isdir(d)]
    vault_path = config.get("vault_path", "")

    if not takeout_dirs:
        print("Error: No valid takeout_dirs configured.", file=sys.stderr)
        return
    if not vault_path:
        print("Error: vault_path not configured.", file=sys.stderr)
        return

    print("Importing Chrome bookmarks...")
    result = import_bookmarks(takeout_dirs, vault_path)
    print(f"  Total bookmarks: {result['total']}")
    print(f"  Folders: {result['folders']}")
    print(f"  Notes written: {result['written']}")


def cmd_topics_index(config: dict):
    """Generate topic index archives."""
    vault_path = config.get("vault_path", "")
    if not vault_path:
        print("Error: vault_path not configured.", file=sys.stderr)
        return

    print("Generating topics indexes...")
    written = generate_all_indexes(vault_path)
    if written:
        for path in written:
            print(f"  Written: {os.path.basename(path)}")
    else:
        print("  No insight notes found to index.")


def cmd_status(config: dict):
    """Show import queue status."""
    db = get_db(config)
    try:
        print("=" * 50)
        print("Context Forge Import Status")
        print("=" * 50)

        for source in ("gemini", "chatgpt", "grok"):
            counts = db.get_status_counts(source=source)
            if counts:
                total = sum(counts.values())
                print(f"\n  {source.capitalize()}:")
                print(f"    Pending:    {counts.get('pending', 0):4d}")
                print(f"    Processing: {counts.get('processing', 0):4d}")
                print(f"    Complete:   {counts.get('complete', 0):4d}")
                print(f"    Skipped:    {counts.get('skipped', 0):4d}")
                print(f"    Failed:     {counts.get('failed', 0):4d}")
                print(f"    Total:      {total:4d}")

        usage = db.get_usage_today()
        print(f"\n  API Usage (today):")
        print(f"    Anthropic calls: {usage.get('anthropic_calls', 0)}")
        print(f"    Items processed: {usage.get('items_processed', 0)}")

        print("=" * 50)
    finally:
        db.close()


def cmd_resume(config: dict):
    """Resume interrupted import — reprocess pending items."""
    errors = validate_config(config, require_api_key=True)
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return

    vault_path = config["vault_path"]
    db = get_db(config)

    try:
        # Reset any stuck 'processing' items
        conn = db._connect()
        conn.execute(
            "UPDATE import_queue SET status = 'pending' WHERE status = 'processing'"
        )
        conn.commit()

        # Check what's pending
        for source in ("gemini", "chatgpt", "grok"):
            pending = db.get_pending(source=source)
            if not pending:
                continue

            print(f"\nResuming {len(pending)} pending {source} items...")

            # We need to re-parse the conversations to get message content
            conversations = _reload_conversations(config, source)
            if conversations:
                result = process_conversations(conversations, config, db, vault_path, source)
                print(f"  Results: {result['scored']} scored, {result['extracted']} extracted, {result['written']} written")

    finally:
        db.close()


def _reload_conversations(config: dict, source: str) -> list[dict]:
    """Reload conversations from source for resume."""
    if source == "gemini":
        takeout_dirs = [d for d in config.get("takeout_dirs", []) if d and os.path.isdir(d)]
        conversations = []
        for tdir in takeout_dirs:
            conversations.extend(parse_all_gemini(tdir))
        return conversations

    elif source == "chatgpt":
        chatgpt_path = config.get("chatgpt_export")
        if chatgpt_path:
            data = find_chatgpt_data(chatgpt_path)
            if "conversations" in data:
                return parse_conversations_json(data["conversations"])
        return []

    elif source == "grok":
        grok_path = config.get("grok_export")
        if grok_path:
            return parse_all_grok(grok_path)
        return []

    return []


def main():
    parser = argparse.ArgumentParser(
        description="Context Forge Importer — Process data exports into vault notes",
    )
    parser.add_argument("--config", default=None, help="Path to config.yaml")

    # Import commands
    parser.add_argument("--youtube-history", action="store_true", help="Import watch history → 2ndbrain queue")
    parser.add_argument("--youtube-liked", action="store_true", help="Import liked videos → 2ndbrain queue")
    parser.add_argument("--youtube-subs", action="store_true", help="Import subscriptions list")
    parser.add_argument("--gemini", action="store_true", help="Extract from Gemini conversations")
    parser.add_argument("--chatgpt", action="store_true", help="Extract from ChatGPT conversations")
    parser.add_argument("--grok", action="store_true", help="Extract from Grok conversations")
    parser.add_argument("--bookmarks", action="store_true", help="Import Chrome bookmarks")
    parser.add_argument("--topics-index", action="store_true", help="Generate topic index archives")

    # Management
    parser.add_argument("--status", action="store_true", help="Show import queue status")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted import")

    args = parser.parse_args()

    # Need at least one action
    actions = [
        args.youtube_history, args.youtube_liked, args.youtube_subs,
        args.gemini, args.chatgpt, args.grok,
        args.bookmarks, args.topics_index,
        args.status, args.resume,
    ]
    if not any(actions):
        parser.print_help()
        sys.exit(1)

    config = load_config(args.config)

    # Dispatch
    if args.status:
        cmd_status(config)
    if args.youtube_history:
        cmd_youtube_history(config)
    if args.youtube_liked:
        cmd_youtube_liked(config)
    if args.youtube_subs:
        cmd_youtube_subs(config)
    if args.gemini:
        cmd_gemini(config)
    if args.chatgpt:
        cmd_chatgpt(config)
    if args.grok:
        cmd_grok(config)
    if args.bookmarks:
        cmd_bookmarks(config)
    if args.topics_index:
        cmd_topics_index(config)
    if args.resume:
        cmd_resume(config)


if __name__ == "__main__":
    main()

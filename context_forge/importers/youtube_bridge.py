"""YouTube History → 2ndbrain Queue Bridge.

Extracts video URLs from Google Takeout watch history and feeds them into the
existing 2ndbrain queue.db for processing by ingest.py.
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone

from context_forge.parsers.youtube import (
    extract_video_id,
    parse_liked_videos,
    parse_subscriptions,
    parse_watch_history,
)
from context_forge.vault import get_existing_video_ids_from_queue


def bridge_watch_history(
    takeout_dirs: list[str],
    secondbrain_queue_db: str,
    min_watch_seconds: int = 30,
) -> dict:
    """
    Parse YouTube watch history and insert new videos into the 2ndbrain queue.

    Returns summary dict with counts.
    """
    if not secondbrain_queue_db or not os.path.exists(secondbrain_queue_db):
        print(f"Error: 2ndbrain queue.db not found at: {secondbrain_queue_db}", file=sys.stderr)
        return {"added": 0, "skipped": 0, "errors": 0}

    # Get already-queued video IDs
    existing_ids = get_existing_video_ids_from_queue(secondbrain_queue_db)
    print(f"  Existing videos in 2ndbrain queue: {len(existing_ids)}")

    # Parse watch history from all Takeout directories
    all_entries = []
    for tdir in takeout_dirs:
        entries = parse_watch_history(tdir)
        all_entries.extend(entries)
    print(f"  Total watch history entries: {len(all_entries)}")

    # Deduplicate by video_id
    seen = set()
    unique = []
    for entry in all_entries:
        vid = entry.get("video_id")
        if vid and vid not in seen:
            seen.add(vid)
            unique.append(entry)

    # Filter out already-ingested
    new_entries = [e for e in unique if e.get("video_id") not in existing_ids]
    print(f"  New videos to queue: {len(new_entries)}")

    # Insert into 2ndbrain queue
    conn = sqlite3.connect(secondbrain_queue_db)
    added = 0
    skipped = 0
    errors = 0

    for entry in new_entries:
        video_id = entry.get("video_id")
        if not video_id:
            skipped += 1
            continue

        url = entry.get("url", f"https://youtube.com/watch?v={video_id}")
        title = entry.get("title")
        channel = entry.get("channel")

        try:
            conn.execute(
                """INSERT OR IGNORE INTO queue (id, url, title, channel, source)
                   VALUES (?, ?, ?, ?, ?)""",
                (video_id, url, title, channel, "context-forge"),
            )
            if conn.total_changes:
                added += 1
        except sqlite3.Error as e:
            errors += 1

    conn.commit()
    conn.close()

    return {"added": added, "skipped": skipped, "errors": errors, "total_parsed": len(all_entries)}


def bridge_liked_videos(
    takeout_dirs: list[str],
    secondbrain_queue_db: str,
) -> dict:
    """
    Parse liked videos and insert into 2ndbrain queue with priority.
    Liked videos get priority=1 so they're processed first.
    """
    if not secondbrain_queue_db or not os.path.exists(secondbrain_queue_db):
        return {"added": 0, "skipped": 0, "errors": 0}

    existing_ids = get_existing_video_ids_from_queue(secondbrain_queue_db)

    all_entries = []
    for tdir in takeout_dirs:
        entries = parse_liked_videos(tdir)
        all_entries.extend(entries)

    # The 2ndbrain queue doesn't have a priority column by default,
    # so we just insert them. They'll be processed in order.
    conn = sqlite3.connect(secondbrain_queue_db)
    added = 0
    skipped = 0
    errors = 0

    for entry in all_entries:
        video_id = entry.get("video_id")
        if not video_id or video_id in existing_ids:
            skipped += 1
            continue

        url = entry.get("url", f"https://youtube.com/watch?v={video_id}")
        title = entry.get("title")

        try:
            conn.execute(
                """INSERT OR IGNORE INTO queue (id, url, title, source)
                   VALUES (?, ?, ?, ?)""",
                (video_id, url, title, "context-forge-liked"),
            )
            added += 1
        except sqlite3.Error:
            errors += 1

    conn.commit()
    conn.close()

    return {"added": added, "skipped": skipped, "errors": errors, "total_parsed": len(all_entries)}


def bridge_subscriptions(
    takeout_dirs: list[str],
    config: dict,
) -> dict:
    """
    Parse YouTube subscriptions and report them for the 2ndbrain watch system.
    Returns the subscription list for the user to configure.
    """
    all_subs = []
    for tdir in takeout_dirs:
        subs = parse_subscriptions(tdir)
        all_subs.extend(subs)

    # Deduplicate by channel_id
    seen = set()
    unique = []
    for sub in all_subs:
        cid = sub.get("channel_id")
        if cid and cid not in seen:
            seen.add(cid)
            unique.append(sub)

    return {"subscriptions": unique, "total": len(unique)}

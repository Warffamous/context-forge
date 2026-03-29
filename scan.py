#!/usr/bin/env python3
"""
scan.py — Context Forge Scanner (Program 1)

Fast, local-only, no API calls. Scans Google Takeout directories, ChatGPT
exports, and Grok exports. Generates a scan-report.md triage report.

Usage:
    python scan.py --takeout ~/Takeout
    python scan.py --takeout ~/Takeout-1 --takeout ~/Takeout-2
    python scan.py --takeout ~/Takeout --chatgpt ~/chatgpt-export-dir
    python scan.py --takeout ~/Takeout --grok ~/grok-export/prod-grok-backend.json
    python scan.py --gemini-dir ~/gemini-texts
    python scan.py --takeout ~/Takeout --vault ~/Knowledge-Web
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from context_forge.config import load_config
from context_forge.parsers.youtube import (
    find_youtube_data,
    parse_watch_history,
    parse_liked_videos,
    parse_subscriptions,
)
from context_forge.parsers.gemini import find_gemini_data, parse_all_gemini
from context_forge.parsers.chatgpt import find_chatgpt_data, parse_conversations_json
from context_forge.parsers.grok import find_grok_data, parse_all_grok
from context_forge.parsers.gemini_text import find_gemini_text_files, parse_all_gemini_text
from context_forge.parsers.chrome import find_chrome_data, parse_bookmarks_html, parse_browsing_history_json
from context_forge.vault import load_vault_index, get_existing_video_ids_from_queue


def scan_youtube(takeout_dirs: list[str], vault_index: dict, existing_video_ids: set, min_watch_seconds: int) -> dict:
    """Scan YouTube data across all Takeout directories."""
    result = {
        "watch_history": {"entries": [], "paths": []},
        "liked_videos": {"entries": [], "paths": []},
        "subscriptions": {"entries": [], "paths": []},
    }

    result["_diagnostics"] = []

    for tdir in takeout_dirs:
        yt_data = find_youtube_data(tdir)

        if "watch_history" in yt_data:
            result["watch_history"]["paths"].append(yt_data["watch_history"])
            entries = parse_watch_history(tdir)
            result["watch_history"]["entries"].extend(entries)

        if "liked_videos" in yt_data:
            result["liked_videos"]["paths"].append(yt_data["liked_videos"])
            entries = parse_liked_videos(tdir)
            result["liked_videos"]["entries"].extend(entries)

        if "subscriptions" in yt_data:
            result["subscriptions"]["paths"].append(yt_data["subscriptions"])
            entries = parse_subscriptions(tdir)
            result["subscriptions"]["entries"].extend(entries)

        # Diagnostic: YouTube folder found but no data files at expected locations
        if "_yt_dir" in yt_data and "watch_history" not in yt_data:
            available = yt_data.get("_available_files", [])
            result["_diagnostics"].append({
                "takeout_dir": tdir,
                "yt_dir": yt_data["_yt_dir"],
                "message": "YouTube folder found but no watch history file detected",
                "files_found": available,
            })

    # Deduplicate watch history by video_id
    seen_ids = set()
    unique_entries = []
    for entry in result["watch_history"]["entries"]:
        vid = entry.get("video_id")
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            unique_entries.append(entry)
        elif not vid:
            unique_entries.append(entry)
    result["watch_history"]["entries"] = unique_entries

    # Count already-ingested
    already_ingested = sum(
        1 for e in result["watch_history"]["entries"]
        if e.get("video_id") in existing_video_ids
    )
    result["watch_history"]["already_ingested"] = already_ingested
    result["watch_history"]["new_count"] = len(result["watch_history"]["entries"]) - already_ingested

    # Count unique channels
    channels = set()
    for e in result["watch_history"]["entries"]:
        ch = e.get("channel")
        if ch:
            channels.add(ch)
    result["watch_history"]["unique_channels"] = len(channels)

    # Date range
    timestamps = [e.get("timestamp", "") for e in result["watch_history"]["entries"] if e.get("timestamp")]
    if timestamps:
        result["watch_history"]["date_range"] = (min(timestamps), max(timestamps))
    else:
        result["watch_history"]["date_range"] = None

    return result


def scan_gemini(takeout_dirs: list[str]) -> dict:
    """Scan Gemini conversation data."""
    result = {"conversations": [], "paths": []}

    for tdir in takeout_dirs:
        gemini_data = find_gemini_data(tdir)
        if gemini_data:
            all_paths = gemini_data.get("conversations_html", []) + gemini_data.get("conversations_json", [])
            result["paths"].extend(all_paths)
            convs = parse_all_gemini(tdir)
            result["conversations"].extend(convs)

    return result


def scan_chatgpt(chatgpt_path: str | None) -> dict:
    """Scan ChatGPT export data."""
    result = {"conversations": [], "path": None, "file_count": 0}

    if not chatgpt_path:
        return result

    data = find_chatgpt_data(chatgpt_path)
    if "conversations" in data:
        result["path"] = data["conversations"]
        result["file_count"] = data.get("file_count", 1)
        result["conversations"] = parse_conversations_json(data["conversations"])

    return result


def scan_grok(grok_path: str | None) -> dict:
    """Scan Grok export data. Accepts a single JSON file or a directory."""
    result = {"conversations": [], "path": None}

    if not grok_path:
        return result

    data = find_grok_data(grok_path)
    if data:
        result["path"] = grok_path
        result["conversations"] = parse_all_grok(grok_path)

    return result


def scan_gemini_text(gemini_dirs: list[str]) -> dict:
    """Scan Gemini plain text files from directories."""
    result = {"conversations": [], "paths": [], "file_count": 0}

    if not gemini_dirs:
        return result

    for path in gemini_dirs:
        txt_files = find_gemini_text_files(path)
        result["paths"].extend(txt_files)
        result["file_count"] += len(txt_files)

    result["conversations"] = parse_all_gemini_text(gemini_dirs)
    return result


def scan_chrome(takeout_dirs: list[str]) -> dict:
    """Scan Chrome data (bookmarks, browsing history)."""
    result = {
        "bookmarks": {"entries": [], "paths": []},
        "browsing_history": {"entries": [], "paths": []},
    }

    for tdir in takeout_dirs:
        chrome_data = find_chrome_data(tdir)

        if "bookmarks" in chrome_data:
            result["bookmarks"]["paths"].append(chrome_data["bookmarks"])
            entries = parse_bookmarks_html(chrome_data["bookmarks"])
            result["bookmarks"]["entries"].extend(entries)

        if "browsing_history" in chrome_data:
            result["browsing_history"]["paths"].append(chrome_data["browsing_history"])
            entries = parse_browsing_history_json(chrome_data["browsing_history"])
            result["browsing_history"]["entries"].extend(entries)

    # Unique bookmark folders
    folders = set()
    for b in result["bookmarks"]["entries"]:
        folders.add(b.get("folder", "Unsorted"))
    result["bookmarks"]["folders"] = sorted(folders)

    return result


def conversation_stats(conversations: list[dict], min_messages: int = 5) -> dict:
    """Compute statistics for a list of conversations."""
    total = len(conversations)
    if total == 0:
        return {"total": 0, "substantive": 0, "avg_messages": 0, "date_range": None, "projects": []}

    msg_counts = [len(c.get("messages", [])) for c in conversations]
    substantive = sum(1 for mc in msg_counts if mc >= min_messages)
    avg_messages = sum(msg_counts) / total if total > 0 else 0

    # Date range
    dates = []
    for c in conversations:
        for field in ("created_at", "updated_at"):
            d = c.get(field, "")
            if d:
                dates.append(d)

    date_range = (min(dates), max(dates)) if dates else None

    # Projects (ChatGPT specific)
    projects = set()
    for c in conversations:
        p = c.get("project", "")
        if p:
            projects.add(p)

    return {
        "total": total,
        "substantive": substantive,
        "avg_messages": round(avg_messages, 1),
        "date_range": date_range,
        "projects": sorted(projects),
    }


def generate_report(
    youtube: dict,
    gemini: dict,
    chatgpt: dict,
    grok: dict,
    chrome: dict,
    min_messages: int = 5,
    gemini_text: dict | None = None,
) -> str:
    """Generate the scan-report.md content."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Context Forge — Scan Report",
        f"## Generated: {now}",
        "",
    ]

    # YouTube Watch History
    wh = youtube["watch_history"]
    total_wh = len(wh["entries"])
    if total_wh > 0:
        lines.append("### YouTube Watch History")
        lines.append(f"- Total videos: {total_wh}")
        if wh.get("date_range"):
            lines.append(f"- Date range: {wh['date_range'][0]} → {wh['date_range'][1]}")
        lines.append(f"- Already in vault: {wh.get('already_ingested', 0)} (will be skipped)")
        lines.append(f"- New videos to potentially ingest: {wh.get('new_count', total_wh)}")
        lines.append(f"- Unique channels: {wh.get('unique_channels', 0)}")
        est_cost = wh.get("new_count", total_wh) * 0.01
        lines.append(f"- Estimated API cost for full ingest: ~${est_cost:.2f} (at ~$0.01/video)")
        lines.append("")

    # YouTube Liked Videos
    lv = youtube["liked_videos"]
    if len(lv["entries"]) > 0:
        lines.append("### YouTube Liked Videos")
        lines.append(f"- Total liked videos: {len(lv['entries'])}")
        lines.append("")

    # YouTube Subscriptions
    subs = youtube["subscriptions"]
    if len(subs["entries"]) > 0:
        lines.append("### YouTube Subscriptions")
        lines.append(f"- Total subscriptions: {len(subs['entries'])}")
        lines.append("")

    # Gemini
    gemini_stats = conversation_stats(gemini["conversations"], min_messages)
    if gemini_stats["total"] > 0:
        lines.append("### Gemini Conversations")
        lines.append(f"- Total conversations: {gemini_stats['total']}")
        lines.append(f"- Substantive (>{min_messages} messages): {gemini_stats['substantive']}")
        lines.append(f"- Average messages per conversation: {gemini_stats['avg_messages']}")
        if gemini_stats["date_range"]:
            lines.append(f"- Date range: {gemini_stats['date_range'][0]} → {gemini_stats['date_range'][1]}")
        lines.append("")

    # Gemini (plain text)
    gemini_text_stats = conversation_stats(
        (gemini_text or {}).get("conversations", []), min_messages
    )
    if gemini_text_stats["total"] > 0:
        lines.append("### Gemini Conversations (Plain Text)")
        file_count = (gemini_text or {}).get("file_count", 0)
        if file_count:
            lines.append(f"- Source files: {file_count} .txt files")
        lines.append(f"- Total conversations: {gemini_text_stats['total']}")
        lines.append(f"- Substantive (>{min_messages} messages): {gemini_text_stats['substantive']}")
        lines.append(f"- Average messages per conversation: {gemini_text_stats['avg_messages']}")
        if gemini_text_stats["date_range"]:
            lines.append(f"- Date range: {gemini_text_stats['date_range'][0]} → {gemini_text_stats['date_range'][1]}")
        lines.append("")

    # ChatGPT
    chatgpt_stats = conversation_stats(chatgpt["conversations"], min_messages)
    if chatgpt_stats["total"] > 0:
        lines.append("### ChatGPT Conversations")
        file_count = chatgpt.get("file_count", 0)
        if file_count > 1:
            lines.append(f"- Source files: {file_count} (conversations-000.json through conversations-{file_count-1:03d}.json)")
        lines.append(f"- Total conversations: {chatgpt_stats['total']}")
        lines.append(f"- Substantive (>{min_messages} messages): {chatgpt_stats['substantive']}")
        lines.append(f"- Average messages per conversation: {chatgpt_stats['avg_messages']}")
        if chatgpt_stats["projects"]:
            lines.append(f"- Projects: {len(chatgpt_stats['projects'])} ({', '.join(chatgpt_stats['projects'][:10])})")
        if chatgpt_stats["date_range"]:
            lines.append(f"- Date range: {chatgpt_stats['date_range'][0]} → {chatgpt_stats['date_range'][1]}")
        lines.append("")

    # Grok
    grok_stats = conversation_stats(grok["conversations"], min_messages)
    if grok_stats["total"] > 0:
        lines.append("### Grok Conversations")
        lines.append(f"- Total conversations: {grok_stats['total']}")
        lines.append(f"- Substantive (>{min_messages} messages): {grok_stats['substantive']}")
        if grok_stats["date_range"]:
            lines.append(f"- Date range: {grok_stats['date_range'][0]} → {grok_stats['date_range'][1]}")
        lines.append("")

    # Chrome Bookmarks
    bm = chrome["bookmarks"]
    if len(bm["entries"]) > 0:
        lines.append("### Chrome Bookmarks")
        lines.append(f"- Total bookmarks: {len(bm['entries'])}")
        if bm.get("folders"):
            lines.append(f"- Folders: {', '.join(bm['folders'][:15])}")
        lines.append("")

    # Chrome Browsing History
    bh = chrome["browsing_history"]
    if len(bh["entries"]) > 0:
        lines.append("### Chrome Browsing History")
        lines.append(f"- Total entries: {len(bh['entries'])}")
        lines.append("")

    # Summary — nothing found
    has_data = any([
        total_wh > 0,
        len(lv["entries"]) > 0,
        len(subs["entries"]) > 0,
        gemini_stats["total"] > 0,
        gemini_text_stats["total"] > 0,
        chatgpt_stats["total"] > 0,
        grok_stats["total"] > 0,
        len(bm["entries"]) > 0,
    ])

    if not has_data:
        lines.append("### No Data Found")
        lines.append("No recognized data types were found in the provided paths.")
        lines.append("Make sure Takeout directories are fully unzipped.")
        lines.append("")

    # Diagnostics for partially-found data
    diagnostics = youtube.get("_diagnostics", [])
    if diagnostics:
        lines.append("### Diagnostics")
        for diag in diagnostics:
            lines.append(f"**{diag['message']}**")
            lines.append(f"- Takeout: `{diag['takeout_dir']}`")
            lines.append(f"- YouTube folder: `{diag['yt_dir']}`")
            files = diag.get("files_found", [])
            if files:
                lines.append(f"- Files found in YouTube folder ({len(files)}):")
                for f in files[:30]:
                    lines.append(f"  - `{f}`")
                if len(files) > 30:
                    lines.append(f"  - ... and {len(files) - 30} more")
            else:
                lines.append("- No files found (folder may be empty — check other Takeout parts)")
            lines.append("")
            lines.append("This typically happens with multi-part Takeout exports. "
                         "The YouTube folder exists in this part but the watch history "
                         "data is in a different zip file. Try pointing to a different "
                         "part, or merge all parts into a single directory.")
            lines.append("")

    # Recommended Import Priority
    if has_data:
        lines.append("## Recommended Import Priority")
        priority = 1
        if len(subs["entries"]) > 0:
            lines.append(f"{priority}. YouTube subscriptions → Watch system (immediate, no API cost)")
            priority += 1
        if len(lv["entries"]) > 0:
            lines.append(f"{priority}. YouTube liked videos → Priority ingest queue")
            priority += 1
        if gemini_stats["substantive"] > 0:
            lines.append(f"{priority}. Gemini conversations (substantive) → LLM extraction")
            priority += 1
        if gemini_text_stats["substantive"] > 0:
            lines.append(f"{priority}. Gemini plain-text conversations (substantive) → LLM extraction")
            priority += 1
        if chatgpt_stats["substantive"] > 0:
            lines.append(f"{priority}. ChatGPT conversations (substantive) → LLM extraction")
            priority += 1
        if total_wh > 0:
            lines.append(f"{priority}. YouTube watch history → Batch ingest queue (largest volume, highest API cost)")
            priority += 1
        if grok_stats["substantive"] > 0:
            lines.append(f"{priority}. Grok conversations → LLM extraction")
            priority += 1
        if len(bm["entries"]) > 0:
            lines.append(f"{priority}. Chrome bookmarks → Reference notes")
            priority += 1
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Context Forge Scanner — Scan data exports and generate triage report",
    )
    parser.add_argument(
        "--takeout",
        action="append",
        default=[],
        metavar="DIR",
        help="Path to unzipped Google Takeout directory (can specify multiple)",
    )
    parser.add_argument(
        "--chatgpt",
        default=None,
        metavar="PATH",
        help="Path to ChatGPT conversations.json or export directory",
    )
    parser.add_argument(
        "--grok",
        default=None,
        metavar="PATH",
        help="Path to Grok export JSON file or directory",
    )
    parser.add_argument(
        "--gemini-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="Path to directory of Gemini plain-text .txt files (can specify multiple)",
    )
    parser.add_argument(
        "--vault",
        default=None,
        metavar="DIR",
        help="Path to 2ndbrain vault (for deduplication)",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--output",
        default="scan-report.md",
        metavar="PATH",
        help="Output path for scan report (default: scan-report.md)",
    )

    args = parser.parse_args()

    # Load config for defaults
    config = load_config(args.config)

    # Merge CLI args with config
    takeout_dirs = args.takeout or [d for d in config.get("takeout_dirs", []) if d]
    chatgpt_path = args.chatgpt or config.get("chatgpt_export")
    grok_path = args.grok or config.get("grok_export")
    gemini_dirs = args.gemini_dir or [d for d in config.get("gemini_dirs", []) if d]
    vault_path = args.vault or config.get("vault_path", "")
    min_messages = config.get("chat_min_messages", 5)

    if not takeout_dirs and not chatgpt_path and not grok_path and not gemini_dirs:
        print("Error: No data sources specified.", file=sys.stderr)
        print("Use --takeout, --chatgpt, --grok, or --gemini-dir to specify data paths.", file=sys.stderr)
        sys.exit(1)

    # Validate paths
    for tdir in takeout_dirs:
        if not os.path.isdir(tdir):
            print(f"Warning: Takeout directory not found: {tdir}", file=sys.stderr)

    # Load vault index for deduplication
    vault_index = load_vault_index(vault_path) if vault_path and os.path.isdir(vault_path) else {}

    # Get existing video IDs from 2ndbrain queue
    queue_db_path = config.get("secondbrain_queue_db", "")
    if not queue_db_path and vault_path:
        queue_db_path = os.path.join(vault_path, "_system", "queue.db")
    existing_video_ids = get_existing_video_ids_from_queue(queue_db_path)

    print("Context Forge Scanner")
    print("=" * 40)

    # Scan all sources
    valid_takeout_dirs = [d for d in takeout_dirs if os.path.isdir(d)]

    print(f"Scanning {len(valid_takeout_dirs)} Takeout director{'y' if len(valid_takeout_dirs) == 1 else 'ies'}...")
    youtube = scan_youtube(valid_takeout_dirs, vault_index, existing_video_ids, config.get("youtube_min_watch_seconds", 30))
    print(f"  YouTube: {len(youtube['watch_history']['entries'])} watch history, "
          f"{len(youtube['liked_videos']['entries'])} liked, "
          f"{len(youtube['subscriptions']['entries'])} subscriptions")
    for diag in youtube.get("_diagnostics", []):
        print(f"  WARNING: {diag['message']} in {os.path.basename(diag['takeout_dir'])}")
        files = diag.get("files_found", [])
        if files:
            print(f"    Files found: {', '.join(files[:5])}{'...' if len(files) > 5 else ''}")
        else:
            print(f"    YouTube folder is empty — watch history likely in another Takeout part")

    print("Scanning Gemini conversations...")
    gemini = scan_gemini(valid_takeout_dirs)
    print(f"  Gemini: {len(gemini['conversations'])} conversations")

    print("Scanning ChatGPT export...")
    chatgpt = scan_chatgpt(chatgpt_path)
    file_info = f" (from {chatgpt['file_count']} files)" if chatgpt.get("file_count", 0) > 1 else ""
    print(f"  ChatGPT: {len(chatgpt['conversations'])} conversations{file_info}")

    print("Scanning Grok export...")
    grok = scan_grok(grok_path)
    print(f"  Grok: {len(grok['conversations'])} conversations")

    gemini_text = {"conversations": [], "paths": [], "file_count": 0}
    if gemini_dirs:
        print("Scanning Gemini plain-text files...")
        gemini_text = scan_gemini_text(gemini_dirs)
        print(f"  Gemini (text): {len(gemini_text['conversations'])} conversations from {gemini_text['file_count']} files")

    print("Scanning Chrome data...")
    chrome = scan_chrome(valid_takeout_dirs)
    print(f"  Chrome: {len(chrome['bookmarks']['entries'])} bookmarks, "
          f"{len(chrome['browsing_history']['entries'])} history entries")

    # Generate report
    report = generate_report(youtube, gemini, chatgpt, grok, chrome, min_messages, gemini_text)

    # Write report
    output_path = os.path.abspath(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nReport written to: {output_path}")
    print("Review the report, then use import.py to process selected data types.")


if __name__ == "__main__":
    main()

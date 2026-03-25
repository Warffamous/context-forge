"""Chrome Bookmarks → Vault Reference Notes importer."""

import os
from datetime import datetime, timezone

from context_forge.parsers.chrome import find_chrome_data, parse_bookmarks_html
from context_forge.vault import atomic_write, sanitize_filename


def import_bookmarks(takeout_dirs: list[str], vault_path: str) -> dict:
    """
    Parse Chrome bookmarks and write reference notes to the vault.

    Creates a Bookmarks/ folder with one index note per bookmark folder.
    Returns summary dict.
    """
    all_bookmarks = []
    for tdir in takeout_dirs:
        chrome_data = find_chrome_data(tdir)
        if "bookmarks" in chrome_data:
            all_bookmarks.extend(parse_bookmarks_html(chrome_data["bookmarks"]))

    if not all_bookmarks:
        return {"total": 0, "folders": 0, "written": 0}

    # Group by folder
    by_folder = {}
    for bm in all_bookmarks:
        folder = bm.get("folder", "Unsorted")
        by_folder.setdefault(folder, []).append(bm)

    # Write bookmark index notes
    bookmarks_dir = os.path.join(vault_path, "Bookmarks")
    os.makedirs(bookmarks_dir, exist_ok=True)
    written = 0
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for folder, bookmarks in sorted(by_folder.items()):
        safe_name = sanitize_filename(folder.replace("/", " - "))
        if not safe_name:
            safe_name = "Unsorted"

        lines = [
            "---",
            "type: bookmarks",
            f"folder: \"{folder}\"",
            f"count: {len(bookmarks)}",
            f"date_imported: {date}",
            "---",
            "",
            f"# Bookmarks — {folder}",
            "",
        ]

        for bm in bookmarks:
            title = bm.get("title", "Untitled")
            url = bm.get("url", "")
            lines.append(f"- [{title}]({url})")

        lines.append("")

        filepath = os.path.join(bookmarks_dir, f"{safe_name}.md")
        atomic_write(filepath, "\n".join(lines))
        written += 1

    return {"total": len(all_bookmarks), "folders": len(by_folder), "written": written}

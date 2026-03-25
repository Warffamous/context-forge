"""Topics Index Generator — creates compressed archive maps per source."""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from context_forge.vault import atomic_write, load_vault_index, sanitize_filename


def generate_topics_index(vault_path: str, source: str) -> str | None:
    """
    Generate a topics-index.md for a given source (gemini, chatgpt, grok).

    Reads all Insight notes for that source and groups them by topic,
    creating a compressed overview.

    Returns the filepath written, or None if no notes found.
    """
    insights_dir = os.path.join(vault_path, "Insights", source)
    if not os.path.isdir(insights_dir):
        return None

    # Read all insight notes and extract frontmatter
    topic_clusters = defaultdict(list)

    for filename in os.listdir(insights_dir):
        if not filename.endswith(".md"):
            continue

        filepath = os.path.join(insights_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except (IOError, UnicodeDecodeError):
            continue

        # Parse frontmatter
        frontmatter = _parse_frontmatter(content)
        if not frontmatter:
            continue

        title = filename.replace(".md", "")
        date = frontmatter.get("date", "")
        density = frontmatter.get("density", 0)
        topics = frontmatter.get("topics", [])

        # Clean topic names (remove [[ ]] wikilink syntax)
        clean_topics = []
        for t in topics:
            if isinstance(t, str):
                t = t.strip().strip('"').replace("[[", "").replace("]]", "")
                if t:
                    clean_topics.append(t)

        note_info = {
            "title": title,
            "date": date,
            "density": density,
            "source_id": frontmatter.get("source_id", ""),
        }

        for topic in clean_topics:
            topic_clusters[topic].append(note_info)

        # Also add to a general cluster if no topics
        if not clean_topics:
            topic_clusters["Uncategorized"].append(note_info)

    if not topic_clusters:
        return None

    # Generate the index
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "---",
        "type: topics-index",
        f"source: {source}",
        f"generated: {now}",
        f"topic_count: {len(topic_clusters)}",
        "---",
        "",
        f"# {source.capitalize()} — Topics Index",
        "",
        f"*Generated: {now}*",
        "",
    ]

    for topic in sorted(topic_clusters.keys()):
        notes = topic_clusters[topic]
        notes.sort(key=lambda n: n.get("date", ""))

        dates = [n["date"] for n in notes if n.get("date")]
        date_range = f"{min(dates)} → {max(dates)}" if dates else "Unknown"

        avg_density = sum(n.get("density", 0) for n in notes) / len(notes) if notes else 0

        lines.append(f"## [[{topic}]]")
        lines.append(f"- **Period:** {date_range}")
        lines.append(f"- **Conversations:** {len(notes)}")
        lines.append(f"- **Average density:** {avg_density:.1f}/5")

        # List source conversations
        lines.append(f"- **Source notes:**")
        for n in notes:
            lines.append(f"  - [[{n['title']}]] ({n.get('date', '?')})")

        lines.append("")

    # Write to Archive folder
    archive_dir = os.path.join(vault_path, "Archive")
    os.makedirs(archive_dir, exist_ok=True)
    filepath = os.path.join(archive_dir, f"{source}-topics-index.md")
    atomic_write(filepath, "\n".join(lines))

    return filepath


def generate_all_indexes(vault_path: str) -> list[str]:
    """Generate topics indexes for all sources. Returns list of filepaths written."""
    written = []
    for source in ("gemini", "chatgpt", "grok"):
        path = generate_topics_index(vault_path, source)
        if path:
            written.append(path)
    return written


def _parse_frontmatter(content: str) -> dict | None:
    """Extract YAML frontmatter from markdown content."""
    import re
    import yaml

    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None

    try:
        return yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None

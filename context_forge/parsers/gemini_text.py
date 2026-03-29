"""Parser for Gemini conversations manually copied as plain text files.

These are copy-pastes from the Gemini web UI into .txt files. The parser
detects conversation boundaries and speaker turns, normalizing into the
standard conversation format.

Expected patterns in the text:
- Speaker turns indicated by lines like "You", "Gemini", or similar labels
  followed by a newline and their message content
- Multiple conversations may be in a single file, separated by visual
  dividers or "New chat" / conversation title patterns
"""

import hashlib
import os
import re
from datetime import datetime


# Patterns that indicate the start of a user turn
USER_PATTERNS = [
    re.compile(r"^You\s*$", re.MULTILINE),
    re.compile(r"^You:\s*$", re.MULTILINE),
    re.compile(r"^User:\s*$", re.MULTILINE),
    re.compile(r"^Human:\s*$", re.MULTILINE),
    re.compile(r"^\*\*You\*\*\s*$", re.MULTILINE),
]

# Patterns that indicate the start of an assistant turn
ASSISTANT_PATTERNS = [
    re.compile(r"^Gemini\s*$", re.MULTILINE),
    re.compile(r"^Gemini:\s*$", re.MULTILINE),
    re.compile(r"^Model:\s*$", re.MULTILINE),
    re.compile(r"^Assistant:\s*$", re.MULTILINE),
    re.compile(r"^\*\*Gemini\*\*\s*$", re.MULTILINE),
    re.compile(r"^Gemini Advanced\s*$", re.MULTILINE),
]

# Patterns that indicate a conversation boundary
BOUNDARY_PATTERNS = [
    re.compile(r"^-{3,}\s*$", re.MULTILINE),          # --- divider
    re.compile(r"^={3,}\s*$", re.MULTILINE),           # === divider
    re.compile(r"^\*{3,}\s*$", re.MULTILINE),          # *** divider
    re.compile(r"^New [Cc]hat\s*$", re.MULTILINE),     # "New chat" marker
    re.compile(r"^Conversation \d+", re.MULTILINE),     # "Conversation 1" header
]


def _detect_turn_markers(text: str) -> list[tuple[int, str]]:
    """Find all speaker turn markers and their positions in the text.

    Returns list of (position, role) tuples sorted by position.
    """
    markers = []

    for pattern in USER_PATTERNS:
        for match in pattern.finditer(text):
            markers.append((match.start(), match.end(), "user"))

    for pattern in ASSISTANT_PATTERNS:
        for match in pattern.finditer(text):
            markers.append((match.start(), match.end(), "assistant"))

    # Sort by position
    markers.sort(key=lambda m: m[0])
    return markers


def _detect_boundaries(text: str) -> list[int]:
    """Find conversation boundary positions in the text."""
    boundaries = []
    for pattern in BOUNDARY_PATTERNS:
        for match in pattern.finditer(text):
            boundaries.append(match.start())
    boundaries.sort()
    return boundaries


def _split_into_conversations(text: str) -> list[str]:
    """Split text into individual conversation chunks."""
    boundaries = _detect_boundaries(text)

    if not boundaries:
        return [text]

    chunks = []
    prev = 0
    for boundary in boundaries:
        chunk = text[prev:boundary].strip()
        if chunk:
            chunks.append(chunk)
        # Skip past the boundary line itself
        next_newline = text.find("\n", boundary)
        prev = next_newline + 1 if next_newline != -1 else len(text)

    # Last chunk
    remainder = text[prev:].strip()
    if remainder:
        chunks.append(remainder)

    return chunks if chunks else [text]


def _parse_conversation_text(text: str) -> list[dict]:
    """Parse a single conversation's text into messages."""
    markers = _detect_turn_markers(text)

    if not markers:
        # No turn markers found — treat entire text as a single user message
        stripped = text.strip()
        if stripped:
            return [{"role": "user", "content": stripped}]
        return []

    messages = []
    for i, (start, end, role) in enumerate(markers):
        # Content runs from end of this marker to start of next marker
        if i + 1 < len(markers):
            content = text[end:markers[i + 1][0]]
        else:
            content = text[end:]

        content = content.strip()
        if content:
            messages.append({
                "role": role,
                "content": content,
            })

    return messages


def _generate_id(text: str, index: int) -> str:
    """Generate a stable ID for a conversation based on content."""
    h = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"gemini-text-{h}-{index}"


def _derive_title(messages: list[dict]) -> str:
    """Derive a title from the first user message."""
    for msg in messages:
        if msg["role"] == "user" and msg["content"]:
            first_line = msg["content"].split("\n")[0]
            return first_line[:80] if len(first_line) > 80 else first_line
    return "Untitled"


def parse_gemini_text_file(filepath: str) -> list[dict]:
    """Parse a single Gemini plain text file into normalized conversations.

    A single file may contain multiple conversations separated by dividers.
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    if not text.strip():
        return []

    chunks = _split_into_conversations(text)
    conversations = []

    # Get file modification time as fallback timestamp
    try:
        mtime = os.path.getmtime(filepath)
        file_date = datetime.fromtimestamp(mtime).isoformat()
    except OSError:
        file_date = ""

    # Extract account info from filename if present
    basename = os.path.splitext(os.path.basename(filepath))[0]

    for i, chunk in enumerate(chunks):
        messages = _parse_conversation_text(chunk)
        if not messages:
            continue

        conv_id = _generate_id(chunk, i)
        title = _derive_title(messages)

        conversations.append({
            "source": "gemini",
            "id": conv_id,
            "title": title,
            "messages": messages,
            "created_at": file_date,
            "updated_at": file_date,
            "source_file": basename,
        })

    return conversations


def find_gemini_text_files(directory: str) -> list[str]:
    """Find all .txt files in a directory (non-recursive)."""
    if not os.path.isdir(directory):
        # If it's a single file, return it
        if os.path.isfile(directory) and directory.endswith(".txt"):
            return [directory]
        return []

    txt_files = []
    for f in os.listdir(directory):
        if f.endswith(".txt"):
            txt_files.append(os.path.join(directory, f))

    return sorted(txt_files)


def parse_all_gemini_text(directories: list[str]) -> list[dict]:
    """Parse all Gemini plain text conversations from one or more directories.

    Args:
        directories: List of directory paths (or individual file paths)
                     containing Gemini .txt files.
    """
    conversations = []

    for path in directories:
        txt_files = find_gemini_text_files(path)
        for filepath in txt_files:
            try:
                convs = parse_gemini_text_file(filepath)
                conversations.extend(convs)
            except Exception:
                pass

    return conversations

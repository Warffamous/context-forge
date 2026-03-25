"""Chat Extraction Pipeline — LLM-powered knowledge extraction from conversations.

Handles Gemini, ChatGPT, and Grok conversations through a unified pipeline:
1. Source-specific parsing → normalized conversation format
2. LLM density scoring (cheap, fast pass)
3. Selective full extraction (density >= threshold)
4. Vault note writing (Insight notes + topic updates)
"""

import json
import os
import time
from datetime import datetime, timezone

import anthropic

from context_forge.queue_db import ImportQueueDB
from context_forge.vault import (
    atomic_write,
    ensure_vault_folders,
    format_wikilinks,
    load_vault_index,
    resolve_topic,
    sanitize_filename,
    save_vault_index,
)


DENSITY_SCORING_PROMPT = """\
Rate this conversation's knowledge density on a 1-5 scale:
1 = Throwaway (greetings, simple questions, no lasting value)
2 = Low (basic info lookup, easily re-derived)
3 = Medium (some decisions or synthesized knowledge)
4 = High (significant conclusions, decisions, or original analysis)
5 = Critical (foundational decisions, deep research, unique insights)

Also extract: main topics (max 5), people mentioned, decisions made (if any).

Conversation title: {title}
Source: {source}

Messages (compressed):
{messages}

Respond in JSON only with this structure:
{{
  "density": <1-5>,
  "topics": ["topic1", "topic2"],
  "people": ["Person Name"],
  "decisions": ["decision description"],
  "brief_summary": "One sentence summary"
}}"""


EXTRACTION_PROMPT = """\
You are a knowledge extractor. Analyze this conversation and extract all valuable knowledge for a personal knowledge management system (Obsidian vault with wiki-links).

Conversation title: {title}
Source: {source}
Date: {date}

Full conversation:
{messages}

Existing vault topics (use these exact names for wiki-links when they match):
{existing_topics}

Extract and return as JSON:
{{
  "title": "Descriptive title for this insight note",
  "summary": "2-3 sentence summary",
  "key_conclusions": ["conclusion 1", "conclusion 2"],
  "decisions": [
    {{"decision": "what was decided", "reasoning": "why"}}
  ],
  "topics": ["Topic Name 1", "Topic Name 2"],
  "people": [
    {{"name": "Person Name", "context": "how they relate to this conversation"}}
  ],
  "open_questions": ["question that remained unresolved"],
  "actionable_items": ["any action items identified"]
}}"""


def compress_messages(messages: list[dict], max_chars: int = 8000) -> str:
    """Compress conversation messages for the density scoring pass."""
    lines = []
    total = 0
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        # Truncate long messages
        if len(content) > 500:
            content = content[:500] + "..."
        line = f"[{role}]: {content}"
        if total + len(line) > max_chars:
            lines.append("... (conversation truncated)")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def full_messages_text(messages: list[dict], max_chars: int = 30000) -> str:
    """Format full conversation messages for extraction."""
    lines = []
    total = 0
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        line = f"[{role}]: {content}"
        if total + len(line) > max_chars:
            lines.append("... (conversation truncated)")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


class ChatExtractor:
    """LLM-powered chat extraction pipeline."""

    def __init__(self, config: dict):
        self.config = config
        self.client = anthropic.Anthropic(api_key=config["anthropic_api_key"])
        self.model = config.get("llm_model", "claude-sonnet-4-20250514")
        self.temperature = config.get("llm_temperature", 0.2)
        self.max_tokens = config.get("llm_max_tokens", 4000)
        self.min_density = config.get("chat_min_density", 3)

    def _call_llm(self, prompt: str) -> str:
        """Make an Anthropic API call with retry logic."""
        max_retries = 5
        for attempt in range(max_retries + 1):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
                if attempt == max_retries:
                    raise
                if isinstance(e, anthropic.APIStatusError) and e.status_code not in (429, 500, 502, 503, 529):
                    raise
                delay = 2 ** attempt
                print(f"    API error, retrying in {delay}s...")
                time.sleep(delay)
        raise RuntimeError("Unreachable")

    def score_density(self, conversation: dict) -> dict:
        """Score a conversation's knowledge density (cheap, fast pass)."""
        compressed = compress_messages(conversation.get("messages", []))
        prompt = DENSITY_SCORING_PROMPT.format(
            title=conversation.get("title", "Untitled"),
            source=conversation.get("source", "unknown"),
            messages=compressed,
        )

        response_text = self._call_llm(prompt)

        # Parse JSON from response
        try:
            # Handle markdown code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]
            return json.loads(response_text.strip())
        except (json.JSONDecodeError, IndexError):
            return {"density": 2, "topics": [], "people": [], "decisions": [], "brief_summary": ""}

    def extract_knowledge(self, conversation: dict, vault_index: dict) -> dict:
        """Full knowledge extraction pass for high-density conversations."""
        messages_text = full_messages_text(conversation.get("messages", []))
        existing_topics = ", ".join(vault_index.get("notes", {}).get("topics", []))

        prompt = EXTRACTION_PROMPT.format(
            title=conversation.get("title", "Untitled"),
            source=conversation.get("source", "unknown"),
            date=conversation.get("created_at", ""),
            messages=messages_text,
            existing_topics=existing_topics or "(none yet)",
        )

        response_text = self._call_llm(prompt)

        try:
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]
            return json.loads(response_text.strip())
        except (json.JSONDecodeError, IndexError):
            return {
                "title": conversation.get("title", "Untitled"),
                "summary": "",
                "key_conclusions": [],
                "decisions": [],
                "topics": [],
                "people": [],
                "open_questions": [],
                "actionable_items": [],
            }

    def write_insight_note(
        self,
        conversation: dict,
        density_result: dict,
        extraction: dict,
        vault_path: str,
    ) -> str:
        """Write an Insight note to the vault. Returns the filepath written."""
        source = conversation.get("source", "unknown")
        conv_id = conversation.get("id", "unknown")
        date = conversation.get("created_at", "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        title = extraction.get("title", conversation.get("title", "Untitled"))
        safe_title = sanitize_filename(title)

        # Build YAML frontmatter
        topics_yaml = format_wikilinks(extraction.get("topics", []))
        people_yaml = "\n".join(
            f'  - "[[{p["name"] if isinstance(p, dict) else p}]]"'
            for p in extraction.get("people", [])
        ) if extraction.get("people") else ""

        frontmatter = f"""---
type: insight
source: {source}
source_id: {conv_id}
date: {date}
density: {density_result.get('density', 0)}
topics:
{topics_yaml}
people:
{people_yaml}
status: active
---"""

        # Build body
        body_parts = [f"# {title}", ""]

        summary = extraction.get("summary", "")
        if summary:
            body_parts.extend(["## Summary", "", summary, ""])

        conclusions = extraction.get("key_conclusions", [])
        if conclusions:
            body_parts.append("## Key Conclusions")
            body_parts.append("")
            for c in conclusions:
                body_parts.append(f"- {c}")
            body_parts.append("")

        decisions = extraction.get("decisions", [])
        if decisions:
            body_parts.append("## Decisions Made")
            body_parts.append("")
            for d in decisions:
                if isinstance(d, dict):
                    body_parts.append(f"- **{d.get('decision', '')}**: {d.get('reasoning', '')}")
                else:
                    body_parts.append(f"- {d}")
            body_parts.append("")

        questions = extraction.get("open_questions", [])
        if questions:
            body_parts.append("## Open Questions")
            body_parts.append("")
            for q in questions:
                body_parts.append(f"- {q}")
            body_parts.append("")

        actions = extraction.get("actionable_items", [])
        if actions:
            body_parts.append("## Action Items")
            body_parts.append("")
            for a in actions:
                body_parts.append(f"- [ ] {a}")
            body_parts.append("")

        content = frontmatter + "\n\n" + "\n".join(body_parts)

        # Write to vault
        folder = os.path.join(vault_path, "Insights", source)
        os.makedirs(folder, exist_ok=True)
        filepath = os.path.join(folder, f"{safe_title}.md")
        atomic_write(filepath, content)

        return filepath


def process_conversations(
    conversations: list[dict],
    config: dict,
    db: ImportQueueDB,
    vault_path: str,
    source_name: str,
) -> dict:
    """
    Process a list of conversations through the extraction pipeline.

    1. Queue all conversations
    2. Score density for each
    3. Extract knowledge for high-density ones
    4. Write insight notes to vault

    Returns summary dict.
    """
    if not conversations:
        return {"total": 0, "scored": 0, "extracted": 0, "written": 0}

    min_messages = config.get("chat_min_messages", 5)
    min_density = config.get("chat_min_density", 3)
    batch_size = config.get("batch_size", 20)
    inter_item_delay = config.get("inter_item_delay", 1)

    extractor = ChatExtractor(config)
    vault_index = load_vault_index(vault_path)
    ensure_vault_folders(vault_path)

    # Queue conversations
    for conv in conversations:
        msg_count = len(conv.get("messages", []))
        if msg_count < min_messages:
            continue
        db.add_item(
            source=source_name,
            source_id=conv.get("id", ""),
            metadata=json.dumps({
                "title": conv.get("title", ""),
                "message_count": msg_count,
            }),
        )

    # Process pending items
    pending = db.get_pending(source=source_name, limit=batch_size)
    if not pending:
        print(f"  No pending {source_name} conversations to process.")
        return {"total": len(conversations), "scored": 0, "extracted": 0, "written": 0}

    # Build lookup of conversations by ID
    conv_map = {conv.get("id", ""): conv for conv in conversations}

    scored = 0
    extracted = 0
    written = 0

    for i, item in enumerate(pending):
        conv_id = item["source_id"]
        conv = conv_map.get(conv_id)
        if not conv:
            db.mark_skipped(item["id"])
            continue

        db.mark_processing(item["id"])
        print(f"  [{i+1}/{len(pending)}] Scoring: {conv.get('title', conv_id)[:60]}")

        try:
            # Step 1: Density scoring
            density_result = extractor.score_density(conv)
            db.add_anthropic_call()
            scored += 1

            density = density_result.get("density", 0)
            print(f"    Density: {density}/5 — {density_result.get('brief_summary', '')[:80]}")

            if density < min_density:
                print(f"    Skipping (below threshold {min_density})")
                db.mark_complete(item["id"])
                db.add_item_processed()
                continue

            # Step 2: Full extraction
            print(f"    Extracting knowledge...")
            extraction = extractor.extract_knowledge(conv, vault_index)
            db.add_anthropic_call()
            extracted += 1

            # Step 3: Write insight note
            filepath = extractor.write_insight_note(conv, density_result, extraction, vault_path)
            print(f"    Written: {os.path.basename(filepath)}")
            written += 1

            db.mark_complete(item["id"])
            db.add_item_processed()

            # Rate limiting
            if inter_item_delay > 0 and i < len(pending) - 1:
                time.sleep(inter_item_delay)

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            print(f"    FAILED: {error_msg}")
            db.mark_failed(item["id"], error_msg[:500])

    return {
        "total": len(conversations),
        "scored": scored,
        "extracted": extracted,
        "written": written,
    }

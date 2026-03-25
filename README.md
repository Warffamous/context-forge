# Context Forge

Data sovereignty tool that extracts, triages, and distills knowledge from platform-locked data (Google Takeout, ChatGPT exports, Grok exports) into portable Obsidian-compatible markdown files.

Designed to integrate with an existing [Second Brain](https://github.com/Warffamous/2ndbrain) Obsidian vault.

## Architecture

The system has two programs that run in sequence:

### Program 1: Scanner (`scan.py`)
Fast, local-only, no API calls. Reads unzipped Takeout folders, ChatGPT JSON, and Grok exports. Generates a `scan-report.md` triage report.

```bash
python scan.py --takeout ~/Takeout-account1 --takeout ~/Takeout-account2
python scan.py --takeout ~/Takeout --chatgpt ~/conversations.json
```

### Program 2: Importer (`import.py`)
Slower, uses Anthropic API, resumable via SQLite queue. Processes selected data through appropriate pipelines and outputs Obsidian-compatible markdown.

```bash
python import.py --youtube-history    # Feed YouTube watch history into 2ndbrain queue
python import.py --youtube-liked      # Import liked videos (priority)
python import.py --youtube-subs       # Import subscriptions to watch list
python import.py --gemini             # Extract knowledge from Gemini conversations
python import.py --chatgpt            # Extract knowledge from ChatGPT conversations
python import.py --grok               # Extract knowledge from Grok conversations
python import.py --bookmarks          # Import Chrome bookmarks
python import.py --status             # Show import queue status
python import.py --resume             # Resume interrupted import
```

## Setup

1. Clone this repo alongside your 2ndbrain vault
2. Copy `config.example.yaml` to `config.yaml` and fill in paths/keys
3. Install dependencies: `pip install -r requirements.txt`
4. Unzip your Google Takeout exports
5. Run the scanner first: `python scan.py --takeout /path/to/Takeout`
6. Review `scan-report.md`, then run the importer for desired data types

## Data Sources

| Priority | Data Type | Source | Output |
|----------|-----------|--------|--------|
| HIGH | YouTube watch history | Google Takeout | 2ndbrain ingest queue |
| HIGH | YouTube liked videos | Google Takeout | Priority ingest queue |
| HIGH | YouTube subscriptions | Google Takeout | 2ndbrain watch list |
| HIGH | Gemini conversations | Google Takeout | Insight notes + topics |
| HIGH | ChatGPT conversations | OpenAI export | Insight notes + topics |
| MEDIUM | Chrome bookmarks | Google Takeout | Reference notes |
| MEDIUM | Google Search history | Google Takeout | Interest mapping |
| LOW | Grok conversations | X/Grok export | Insight notes |

## Vault Output Structure

All output integrates with the existing 2ndbrain vault:

```
Knowledge-Web/
  Insights/           # NEW - context-forge output
    gemini/
    chatgpt/
    grok/
  Archive/            # NEW - compressed topic indexes
  Bookmarks/          # NEW - bookmark reference notes
  _system/
    import-queue.db   # NEW - context-forge queue
```

## Requirements

- Python 3.12+
- Anthropic API key (for chat extraction)
- Existing 2ndbrain vault (for integration)

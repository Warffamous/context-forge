"""Configuration loader for Context Forge."""

import os
import sys

import yaml


DEFAULT_CONFIG = {
    "vault_path": "",
    "anthropic_api_key": "",
    "llm_model": "claude-sonnet-4-20250514",
    "llm_temperature": 0.2,
    "llm_max_tokens": 4000,
    "takeout_dirs": [],
    "chatgpt_export": None,
    "grok_export": None,
    "gemini_dirs": [],
    "youtube_min_watch_seconds": 30,
    "chat_min_messages": 5,
    "chat_min_density": 3,
    "batch_size": 20,
    "inter_item_delay": 1,
    "max_retry_count": 3,
    "secondbrain_queue_db": "",
}


def find_config_path() -> str:
    """Find config.yaml in the script directory or current directory."""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml"),
        os.path.join(os.getcwd(), "config.yaml"),
    ]
    for path in candidates:
        resolved = os.path.normpath(path)
        if os.path.exists(resolved):
            return resolved
    return os.path.normpath(candidates[0])


def load_config(config_path: str | None = None) -> dict:
    """Load configuration from YAML file, merged with defaults."""
    if config_path is None:
        config_path = find_config_path()

    config = dict(DEFAULT_CONFIG)

    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config.update(user_config)

    return config


def validate_config(config: dict, require_api_key: bool = False) -> list[str]:
    """Validate configuration. Returns list of error messages (empty = valid)."""
    errors = []

    if require_api_key and not config.get("anthropic_api_key"):
        errors.append("anthropic_api_key is required for import operations")

    vault_path = config.get("vault_path", "")
    if vault_path and not os.path.isdir(vault_path):
        errors.append(f"vault_path does not exist: {vault_path}")

    return errors

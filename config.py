"""Configuration management for EPUB Translator.

Handles environment variables, API key rotation settings, and CLI arguments.
Supports multiple Gemini API keys for round-robin rotation and automatic fallback
when hitting rate limits (HTTP 429).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


def mask_key(key: str) -> str:
    """Safely mask an API key for logs and messages."""
    if not key:
        return "<empty>"
    clean = key.strip()
    if len(clean) <= 8:
        return "***"
    return f"{clean[:4]}...{clean[-4:]}"


def parse_api_keys(
    cli_keys: Optional[List[str]] = None,
    env_keys_str: Optional[str] = None,
    single_env_key: Optional[str] = None,
) -> List[str]:
    """Parse and collect unique, non-empty API keys from CLI and environment.

    Supports comma/space separated lists in GEMINI_API_KEYS and single GEMINI_API_KEY.
    """
    keys: List[str] = []

    if cli_keys:
        for item in cli_keys:
            for sub in item.replace(",", " ").split():
                clean = sub.strip()
                if clean and clean not in keys:
                    keys.append(clean)

    env_multi = env_keys_str or os.getenv("GEMINI_API_KEYS", "")
    if env_multi:
        for item in env_multi.replace(",", " ").split():
            clean = item.strip()
            if clean and clean not in keys:
                keys.append(clean)

    env_single = single_env_key or os.getenv("GEMINI_API_KEY", "")
    if env_single:
        for item in env_single.replace(",", " ").split():
            clean = item.strip()
            if clean and clean not in keys:
                keys.append(clean)

    return keys


@dataclass
class Config:
    """Runtime configuration for EPUB translation."""

    api_keys: List[str] = field(default_factory=list)
    model: str = "gemini-2.5-flash"
    batch_size: int = 20
    max_batch_chars: int = 3500
    source_lang: str = "en"
    target_lang: str = "id"
    style: str = "natural"
    request_timeout: float = 60.0
    max_retries_per_key: int = 3
    key_cooldown_seconds: float = 60.0
    checkpoint_dir: Path = field(default_factory=lambda: Path(".epub_translate_cache"))
    rotate_strategy: str = "round_robin"  # 'round_robin' or 'fallback_on_limit'
    translate_metadata: bool = False
    dry_run: bool = False
    verbose: bool = False

    @classmethod
    def from_env(cls, **overrides) -> Config:
        """Create config loading from environment and applying overrides."""
        keys = parse_api_keys(
            cli_keys=overrides.get("api_keys"),
        )
        model = (
            overrides.get("model")
            or os.getenv("GEMINI_MODEL")
            or "gemini-2.5-flash"
        )
        batch_size = int(
            overrides.get("batch_size")
            or os.getenv("BATCH_SIZE")
            or 20
        )
        timeout = float(
            overrides.get("request_timeout")
            or os.getenv("REQUEST_TIMEOUT")
            or 60.0
        )

        cfg = cls(
            api_keys=keys,
            model=model,
            batch_size=batch_size,
            request_timeout=timeout,
        )

        for k, v in overrides.items():
            if v is not None and hasattr(cfg, k):
                setattr(cfg, k, v)

        return cfg

    def masked_keys_summary(self) -> str:
        """Return a safe summary of available API keys."""
        if not self.api_keys:
            return "No API keys configured"
        return f"{len(self.api_keys)} key(s): " + ", ".join(mask_key(k) for k in self.api_keys)

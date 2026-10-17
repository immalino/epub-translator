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

    provider: str = "ollama"  # 'ollama' or 'gemini'
    ollama_base_url: str = "http://localhost:11434"
    model: str = "translategemma:4b"
    batch_size: int = 5
    max_batch_chars: int = 3500
    source_lang: str = "en"
    target_lang: str = "id"
    style: str = "natural"
    request_timeout: float = 120.0
    input_dir: Path = field(default_factory=lambda: Path("input"))
    output_dir: Path = field(default_factory=lambda: Path("output"))
    api_keys: List[str] = field(default_factory=list)
    max_retries: int = 5
    max_retries_per_key: int = 3
    key_cooldown_seconds: float = 60.0
    checkpoint_dir: Path = field(default_factory=lambda: Path(".epub_translate_cache"))
    rotate_strategy: str = "round_robin"  # 'round_robin' or 'fallback_on_limit'
    translate_metadata: bool = False
    dry_run: bool = False
    verbose: bool = False

    def __post_init__(self) -> None:
        self.input_dir = Path(self.input_dir)
        self.output_dir = Path(self.output_dir)
        self.checkpoint_dir = Path(self.checkpoint_dir)

    @classmethod
    def from_env(cls, **overrides) -> Config:
        """Create config loading from environment and applying overrides."""
        keys = parse_api_keys(
            cli_keys=overrides.get("api_keys"),
        )
        provider = overrides.get("provider")
        if not provider:
            if overrides.get("api_keys"):
                provider = "gemini"
            else:
                provider = (
                    os.getenv("TRANSLATION_PROVIDER")
                    or os.getenv("PROVIDER")
                    or "ollama"
                )

        ollama_base_url = (
            overrides.get("ollama_base_url")
            or os.getenv("OLLAMA_BASE_URL")
            or "http://localhost:11434"
        )
        default_model = "gemini-2.5-flash" if provider == "gemini" else "translategemma:4b"
        model = (
            overrides.get("model")
            or (os.getenv("GEMINI_MODEL") if provider == "gemini" else (os.getenv("OLLAMA_MODEL") or os.getenv("MODEL")))
            or default_model
        )
        default_batch_size = 20 if provider == "gemini" else 5
        batch_size = int(
            overrides.get("batch_size")
            or os.getenv("BATCH_SIZE")
            or default_batch_size
        )
        default_timeout = 60.0 if provider == "gemini" else 120.0
        timeout = float(
            overrides.get("request_timeout")
            or overrides.get("timeout")
            or os.getenv("REQUEST_TIMEOUT")
            or default_timeout
        )
        max_retries = int(
            overrides.get("max_retries")
            or os.getenv("MAX_RETRIES")
            or 5
        )
        input_dir = Path(
            overrides.get("input_dir")
            or os.getenv("INPUT_DIR")
            or "input"
        )
        output_dir = Path(
            overrides.get("output_dir")
            or os.getenv("OUTPUT_DIR")
            or "output"
        )

        cfg = cls(
            provider=provider,
            ollama_base_url=ollama_base_url,
            api_keys=keys,
            model=model,
            batch_size=batch_size,
            request_timeout=timeout,
            max_retries=max_retries,
            input_dir=input_dir,
            output_dir=output_dir,
        )

        for k, v in overrides.items():
            if v is not None and hasattr(cfg, k):
                if k in ("input_dir", "output_dir", "checkpoint_dir"):
                    setattr(cfg, k, Path(v))
                else:
                    setattr(cfg, k, v)

        return cfg

    def masked_keys_summary(self) -> str:
        """Return a safe summary of available API keys."""
        if not self.api_keys:
            return "No API keys configured"
        return f"{len(self.api_keys)} key(s): " + ", ".join(mask_key(k) for k in self.api_keys)


"""Configuration management for EPUB Translator.

Handles environment variables, API key rotation settings, and CLI arguments.
Supports multiple Gemini API keys for round-robin rotation and automatic fallback
when hitting rate limits (HTTP 429).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# Load .env file only when running as source script (not frozen in PyInstaller)
if not getattr(sys, "frozen", False):
    load_dotenv()


def is_directory_writable(dir_path: Path | str) -> bool:
    """Test if a directory is writable by attempting to create a temporary test file."""
    try:
        p = Path(dir_path)
        p.mkdir(parents=True, exist_ok=True)
        test_file = p / f".write_test_{os.getpid()}"
        test_file.touch()
        test_file.unlink()
        return True
    except (PermissionError, OSError):
        return False


def get_user_data_dir() -> Path:
    """Get the user-writable data directory for EPUB Translator."""
    appdata = (
        os.getenv("LOCALAPPDATA")
        or os.getenv("APPDATA")
        or os.getenv("XDG_DATA_HOME")
        or (Path.home() / ".local" / "share")
    )
    user_dir = Path(appdata) / "EPUBTranslator"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def get_user_documents_dir() -> Path:
    """Get the user-writable documents directory for output."""
    docs = Path.home() / "Documents" / "EPUBTranslator"
    try:
        docs.mkdir(parents=True, exist_ok=True)
        return docs
    except (PermissionError, OSError):
        user_dir = get_user_data_dir() / "output"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir


def get_default_checkpoint_dir() -> Path:
    """Return default checkpoint directory, falling back to user data dir if CWD is read-only."""
    cwd_cache = Path(".epub_translate_cache")
    if is_directory_writable(Path.cwd()):
        return cwd_cache
    cache_dir = get_user_data_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_default_output_dir() -> Path:
    """Return default output directory, falling back to Documents if CWD is read-only."""
    cwd_out = Path("output")
    if is_directory_writable(Path.cwd()):
        return cwd_out
    out_dir = get_user_documents_dir() / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def get_config_path() -> Path:
    """Return the active configuration path (config.json).

    If running frozen (PyInstaller executable):
    - Checks next to the executable (portable mode if writable).
    - Falls back to user AppData / home directory if the executable dir is read-only (e.g. Program Files).
    When running from source / dev:
    - Uses config.json in the current working directory if writable, else user data dir.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        exe_config = exe_dir / "config.json"
        if exe_config.exists():
            return exe_config
        if is_directory_writable(exe_dir):
            return exe_config
        return get_user_data_dir() / "config.json"

    if is_directory_writable(Path.cwd()):
        return Path("config.json")
    return get_user_data_dir() / "config.json"


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

    provider: str = "gemini"  # 'gemini' or 'ollama'
    model: str = "gemini-2.5-flash"
    batch_size: int = 20
    max_batch_chars: int = 3500
    source_lang: str = "en"
    target_lang: str = "id"
    style: str = "natural"
    request_timeout: float = 60.0
    input_dir: Path = field(default_factory=lambda: Path("input"))
    output_dir: Path = field(default_factory=get_default_output_dir)
    ollama_base_url: str = "http://localhost:11434"
    api_keys: List[str] = field(default_factory=list)
    max_retries: int = 5
    max_retries_per_key: int = 3
    key_cooldown_seconds: float = 60.0
    checkpoint_dir: Path = field(default_factory=get_default_checkpoint_dir)
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
        provider = (
            overrides.get("provider")
            or os.getenv("TRANSLATION_PROVIDER")
            or os.getenv("PROVIDER")
            or "gemini"
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

    @classmethod
    def load(cls, file_path: Optional[Path | str] = None, **overrides) -> Config:
        """Load configuration for GUI / Desktop.

        Loads settings from config.json. If config.json does not exist,
        starts completely clean/empty (kosongan) with default settings
        and NO API keys (does not take from .env or os.environ).
        """
        config_file = Path(file_path) if file_path else get_config_path()
        json_data: dict = {}
        if config_file.is_file():
            try:
                import json
                with open(config_file, "r", encoding="utf-8") as f:
                    json_data = json.load(f)
            except Exception:
                json_data = {}

        # Resolve output_dir safely (fallback if directory is not writable)
        raw_output = json_data.get("output_dir")
        if raw_output:
            out_p = Path(raw_output)
            if not is_directory_writable(out_p if out_p.is_absolute() else Path.cwd()):
                out_p = get_default_output_dir()
        else:
            out_p = get_default_output_dir()

        # Resolve checkpoint_dir safely (fallback if directory is not writable)
        raw_checkpoint = json_data.get("checkpoint_dir")
        if raw_checkpoint:
            cp_p = Path(raw_checkpoint)
            if not is_directory_writable(cp_p if cp_p.is_absolute() else Path.cwd()):
                cp_p = get_default_checkpoint_dir()
        else:
            cp_p = get_default_checkpoint_dir()

        cfg = cls(
            provider=json_data.get("provider", "gemini"),
            model=json_data.get("model", "gemini-2.5-flash"),
            batch_size=int(json_data.get("batch_size", 20)),
            max_batch_chars=int(json_data.get("max_batch_chars", 3500)),
            source_lang=json_data.get("source_lang", "en"),
            target_lang=json_data.get("target_lang", "id"),
            style=json_data.get("style", "natural"),
            request_timeout=float(json_data.get("request_timeout", 60.0)),
            input_dir=Path(json_data.get("input_dir", "input")),
            output_dir=out_p,
            ollama_base_url=json_data.get("ollama_base_url", "http://localhost:11434"),
            api_keys=list(json_data.get("api_keys", [])),
            max_retries=int(json_data.get("max_retries", 5)),
            max_retries_per_key=int(json_data.get("max_retries_per_key", 3)),
            key_cooldown_seconds=float(json_data.get("key_cooldown_seconds", 60.0)),
            checkpoint_dir=cp_p,
            rotate_strategy=json_data.get("rotate_strategy", "round_robin"),
            translate_metadata=bool(json_data.get("translate_metadata", False)),
            dry_run=bool(json_data.get("dry_run", False)),
            verbose=bool(json_data.get("verbose", False)),
        )

        for k, v in overrides.items():
            if v is not None and hasattr(cfg, k):
                if k in ("input_dir", "output_dir", "checkpoint_dir"):
                    setattr(cfg, k, Path(v))
                else:
                    setattr(cfg, k, v)

        return cfg

    def save(self, file_path: Optional[Path | str] = None) -> bool:
        """Persist configuration directly to config.json."""
        import json
        path = Path(file_path) if file_path else get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "provider": self.provider,
            "model": self.model,
            "api_keys": self.api_keys,
            "batch_size": self.batch_size,
            "max_batch_chars": self.max_batch_chars,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "style": self.style,
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
            "max_retries_per_key": self.max_retries_per_key,
            "key_cooldown_seconds": self.key_cooldown_seconds,
            "rotate_strategy": self.rotate_strategy,
            "ollama_base_url": self.ollama_base_url,
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
            "checkpoint_dir": str(self.checkpoint_dir),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True

    def masked_keys_summary(self) -> str:
        """Return a safe summary of available API keys."""
        if not self.api_keys:
            return "No API keys configured"
        return f"{len(self.api_keys)} key(s): " + ", ".join(mask_key(k) for k in self.api_keys)


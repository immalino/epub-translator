"""Glossary management for novel terminology and character consistency.

Loads glossary definitions from JSON files and formats them into
system instructions for Gemini, ensuring consistent translation of names,
honorifics, places, and terms across the entire book.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional


class Glossary:
    """Manages translation terms, character names, and style notes."""

    def __init__(
        self,
        terms: Optional[Dict[str, str]] = None,
        notes: Optional[str] = None,
        source_path: Optional[Path] = None,
    ) -> None:
        self.terms: Dict[str, str] = terms or {}
        self.notes: str = notes or ""
        self.source_path: Optional[Path] = source_path
        self._content_hash: Optional[str] = None

    @classmethod
    def load(cls, path: str | Path) -> Glossary:
        """Load a glossary from a JSON file."""
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError(f"Glossary file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        terms: Dict[str, str] = {}
        notes: str = ""

        if isinstance(data, dict):
            if "terms" in data and isinstance(data["terms"], dict):
                terms = {str(k): str(v) for k, v in data["terms"].items()}
                notes = str(data.get("notes", ""))
            else:
                # Direct key-value mapping
                for k, v in data.items():
                    if k != "notes" and isinstance(v, (str, int, float)):
                        terms[str(k)] = str(v)
                    elif k == "notes" and isinstance(v, str):
                        notes = v
        elif isinstance(data, list):
            # List of objects [{"source": "...", "target": "..."}, ...]
            for item in data:
                if isinstance(item, dict):
                    src = item.get("source") or item.get("from") or item.get("en")
                    tgt = item.get("target") or item.get("to") or item.get("id")
                    if src and tgt:
                        terms[str(src)] = str(tgt)

        glossary = cls(terms=terms, notes=notes, source_path=file_path)
        return glossary

    @property
    def hash(self) -> str:
        """Deterministic SHA-256 hash of glossary content for checkpoint tracking."""
        if self._content_hash is None:
            sorted_terms = sorted(self.terms.items())
            payload = json.dumps({"terms": sorted_terms, "notes": self.notes}, sort_keys=True)
            self._content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return self._content_hash

    def format_for_prompt(self) -> str:
        """Generate prompt text representing glossary rules."""
        if not self.terms and not self.notes:
            return ""

        lines = ["\n[PANDUAN GLOSARIUM & KONSISTENSI ISTILAH]"]
        if self.terms:
            lines.append("Harap terjemahkan istilah/nama berikut persis sesuai padanan ini:")
            for src, tgt in sorted(self.terms.items()):
                lines.append(f"- {src} => {tgt}")

        if self.notes:
            lines.append(f"\nCatatan Tambahan Gaya & Terjemahan:\n{self.notes.strip()}")

        return "\n".join(lines) + "\n"

    def __len__(self) -> int:
        return len(self.terms)

    def __repr__(self) -> str:
        return f"Glossary(terms={len(self.terms)}, hash={self.hash})"

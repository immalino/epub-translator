"""Checkpoint and progress recovery management.

Tracks translation status per document and batch using content hashes.
Allows interrupted translation jobs to be safely resumed (--resume)
or failed batches to be retried (--retry-failed) without re-translating
already completed sections.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BatchRecord:
    """Record of a single batch translation status."""

    batch_id: str
    item_ids: List[str]
    source_hash: str
    status: str  # "PENDING", "IN_PROGRESS", "COMPLETED", "FAILED"
    translated_texts: Dict[str, str] = field(default_factory=dict)
    error_message: Optional[str] = field(default=None)


@dataclass
class ChapterRecord:
    """Record of an EPUB chapter/document translation status."""

    href: str
    title: str
    total_segments: int
    status: str  # "PENDING", "IN_PROGRESS", "COMPLETED", "FAILED"
    batches: Dict[str, BatchRecord] = field(default_factory=dict)
    error_message: Optional[str] = field(default=None)


class CheckpointManager:
    """Manages persistent checkpoint storage in JSON files."""

    def __init__(
        self,
        epub_hash: str,
        model: str,
        glossary_hash: str,
        checkpoint_dir: Path | str = ".epub_translate_cache",
    ) -> None:
        self.epub_hash = epub_hash
        self.model = model
        self.glossary_hash = glossary_hash
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self.session_id = f"{epub_hash}_{model}_{glossary_hash}"
        self.file_path = self.checkpoint_dir / f"{self.session_id}.json"
        self.chapters: Dict[str, ChapterRecord] = {}
        self._load()

    @classmethod
    def compute_file_hash(cls, file_path: str | Path) -> str:
        """Compute SHA-256 hash of a file for checkpoint keying."""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()[:16]

    @classmethod
    def compute_content_hash(cls, content: str | bytes) -> str:
        """Compute SHA-256 hash of string or bytes content."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()[:16]

    def _load(self) -> None:
        """Load checkpoint file if it exists."""
        if not self.file_path.exists():
            return

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            chapters_data = data.get("chapters", {})
            for href, ch_info in chapters_data.items():
                batches = {}
                for b_id, b_info in ch_info.get("batches", {}).items():
                    batches[b_id] = BatchRecord(
                        batch_id=b_info["batch_id"],
                        item_ids=b_info.get("item_ids", []),
                        source_hash=b_info.get("source_hash", ""),
                        status=b_info.get("status", "PENDING"),
                        translated_texts=b_info.get("translated_texts", {}),
                        error_message=b_info.get("error_message"),
                    )
                self.chapters[href] = ChapterRecord(
                    href=ch_info["href"],
                    title=ch_info.get("title", ""),
                    total_segments=ch_info.get("total_segments", 0),
                    status=ch_info.get("status", "PENDING"),
                    batches=batches,
                    error_message=ch_info.get("error_message"),
                )
            logger.info("Loaded checkpoint from %s with %d chapters", self.file_path, len(self.chapters))
        except Exception as e:
            logger.warning("Failed to load checkpoint file %s: %s", self.file_path, e)

    def save(self) -> None:
        """Atomically persist current state to disk."""
        data = {
            "epub_hash": self.epub_hash,
            "model": self.model,
            "glossary_hash": self.glossary_hash,
            "chapters": {href: asdict(ch) for href, ch in self.chapters.items()},
        }
        temp_path = self.file_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.file_path)
        except Exception as e:
            logger.error("Failed to save checkpoint to %s: %s", self.file_path, e)
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def register_chapter(self, href: str, title: str, total_segments: int) -> ChapterRecord:
        """Register or retrieve an existing chapter."""
        if href not in self.chapters:
            self.chapters[href] = ChapterRecord(
                href=href,
                title=title,
                total_segments=total_segments,
                status="PENDING",
            )
            self.save()
        return self.chapters[href]

    def is_batch_completed(self, href: str, batch_id: str, source_hash: str) -> bool:
        """Check if a specific batch has already been successfully translated and matches source."""
        ch = self.chapters.get(href)
        if not ch:
            return False
        b = ch.batches.get(batch_id)
        if not b:
            return False
        return b.status == "COMPLETED" and b.source_hash == source_hash and len(b.translated_texts) == len(b.item_ids)

    def get_batch_translations(self, href: str, batch_id: str) -> Optional[Dict[str, str]]:
        """Retrieve cached translations for a batch if completed."""
        ch = self.chapters.get(href)
        if not ch:
            return None
        b = ch.batches.get(batch_id)
        if b and b.status == "COMPLETED":
            return b.translated_texts
        return None

    def record_batch_success(
        self,
        href: str,
        batch_id: str,
        item_ids: List[str],
        source_hash: str,
        translations: Dict[str, str],
    ) -> None:
        """Record successful translation of a batch."""
        ch = self.chapters.setdefault(
            href, ChapterRecord(href=href, title="", total_segments=0, status="IN_PROGRESS")
        )
        ch.batches[batch_id] = BatchRecord(
            batch_id=batch_id,
            item_ids=item_ids,
            source_hash=source_hash,
            status="COMPLETED",
            translated_texts=translations,
            error_message=None,
        )
        ch.status = "IN_PROGRESS"
        self.save()

    def record_batch_failure(
        self,
        href: str,
        batch_id: str,
        item_ids: List[str],
        source_hash: str,
        error_msg: str,
    ) -> None:
        """Record batch failure."""
        ch = self.chapters.setdefault(
            href, ChapterRecord(href=href, title="", total_segments=0, status="FAILED")
        )
        ch.batches[batch_id] = BatchRecord(
            batch_id=batch_id,
            item_ids=item_ids,
            source_hash=source_hash,
            status="FAILED",
            translated_texts={},
            error_message=error_msg,
        )
        ch.status = "FAILED"
        ch.error_message = f"Batch {batch_id} failed: {error_msg}"
        self.save()

    def mark_chapter_completed(self, href: str) -> None:
        """Mark chapter as fully completed."""
        if href in self.chapters:
            self.chapters[href].status = "COMPLETED"
            self.chapters[href].error_message = None
            self.save()

    def get_summary(self) -> Dict[str, Any]:
        """Return statistics on progress."""
        total_ch = len(self.chapters)
        completed_ch = sum(1 for ch in self.chapters.values() if ch.status == "COMPLETED")
        failed_ch = sum(1 for ch in self.chapters.values() if ch.status == "FAILED")

        total_batches = 0
        completed_batches = 0
        failed_batches = 0

        for ch in self.chapters.values():
            total_batches += len(ch.batches)
            completed_batches += sum(1 for b in ch.batches.values() if b.status == "COMPLETED")
            failed_batches += sum(1 for b in ch.batches.values() if b.status == "FAILED")

        return {
            "total_chapters": total_ch,
            "completed_chapters": completed_ch,
            "failed_chapters": failed_ch,
            "total_batches": total_batches,
            "completed_batches": completed_batches,
            "failed_batches": failed_batches,
        }

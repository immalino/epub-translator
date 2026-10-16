"""Tests for checkpoint saving, loading, hashing, resume, and retry."""

from pathlib import Path
import pytest
from checkpoint import CheckpointManager


def test_checkpoint_lifecycle(tmp_path: Path):
    cp = CheckpointManager(
        epub_hash="abc12345",
        model="gemini-2.5-flash",
        glossary_hash="glosshash01",
        checkpoint_dir=tmp_path,
    )

    # Register chapter
    ch = cp.register_chapter("OEBPS/ch1.xhtml", "Chapter 1", total_segments=5)
    assert ch.status == "PENDING"

    # Record batch success
    batch_id = "b001"
    items = ["s0001", "s0002"]
    src_hash = "batch_hash_1"
    translations = {"s0001": "Halo dunia", "s0002": "Selamat pagi"}

    cp.record_batch_success("OEBPS/ch1.xhtml", batch_id, items, src_hash, translations)
    assert cp.is_batch_completed("OEBPS/ch1.xhtml", batch_id, src_hash)

    cached = cp.get_batch_translations("OEBPS/ch1.xhtml", batch_id)
    assert cached == translations

    # Reload checkpoint in a fresh instance
    cp_reloaded = CheckpointManager(
        epub_hash="abc12345",
        model="gemini-2.5-flash",
        glossary_hash="glosshash01",
        checkpoint_dir=tmp_path,
    )
    assert cp_reloaded.is_batch_completed("OEBPS/ch1.xhtml", batch_id, src_hash)
    assert cp_reloaded.get_batch_translations("OEBPS/ch1.xhtml", batch_id) == translations


def test_checkpoint_failure_and_retry(tmp_path: Path):
    cp = CheckpointManager(
        epub_hash="hash999",
        model="gemini-2.5-flash",
        glossary_hash="none",
        checkpoint_dir=tmp_path,
    )

    cp.record_batch_failure(
        "OEBPS/ch2.xhtml",
        "b001",
        ["s0001"],
        "src_hash",
        "Network timeout",
    )

    summary = cp.get_summary()
    assert summary["failed_chapters"] == 1
    assert summary["failed_batches"] == 1
    assert not cp.is_batch_completed("OEBPS/ch2.xhtml", "b001", "src_hash")


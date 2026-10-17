"""Unit tests for TranslationRunner and TranslationCallback in runner.py."""

from pathlib import Path
from config import Config
from runner import TranslationRunner, TranslationCallback

FIXTURE_EPUB = Path(__file__).parent / "fixtures" / "sample_novel.epub"


def test_inspect_epub():
    info = TranslationRunner.inspect_epub(FIXTURE_EPUB)
    assert "title" in info
    assert info["title"] == "The Chronicles of Finch"
    assert info["spine_count"] >= 3
    assert len(info["chapters"]) == info["spine_count"]

    first_ch = info["chapters"][0]
    assert "index" in first_ch
    assert "zip_path" in first_ch
    assert first_ch["segment_count"] > 0
    assert first_ch["char_count"] > 0


def test_get_dry_run_stats():
    config = Config.from_env(provider="ollama", model="translategemma:4b")
    stats = TranslationRunner.get_dry_run_stats(FIXTURE_EPUB, config=config)

    assert stats["book_title"] == "The Chronicles of Finch"
    assert stats["total_segments"] > 0
    assert stats["approx_words"] > 0
    assert stats["batches_count"] > 0
    assert stats["remaining_batches"] > 0
    assert stats["provider"] == "ollama"


def test_get_bilingual_preview():
    info = TranslationRunner.inspect_epub(FIXTURE_EPUB)
    first_zip_path = info["chapters"][0]["zip_path"]

    preview = TranslationRunner.get_bilingual_preview(
        FIXTURE_EPUB,
        first_zip_path,
        config=Config.from_env(provider="ollama", model="translategemma:4b"),
    )
    assert len(preview) > 0
    assert "source" in preview[0]
    assert "translated" in preview[0]
    assert preview[0]["source"] is not None


def test_get_bilingual_preview_with_cached_translations(tmp_path):
    from checkpoint import CheckpointManager
    config = Config.from_env(checkpoint_dir=tmp_path)
    epub_hash = CheckpointManager.compute_file_hash(FIXTURE_EPUB)
    cp = CheckpointManager(epub_hash=epub_hash, model=config.model, glossary_hash="none", checkpoint_dir=tmp_path)

    info = TranslationRunner.inspect_epub(FIXTURE_EPUB)
    zip_path = info["chapters"][0]["zip_path"]

    # Register batch with translations
    cp.register_chapter(zip_path, "Chap 1", 5)
    cp.record_batch_success(
        href=zip_path,
        batch_id="b001",
        item_ids=["s0001"],
        source_hash="testhash",
        translations={"s0001": "Terjemahan uji coba"},
    )

    pairs = TranslationRunner.get_bilingual_preview(
        FIXTURE_EPUB,
        zip_path,
        config=config,
    )
    assert len(pairs) > 0
    assert pairs[0]["translated"] == "Terjemahan uji coba"
    assert pairs[0]["is_translated"] is True

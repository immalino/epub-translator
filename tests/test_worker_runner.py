"""Tests for QtTranslationCallback, TranslationWorker, and cooperative pause/cancel in TranslationRunner."""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QCoreApplication

from config import Config
from gui.worker import QtTranslationCallback, TranslationWorker
from runner import TranslationRunner
from tests.create_fixture import create_fixture_epub

FIXTURE_EPUB = Path(__file__).parent / "fixtures" / "sample_novel.epub"


@pytest.fixture(scope="session")
def qapp():
    """Ensure a QCoreApplication instance exists for Qt signals/threads."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_qt_translation_callback_signals(qapp):
    """Verify that QtTranslationCallback emits all appropriate Qt signals."""
    cb = QtTranslationCallback()

    logs = []
    overalls = []
    batches = []
    chapter_statuses = []
    quotas = []
    completed = []
    errors = []

    cb.sig_log.connect(lambda lvl, msg: logs.append((lvl, msg)))
    cb.sig_overall_progress.connect(lambda frac, text: overalls.append((frac, text)))
    cb.sig_batch_progress.connect(lambda frac, text: batches.append((frac, text)))
    cb.sig_chapter_status.connect(lambda idx, st: chapter_statuses.append((idx, st)))
    cb.sig_quota_warning.connect(lambda msg: quotas.append(msg))
    cb.sig_completed.connect(lambda p, el, rep: completed.append((p, el, rep)))
    cb.sig_error.connect(lambda msg: errors.append(msg))

    # Test logs and errors
    cb.on_log("INFO", "Starting engine")
    assert len(logs) == 1
    assert logs[0] == ("INFO", "Starting engine")
    assert len(errors) == 0

    cb.on_log("ERROR", "Something broke")
    assert len(logs) == 2
    assert len(errors) == 1
    assert errors[0] == "Something broke"

    # Test on_start
    cb.on_start(total_chapters=2, total_chars=500, total_segments=10, target_spine=[])
    assert len(overalls) >= 1
    assert overalls[-1][0] == 0.0

    # Test on_chapter_start
    cb.on_chapter_start(chapter_idx=1, chapter_title="Chapter 1", total_batches=2)
    assert chapter_statuses[-1] == (1, "Memproses")
    assert batches[-1][0] == 0.0

    # Test on_batch_complete
    cb.on_batch_complete(chapter_idx=1, batch_idx=1, total_batches=2, translated_count=5, is_cache=False)
    assert batches[-1][0] == 0.5
    assert "Batch 1/2 (API)" in batches[-1][1]

    # Test on_chapter_complete
    cb.on_chapter_complete(chapter_idx=1, chapter_title="Chapter 1")
    assert chapter_statuses[-1] == (1, "Selesai")

    # Test on_chapter_failed
    cb.on_chapter_failed(chapter_idx=2, chapter_title="Chapter 2", error_message="Network error")
    assert chapter_statuses[-1] == (2, "Gagal")
    assert any("Chapter 2" in err for err in errors)

    # Test quota warning
    cb.on_quota_warning("Quota exhausted", None)
    assert quotas[-1] == "Quota exhausted"

    # Test completion
    dummy_out = Path("/tmp/out.epub")
    cb.on_complete(dummy_out, 42.0, None)
    assert len(completed) == 1
    assert completed[0][0] == str(dummy_out)
    assert completed[0][1] == 42.0
    assert overalls[-1][0] == 1.0


def test_translation_worker_pause_resume_methods(qapp):
    """Verify pause, resume, cancel, and is_paused states on TranslationWorker."""
    worker = TranslationWorker()

    assert not worker.is_paused()
    assert not worker._pause_event.is_set()
    assert not worker._cancel_event.is_set()

    worker.pause()
    assert worker.is_paused()
    assert worker._pause_event.is_set()

    worker.resume()
    assert not worker.is_paused()
    assert not worker._pause_event.is_set()

    worker.cancel()
    assert worker._cancel_event.is_set()


def test_runner_cancellation_cooperative(tmp_path):
    """Verify TranslationRunner exits cleanly with return code 3 when cancel_event is set."""
    src_epub = tmp_path / "test.epub"
    out_epub = tmp_path / "test_out.epub"
    create_fixture_epub(src_epub)

    config = Config.from_env(
        provider="ollama",
        model="translategemma:4b",
        checkpoint_dir=tmp_path / "cache",
    )

    cancel_event = threading.Event()
    cancel_event.set()  # Cancel immediately before processing

    with patch("runner.OllamaTranslator.check_connection", return_value=True):
        exit_code = TranslationRunner.run_translation(
            input_path=src_epub,
            output_path=out_epub,
            config=config,
            cancel_event=cancel_event,
        )

    assert exit_code == 3
    # Output epub shouldn't be finalized because translation was cancelled
    assert not out_epub.exists()


def test_runner_pause_and_resume_cooperative(tmp_path):
    """Verify TranslationRunner pauses and then resumes when pause_event is manipulated."""
    src_epub = tmp_path / "test_pause.epub"
    out_epub = tmp_path / "test_pause_out.epub"
    create_fixture_epub(src_epub)

    config = Config.from_env(
        provider="gemini",
        api_keys=["dummy_key"],
        checkpoint_dir=tmp_path / "cache",
    )

    pause_event = threading.Event()
    cancel_event = threading.Event()

    # Pre-pause the runner
    pause_event.set()

    def delayed_resume():
        time.sleep(0.3)
        pause_event.clear()

    resume_thread = threading.Thread(target=delayed_resume)
    resume_thread.start()

    with patch("runner.GeminiTranslator") as mock_gemini_cls, \
         patch("runner.EPUBValidator"):
        mock_translator = MagicMock()
        mock_gemini_cls.return_value = mock_translator
        # Mock translate_batch returning translations
        mock_translator.create_batches.side_effect = lambda segs: [segs]
        mock_translator.translate_batch.side_effect = lambda batch: {s.id: "Halo" for s in batch}

        exit_code = TranslationRunner.run_translation(
            input_path=src_epub,
            output_path=out_epub,
            config=config,
            chapter_filter="1",  # Only 1 chapter for quick test
            pause_event=pause_event,
            cancel_event=cancel_event,
        )

    resume_thread.join()
    assert exit_code == 0
    assert out_epub.exists()


def test_translation_worker_thread_execution(tmp_path, qapp):
    """Verify TranslationWorker runs on a separate QThread and forwards signals."""
    src_epub = tmp_path / "worker_test.epub"
    out_epub = tmp_path / "worker_test_out.epub"
    create_fixture_epub(src_epub)

    config = Config.from_env(
        provider="gemini",
        api_keys=["dummy_key"],
        checkpoint_dir=tmp_path / "cache",
    )

    worker = TranslationWorker()
    emitted_logs = []
    emitted_statuses = []
    worker.sig_log.connect(lambda lvl, msg: emitted_logs.append((lvl, msg)))
    worker.sig_chapter_status.connect(lambda idx, st: emitted_statuses.append((idx, st)))

    with patch("runner.GeminiTranslator") as mock_gemini_cls, \
         patch("runner.EPUBValidator"):
        mock_translator = MagicMock()
        mock_gemini_cls.return_value = mock_translator
        mock_translator.create_batches.side_effect = lambda segs: [segs]
        mock_translator.translate_batch.side_effect = lambda batch: {s.id: "Diterjemahkan" for s in batch}

        worker.start_translation(
            input_path=src_epub,
            output_path=out_epub,
            config=config,
            chapter_filter="1",
        )

        # Wait up to 5 seconds for thread to finish
        finished = worker.wait(5000)
        assert finished, "Worker thread timed out"
        qapp.processEvents()
        assert worker.exit_code == 0
        assert len(emitted_logs) > 0
        assert len(emitted_statuses) > 0
        assert out_epub.exists()


def test_translation_worker_cancellation(tmp_path, qapp):
    """Verify TranslationWorker can be cancelled while running."""
    src_epub = tmp_path / "worker_cancel.epub"
    out_epub = tmp_path / "worker_cancel_out.epub"
    create_fixture_epub(src_epub)

    config = Config.from_env(
        provider="gemini",
        api_keys=["dummy_key"],
        checkpoint_dir=tmp_path / "cache",
    )

    worker = TranslationWorker(
        input_path=src_epub,
        output_path=out_epub,
        config=config,
    )

    # Cancel before starting
    worker.cancel()
    worker.start()

    finished = worker.wait(5000)
    assert finished, "Worker thread timed out"
    assert worker.exit_code == 3

"""Worker and Qt Signal Bridge for Translation Runner.

Provides QtTranslationCallback and TranslationWorker (QThread) to support
non-blocking execution, cooperative pause/resume, and safe cancellation.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from config import Config
from glossary import Glossary
from runner import TranslationCallback, TranslationRunner

logger = logging.getLogger("epub_translate.gui.worker")


class QtTranslationCallback(QObject, TranslationCallback):
    """Bridge TranslationCallback events into PySide6 Qt Signals."""

    # Qt Signals
    sig_log = Signal(str, str)  # (level, message)
    sig_overall_progress = Signal(float, str)  # (fraction 0.0 - 1.0, message)
    sig_batch_progress = Signal(float, str)  # (fraction 0.0 - 1.0, message)
    sig_chapter_status = Signal(int, str)  # (chapter_index, status_text)
    sig_quota_warning = Signal(str)  # (error_message)
    sig_completed = Signal(str, float, object)  # (output_path, elapsed_seconds, report)
    sig_error = Signal(str)  # (error_message)

    # Aliases
    log = sig_log
    overall_progress = sig_overall_progress
    batch_progress = sig_batch_progress
    chapter_status = sig_chapter_status
    quota_warning = sig_quota_warning
    completed = sig_completed
    error = sig_error

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.total_chapters: int = 0
        self.current_chapter_idx: int = 0
        self.total_batches_current_chapter: int = 0

    def on_log(self, level: str, message: str) -> None:
        self.sig_log.emit(level, message)
        if level.upper() == "ERROR":
            self.sig_error.emit(message)

    def on_start(
        self,
        total_chapters: int,
        total_chars: int,
        total_segments: int,
        target_spine: List[Any],
    ) -> None:
        self.total_chapters = total_chapters
        self.current_chapter_idx = 0
        self.sig_overall_progress.emit(
            0.0,
            f"Memulai penerjemahan ({total_chapters} bab, {total_segments} segmen)...",
        )

    def on_chapter_start(
        self,
        chapter_idx: int,
        chapter_title: str,
        total_batches: int,
    ) -> None:
        self.current_chapter_idx = chapter_idx
        self.total_batches_current_chapter = total_batches
        self.sig_chapter_status.emit(chapter_idx, "Memproses")

        overall_frac = (chapter_idx - 1) / max(1, self.total_chapters) if self.total_chapters > 0 else 0.0
        self.sig_overall_progress.emit(
            overall_frac,
            f"Memproses {chapter_title} (0/{total_batches} batch)...",
        )
        self.sig_batch_progress.emit(0.0, f"Batch 0/{total_batches}")

    def on_batch_complete(
        self,
        chapter_idx: int,
        batch_idx: int,
        total_batches: int,
        translated_count: int,
        is_cache: bool = False,
    ) -> None:
        batch_frac = batch_idx / max(1, total_batches) if total_batches > 0 else 1.0
        source_label = "cache" if is_cache else "API"

        if self.total_chapters > 0 and total_batches > 0:
            overall_frac = ((chapter_idx - 1) + (batch_idx / total_batches)) / self.total_chapters
        else:
            overall_frac = 0.0

        self.sig_batch_progress.emit(
            batch_frac,
            f"Batch {batch_idx}/{total_batches} ({source_label})",
        )
        self.sig_overall_progress.emit(
            overall_frac,
            f"Bab {chapter_idx}/{self.total_chapters} - Batch {batch_idx}/{total_batches}",
        )

    def on_chapter_complete(
        self,
        chapter_idx: int,
        chapter_title: str,
    ) -> None:
        self.sig_chapter_status.emit(chapter_idx, "Selesai")
        overall_frac = chapter_idx / max(1, self.total_chapters) if self.total_chapters > 0 else 1.0
        self.sig_overall_progress.emit(overall_frac, f"Selesai {chapter_title}")
        self.sig_batch_progress.emit(1.0, f"Selesai {chapter_title}")

    def on_chapter_failed(
        self,
        chapter_idx: int,
        chapter_title: str,
        error_message: str,
    ) -> None:
        self.sig_chapter_status.emit(chapter_idx, "Gagal")
        self.sig_error.emit(f"Bab {chapter_idx} ({chapter_title}) gagal: {error_message}")

    def on_quota_warning(
        self,
        error: Any,
        checkpoint: Any,
    ) -> None:
        self.sig_quota_warning.emit(str(error))

    def on_complete(
        self,
        output_path: Path,
        elapsed_seconds: float,
        validation_report: Optional[Any] = None,
    ) -> None:
        self.sig_overall_progress.emit(1.0, "Penerjemahan selesai.")
        self.sig_completed.emit(
            str(output_path) if output_path else "",
            elapsed_seconds,
            validation_report,
        )


class TranslationWorker(QThread):
    """Worker thread running TranslationRunner with cooperative interrupt support."""

    # Sinyal yang diteruskan ke caller/GUI
    sig_log = Signal(str, str)
    sig_overall_progress = Signal(float, str)
    sig_batch_progress = Signal(float, str)
    sig_chapter_status = Signal(int, str)
    sig_quota_warning = Signal(str)
    sig_completed = Signal(str, float, object)
    sig_error = Signal(str)

    # Aliases
    log = sig_log
    overall_progress = sig_overall_progress
    batch_progress = sig_batch_progress
    chapter_status = sig_chapter_status
    quota_warning = sig_quota_warning
    completed = sig_completed
    error = sig_error

    def __init__(
        self,
        input_path: Optional[Path] = None,
        output_path: Optional[Path] = None,
        config: Optional[Config] = None,
        chapter_filter: Optional[str] = None,
        resume: bool = True,
        retry_failed: bool = False,
        glossary: Optional[Glossary] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.input_path: Optional[Path] = Path(input_path) if input_path else None
        self.output_path: Optional[Path] = Path(output_path) if output_path else None
        self.config: Optional[Config] = config
        self.chapter_filter: Optional[str] = chapter_filter
        self.resume_flag: bool = resume
        self.retry_failed: bool = retry_failed
        self.glossary: Optional[Glossary] = glossary

        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()
        self.exit_code: Optional[int] = None

        self.callback = QtTranslationCallback()
        self._connect_callback_signals()

    def _connect_callback_signals(self) -> None:
        self.callback.sig_log.connect(self.sig_log.emit)
        self.callback.sig_overall_progress.connect(self.sig_overall_progress.emit)
        self.callback.sig_batch_progress.connect(self.sig_batch_progress.emit)
        self.callback.sig_chapter_status.connect(self.sig_chapter_status.emit)
        self.callback.sig_quota_warning.connect(self.sig_quota_warning.emit)
        self.callback.sig_completed.connect(self.sig_completed.emit)
        self.callback.sig_error.connect(self.sig_error.emit)

    def start_translation(
        self,
        input_path: Path,
        output_path: Path,
        config: Config,
        chapter_filter: Optional[str] = None,
        resume: bool = True,
        retry_failed: bool = False,
        glossary: Optional[Glossary] = None,
    ) -> None:
        """Configure translation task and start worker thread."""
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.config = config
        self.chapter_filter = chapter_filter
        self.resume_flag = resume
        self.retry_failed = retry_failed
        self.glossary = glossary

        self._pause_event.clear()
        self._cancel_event.clear()
        self.exit_code = None
        self.start()

    def pause(self) -> None:
        """Pause the translation process."""
        self._pause_event.set()

    def resume(self) -> None:
        """Resume the translation process."""
        self._pause_event.clear()

    def cancel(self) -> None:
        """Signal translation process to stop gracefully."""
        self._cancel_event.set()

    def is_paused(self) -> bool:
        """Return True if the worker is currently paused."""
        return self._pause_event.is_set()

    def run(self) -> None:
        """Thread entrypoint executing TranslationRunner.run_translation."""
        if not self.input_path or not self.output_path or not self.config:
            err_msg = "Parameter input_path, output_path, atau config belum diset."
            self.sig_error.emit(err_msg)
            self.exit_code = 1
            return

        try:
            self.exit_code = TranslationRunner.run_translation(
                input_path=self.input_path,
                output_path=self.output_path,
                config=self.config,
                chapter_filter=self.chapter_filter,
                resume=self.resume_flag,
                retry_failed=self.retry_failed,
                glossary=self.glossary,
                callback=self.callback,
                pause_event=self._pause_event,
                cancel_event=self._cancel_event,
            )
        except Exception as exc:
            logger.exception("Kesalahan tak terduga dalam TranslationWorker: %s", exc)
            self.sig_error.emit(str(exc))
            self.exit_code = 1


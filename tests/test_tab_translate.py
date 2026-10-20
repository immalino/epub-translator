"""Unit tests for TabTranslate (Tab 1) and MainWindow translation integration."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from config import Config
from gui.main_window import MainWindow
from gui.tab_translate import DryRunDialog, TabTranslate

os.environ["QT_QPA_PLATFORM"] = "offscreen"

FIXTURE_EPUB = Path(__file__).parent / "fixtures" / "sample_novel.epub"


@pytest.fixture(scope="session")
def qapp():
    """Ensure a single QApplication instance exists for GUI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_tab_translate_initial_state(qapp):
    """Test initial state of TabTranslate before any book is loaded."""
    tab = TabTranslate()

    assert tab.label_title.text() == "Belum Ada Buku Dimuat"
    assert tab.label_creator.text() == "Pengarang: -"
    assert tab.label_language.text() == "Bahasa Sumber: -"
    assert tab.label_summary.text() == "Total: 0 Bab • 0 Segmen • 0 Karakter"
    assert tab.table_chapters.rowCount() == 0
    assert not tab.btn_dry_run.isEnabled()
    assert tab.progress_overall.value() == 0
    assert tab.progress_batch.value() == 0
    assert tab.log_console.toPlainText() == ""


def test_tab_translate_load_fixture_epub(qapp):
    """Test loading sample_novel.epub into TabTranslate."""
    tab = TabTranslate()

    book_loaded_events = []
    tab.sig_book_loaded.connect(lambda info: book_loaded_events.append(info))

    tab.load_epub(FIXTURE_EPUB)

    assert len(book_loaded_events) == 1
    assert tab.current_epub_path == FIXTURE_EPUB
    assert "The Chronicles of Finch" in tab.label_title.text()
    assert "Arthur Pendelton" in tab.label_creator.text()
    assert "en" in tab.label_language.text()
    assert "3 Bab" in tab.label_summary.text()
    assert "13 Segmen" in tab.label_summary.text()
    assert tab.btn_dry_run.isEnabled()

    # Table verification
    assert tab.table_chapters.rowCount() == 3

    # Chapter 1
    chk_0 = tab.table_chapters.item(0, 0)
    assert chk_0.checkState() == Qt.Checked
    assert tab.table_chapters.item(0, 1).text() == "1"
    assert tab.table_chapters.item(0, 2).text() == "chap1.xhtml"
    assert tab.table_chapters.item(0, 3).text() == "6"
    assert tab.table_chapters.item(0, 4).text() == "569"
    assert tab.table_chapters.item(0, 5).text() == "Belum"

    # Chapter 2
    assert tab.table_chapters.item(1, 1).text() == "2"
    assert tab.table_chapters.item(1, 2).text() == "chap2.xhtml"
    assert tab.table_chapters.item(1, 3).text() == "4"
    assert tab.table_chapters.item(1, 4).text() == "454"

    # Chapter 3
    assert tab.table_chapters.item(2, 1).text() == "3"
    assert tab.table_chapters.item(2, 2).text() == "chap3.xhtml"
    assert tab.table_chapters.item(2, 3).text() == "3"
    assert tab.table_chapters.item(2, 4).text() == "330"

    assert tab.label_selection_summary.text() == "3 dari 3 bab dipilih"
    assert tab.get_selected_chapter_indices() == [1, 2, 3]
    # None means all chapters selected
    assert tab.get_selected_chapters_filter() is None


def test_tab_translate_selection_controls(qapp):
    """Test Select All, Deselect All, and chapter filter generation."""
    tab = TabTranslate()
    tab.load_epub(FIXTURE_EPUB)

    # Deselect All
    tab.deselect_all_chapters()
    assert tab.get_selected_chapter_indices() == []
    assert tab.get_selected_chapters_filter() == ""
    assert tab.label_selection_summary.text() == "0 dari 3 bab dipilih"

    # Check that checkboxes are unchecked
    for r in range(3):
        assert tab.table_chapters.item(r, 0).checkState() == Qt.Unchecked

    # Select All
    tab.select_all_chapters()
    assert tab.get_selected_chapter_indices() == [1, 2, 3]
    assert tab.get_selected_chapters_filter() is None
    assert tab.label_selection_summary.text() == "3 dari 3 bab dipilih"

    # Manually uncheck Chapter 2 (row 1)
    tab.table_chapters.item(1, 0).setCheckState(Qt.Unchecked)
    assert tab.get_selected_chapter_indices() == [1, 3]
    assert tab.get_selected_chapters_filter() == "1,3"
    assert tab.label_selection_summary.text() == "2 dari 3 bab dipilih"


def test_tab_translate_worker_signals_update_ui(qapp):
    """Test that progress bars, chapter statuses, and logs update correctly."""
    tab = TabTranslate()
    tab.load_epub(FIXTURE_EPUB)

    # 1. Overall Progress
    tab.update_overall_progress(0.65, "Memproses Bab 2 (65%)...")
    assert tab.progress_overall.value() == 65
    assert tab.label_overall_percent.text() == "65%"
    assert tab.label_overall_status.text() == "Memproses Bab 2 (65%)..."

    # 2. Batch Progress
    tab.update_batch_progress(0.40, "Batch 2/5 (API)")
    assert tab.progress_batch.value() == 40
    assert tab.label_batch_percent.text() == "40%"
    assert tab.label_batch_status.text() == "Batch 2/5 (API)"

    # 3. Chapter Statuses
    tab.update_chapter_status(1, "Selesai")
    assert tab.table_chapters.item(0, 5).text() == "Selesai"

    tab.update_chapter_status(2, "Memproses")
    assert tab.table_chapters.item(1, 5).text() == "Memproses"

    tab.update_chapter_status(3, "Gagal")
    assert tab.table_chapters.item(2, 5).text() == "Gagal"

    # 4. Console Log
    tab.append_log("INFO", "Proses terjemahan bab 1 berhasil.")
    tab.append_log("ERROR", "Koneksi terputus sesaat.")
    log_text = tab.log_console.toPlainText()
    assert "INFO" in log_text
    assert "Proses terjemahan bab 1 berhasil." in log_text
    assert "ERROR" in log_text
    assert "Koneksi terputus sesaat." in log_text

    # Clear log
    tab.clear_log()
    assert tab.log_console.toPlainText() == ""


def test_tab_translate_dry_run_dialog(qapp):
    """Test DryRunDialog initialization and stats rendering."""
    stats = {
        "book_title": "The Chronicles of Finch",
        "total_spine_chapters": 3,
        "target_chapters": 2,
        "total_segments": 10,
        "total_chars": 1023,
        "approx_words": 186,
        "approx_tokens": 247,
        "batches_count": 2,
        "completed_batches": 1,
        "remaining_batches": 1,
        "est_minutes": 0.1,
        "rpd_sufficient": True,
        "provider": "gemini",
        "model": "gemini-2.5-flash",
    }

    dialog = DryRunDialog(stats)
    assert dialog.windowTitle() == "Estimasi Biaya & Kuota API (Dry Run)"

    # Test show_dry_run_dialog with mocked exec
    tab = TabTranslate()
    tab.load_epub(FIXTURE_EPUB)

    with patch.object(DryRunDialog, "exec", return_value=0) as mock_exec:
        tab.show_dry_run_dialog(config=Config())
        mock_exec.assert_called_once()


def test_main_window_open_epub_action(qapp):
    """Test opening EPUB from MainWindow toolbar action."""
    window = MainWindow()

    with patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(FIXTURE_EPUB), "EPUB Files (*.epub)")):
        window.action_open.trigger()

    assert window.current_epub_path == FIXTURE_EPUB
    assert "The Chronicles of Finch" in window.tab_translate.label_title.text()
    assert window.action_start.isEnabled()
    assert window.action_dry_run.isEnabled()


def test_main_window_start_translation_flow(qapp, tmp_path):
    """Test start translation flow and worker signal connections in MainWindow."""
    window = MainWindow()
    window.output_directory = tmp_path
    window.load_epub(FIXTURE_EPUB)

    # Mock TranslationWorker so it doesn't do real network calls
    with patch("gui.main_window.TranslationWorker.start") as mock_worker_start:
        window.action_start.trigger()

        assert window.worker is not None
        mock_worker_start.assert_called_once()
        assert not window.action_start.isEnabled()
        assert window.action_pause.isEnabled()
        assert window.action_stop.isEnabled()

        # Emit test signals from worker callback to verify MainWindow / TabTranslate reaction
        window.worker.callback.sig_overall_progress.emit(0.75, "Hampir selesai")
        assert window.tab_translate.progress_overall.value() == 75
        assert window.tab_translate.label_overall_status.text() == "Hampir selesai"

        window.worker.callback.sig_chapter_status.emit(1, "Selesai")
        assert window.tab_translate.table_chapters.item(0, 5).text() == "Selesai"

        # Test pause / resume
        window.worker.is_paused = MagicMock(return_value=False)
        window.worker.pause = MagicMock()
        window.action_pause.trigger()
        window.worker.pause.assert_called_once()
        assert window.action_pause.text() == "Lanjut"

        window.worker.is_paused = MagicMock(return_value=True)
        window.worker.resume = MagicMock()
        window.action_pause.trigger()
        window.worker.resume.assert_called_once()
        assert window.action_pause.text() == "Jeda"

        # Test Stop action with confirmation
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            window.worker.isRunning = MagicMock(return_value=True)
            window.worker.cancel = MagicMock()
            window.action_stop.trigger()
            window.worker.cancel.assert_called_once()

        # Test worker finished resets toolbar
        window.worker.finished.emit()
        assert window.action_start.isEnabled()
        assert not window.action_pause.isEnabled()
        assert not window.action_stop.isEnabled()


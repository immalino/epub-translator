"""Unit tests for Calibre GUI Theme, Assets, and MainWindow."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QTabWidget, QToolBar

# Ensure offscreen Qt platform for headless Linux testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(scope="session")
def qapp():
    """Fixture ensuring a single QApplication instance exists for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_asset_icons(qapp):
    """Test that all required icon assets generate valid non-null QIcons."""
    from gui import assets

    icon_funcs = [
        assets.get_open_epub_icon,
        assets.get_start_icon,
        assets.get_pause_icon,
        assets.get_stop_icon,
        assets.get_dry_run_icon,
        assets.get_glossary_icon,
        assets.get_editor_icon,
        assets.get_settings_icon,
        assets.get_validate_icon,
        assets.get_output_folder_icon,
    ]

    for func in icon_funcs:
        icon = func()
        assert isinstance(icon, QIcon)
        assert not icon.isNull(), f"Icon from {func.__name__} should not be null."

    # Test unknown icon name fallback
    fallback_icon = assets.get_icon("non_existent_key")
    assert isinstance(fallback_icon, QIcon)
    assert fallback_icon.isNull()


def test_theme_application(qapp):
    """Test that Calibre stylesheet is applied to QApplication."""
    from gui.theme import CALIBRE_QSS, apply_calibre_theme

    assert "QToolBar" in CALIBRE_QSS
    assert "QTabWidget::pane" in CALIBRE_QSS
    assert "QTableWidget" in CALIBRE_QSS
    assert "QProgressBar" in CALIBRE_QSS
    assert "QStatusBar" in CALIBRE_QSS

    apply_calibre_theme(qapp)
    assert len(qapp.styleSheet()) > 0


def test_main_window_structure(qapp):
    """Test MainWindow initialization, toolbars, tabs, and statusbar."""
    from gui.main_window import MainWindow

    window = MainWindow()
    assert "EPUB Translator" in window.windowTitle()

    # Verify Toolbar
    toolbars = window.findChildren(QToolBar)
    assert len(toolbars) >= 1
    toolbar = toolbars[0]
    assert toolbar.toolButtonStyle() == Qt.ToolButtonTextUnderIcon

    action_texts = [action.text() for action in toolbar.actions() if action.text()]
    assert "Buka EPUB" in action_texts
    assert "Mulai Terjemah" in action_texts
    assert "Jeda / Lanjut" in action_texts
    assert "Stop" in action_texts
    assert "Estimasi Kuota" in action_texts
    assert "Folder Hasil" in action_texts

    # Verify Central QTabWidget and 5 tabs
    assert isinstance(window.centralWidget(), QTabWidget)
    assert window.tab_widget.count() == 5

    tab_labels = [window.tab_widget.tabText(i) for i in range(5)]
    assert "Penerjemahan" in tab_labels
    assert "Editor Bilingual" in tab_labels
    assert "Glosarium" in tab_labels
    assert "Pengaturan" in tab_labels
    assert "Validasi" in tab_labels

    # Verify StatusBar
    status_bar = window.statusBar()
    assert status_bar is not None
    assert window.status_engine_label is not None
    assert window.status_checkpoint_label is not None


def test_main_window_close_event_idle(qapp):
    """Test closeEvent accepts closing when no worker is running."""
    from gui.main_window import MainWindow

    window = MainWindow()
    window.worker = None

    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_main_window_close_event_worker_running_confirm_yes(qapp):
    """Test closeEvent cancels worker and accepts when user confirms exit."""
    from gui.main_window import MainWindow

    window = MainWindow()
    mock_worker = MagicMock()
    mock_worker.isRunning.return_value = True
    window.worker = mock_worker

    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        event = QCloseEvent()
        window.closeEvent(event)
        assert event.isAccepted()
        mock_worker.cancel.assert_called_once()
        mock_worker.wait.assert_called_once()


def test_main_window_close_event_worker_running_confirm_no(qapp):
    """Test closeEvent ignores closing when user declines exit during work."""
    from gui.main_window import MainWindow

    window = MainWindow()
    mock_worker = MagicMock()
    mock_worker.isRunning.return_value = True
    window.worker = mock_worker

    with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted()
        mock_worker.cancel.assert_not_called()


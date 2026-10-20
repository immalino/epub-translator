"""Main Application Window for EPUB Translator (Calibre Edition).

Features:
- Calibre-inspired action toolbar with prominent icon buttons
- 5 central feature tabs (Translation Monitor, Bilingual Editor, Glossary, Settings, Validation)
- Informative status bar with engine and checkpoint indicators
- Safe graceful exit handler warning when worker tasks are in progress
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from config import Config
from gui import assets
from gui.worker import TranslationWorker

logger = logging.getLogger("epub_translate.gui.main_window")


class PlaceholderTab(QWidget):
    """Temporary placeholder widget for tabs before their specific implementation."""

    def __init__(self, title: str, description: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        title_label = QLabel(title)
        title_font = title_label.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)

        desc_label = QLabel(description)
        desc_label.setStyleSheet("color: #64748b; font-size: 13px;")
        desc_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(title_label)
        layout.addWidget(desc_label)


class MainWindow(QMainWindow):
    """Calibre-inspired Main Window for EPUB Translator."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("EPUB Translator - Calibre Edition")
        self.resize(1150, 750)
        self.setMinimumSize(900, 600)

        # Active worker reference
        self.worker: Optional[TranslationWorker] = None
        self.current_epub_path: Optional[Path] = None
        self.output_directory: Path = Path("output")

        # UI Setup
        self._setup_toolbar()
        self._setup_central_tabs()
        self._setup_statusbar()

        logger.info("MainWindow initialized successfully.")

    def _setup_toolbar(self) -> None:
        """Create Calibre-style top action toolbar."""
        toolbar = QToolBar("Calibre Action Toolbar", self)
        toolbar.setObjectName("calibreToolBar")
        toolbar.setIconSize(QSize(28, 28))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        # 1. Buka EPUB
        self.action_open = QAction(assets.get_open_epub_icon(), "Buka EPUB", self)
        self.action_open.setShortcut(QKeySequence("Ctrl+O"))
        self.action_open.setStatusTip("Pilih dan buka file buku EPUB untuk diterjemahkan (Ctrl+O)")
        self.action_open.triggered.connect(self._on_open_epub)
        toolbar.addAction(self.action_open)

        toolbar.addSeparator()

        # 2. Mulai Terjemahkan
        self.action_start = QAction(assets.get_start_icon(), "Mulai Terjemah", self)
        self.action_start.setShortcut(QKeySequence("F5"))
        self.action_start.setStatusTip("Mulai proses penerjemahan buku (F5)")
        self.action_start.triggered.connect(self._on_start_translation)
        toolbar.addAction(self.action_start)

        # 3. Jeda / Lanjut
        self.action_pause = QAction(assets.get_pause_icon(), "Jeda / Lanjut", self)
        self.action_pause.setStatusTip("Jeda sementara atau lanjutkan proses penerjemahan")
        self.action_pause.setEnabled(False)
        self.action_pause.triggered.connect(self._on_pause_resume)
        toolbar.addAction(self.action_pause)

        # 4. Stop / Batal
        self.action_stop = QAction(assets.get_stop_icon(), "Stop", self)
        self.action_stop.setStatusTip("Hentikan dan batalkan penerjemahan buku")
        self.action_stop.setEnabled(False)
        self.action_stop.triggered.connect(self._on_stop_translation)
        toolbar.addAction(self.action_stop)

        toolbar.addSeparator()

        # 5. Estimasi (Dry Run)
        self.action_dry_run = QAction(assets.get_dry_run_icon(), "Estimasi Kuota", self)
        self.action_dry_run.setStatusTip("Hitung estimasi token, panggilan API, dan waktu tanpa memanggil AI")
        self.action_dry_run.triggered.connect(self._on_dry_run)
        toolbar.addAction(self.action_dry_run)

        # 6. Buka Folder Hasil
        self.action_open_output = QAction(assets.get_output_folder_icon(), "Folder Hasil", self)
        self.action_open_output.setStatusTip("Buka folder output file EPUB yang telah diterjemahkan")
        self.action_open_output.triggered.connect(self._on_open_output_folder)
        toolbar.addAction(self.action_open_output)

    def _setup_central_tabs(self) -> None:
        """Create central tab widget with 5 modular tabs."""
        self.tab_widget = QTabWidget(self)
        self.tab_widget.setObjectName("mainTabs")
        self.tab_widget.setIconSize(QSize(18, 18))

        # Tab 1: Penerjemahan & Monitor
        self.tab_translate = PlaceholderTab(
            "Penerjemahan & Monitor",
            "Panel monitor penerjemahan buku, pemilihan bab, dual progress bar, dan live console log.",
        )
        self.tab_widget.addTab(self.tab_translate, assets.get_open_epub_icon(), "Penerjemahan")

        # Tab 2: Editor Bilingual (Advanced Mode)
        self.tab_editor = PlaceholderTab(
            "Editor Bilingual (Calibre Advanced Mode)",
            "Tinjau dan perbaiki teks terjemahan berdampingan dengan teks asli sebelum finalisasi.",
        )
        self.tab_widget.addTab(self.tab_editor, assets.get_editor_icon(), "Editor Bilingual")

        # Tab 3: Glosarium Istilah
        self.tab_glossary = PlaceholderTab(
            "Glosarium Istilah & Karakter",
            "Kelola padanan kata khusus, nama tokoh, dan terminologi novel konsisten.",
        )
        self.tab_widget.addTab(self.tab_glossary, assets.get_glossary_icon(), "Glosarium")

        # Tab 4: Pengaturan Mesin & API
        self.tab_settings = PlaceholderTab(
            "Pengaturan Mesin & Konfigurasi API",
            "Atur model LLM (Gemini / Ollama), rotasi API Keys, rate limit, dan concurrency.",
        )
        self.tab_widget.addTab(self.tab_settings, assets.get_settings_icon(), "Pengaturan")

        # Tab 5: Validasi EPUB
        self.tab_validator = PlaceholderTab(
            "Validasi Standar EPUB",
            "Cek kepatuhan XHTML, integritas tautan, cover metadata, dan konsistensi file terjemahan.",
        )
        self.tab_widget.addTab(self.tab_validator, assets.get_validate_icon(), "Validasi")

        self.setCentralWidget(self.tab_widget)

    def _setup_statusbar(self) -> None:
        """Configure status bar with status text and system indicators."""
        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)

        # Permanent status widgets on the right
        self.status_engine_label = QLabel("Mesin: Gemini 2.5 Flash | API Keys: Siap")
        self.status_engine_label.setStyleSheet("padding: 0 8px; color: #334155;")
        status_bar.addPermanentWidget(self.status_engine_label)

        self.status_checkpoint_label = QLabel("💾 Checkpoint: Aktif")
        self.status_checkpoint_label.setStyleSheet("padding: 0 8px; color: #0284c7; font-weight: 500;")
        status_bar.addPermanentWidget(self.status_checkpoint_label)

        status_bar.showMessage("Siap")

    # =========================================================================
    # Toolbar Action Handlers (Placeholders to be wired in subsequent sessions)
    # =========================================================================

    def _on_open_epub(self) -> None:
        """Handler for Open EPUB action."""
        logger.info("Toolbar action: Buka EPUB triggered.")
        self.statusBar().showMessage("Membuka dialog pemilihan file EPUB...", 3000)

    def _on_start_translation(self) -> None:
        """Handler for Start Translation action."""
        logger.info("Toolbar action: Mulai Terjemahkan triggered.")
        self.statusBar().showMessage("Memulai proses penerjemahan...", 3000)

    def _on_pause_resume(self) -> None:
        """Handler for Pause / Resume action."""
        if not self.worker:
            return

        if self.worker.is_paused():
            self.worker.resume()
            self.action_pause.setText("Jeda")
            self.statusBar().showMessage("Penerjemahan dilanjutkan.")
        else:
            self.worker.pause()
            self.action_pause.setText("Lanjut")
            self.statusBar().showMessage("Penerjemahan dijeda.")

    def _on_stop_translation(self) -> None:
        """Handler for Stop action."""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Hentikan Penerjemahan",
                "Apakah Anda yakin ingin membatalkan proses penerjemahan?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.worker.cancel()
                self.statusBar().showMessage("Membatalkan penerjemahan...")

    def _on_dry_run(self) -> None:
        """Handler for Dry Run action."""
        logger.info("Toolbar action: Estimasi Kuota (Dry Run) triggered.")
        self.statusBar().showMessage("Melakukan estimasi kuota...", 3000)

    def _on_open_output_folder(self) -> None:
        """Open output directory in OS file manager."""
        folder = self.output_directory.resolve()
        folder.mkdir(parents=True, exist_ok=True)
        logger.info("Opening output directory: %s", folder)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        self.statusBar().showMessage(f"Membuka folder output: {folder.name}", 3000)

    # =========================================================================
    # Window Lifecycle & Close Confirmation
    # =========================================================================

    def closeEvent(self, event) -> None:
        """Confirm window exit if background translation task is active."""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Penerjemahan Sedang Berlangsung",
                "Penerjemahan buku sedang berjalan di latar belakang.\n"
                "Apakah Anda yakin ingin menghentikan tugas dan keluar dari aplikasi?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                logger.info("Application closing with active worker. Cancelling worker thread...")
                self.worker.cancel()
                self.worker.wait(2000)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


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
    QFileDialog,
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
from gui.tab_bilingual import TabBilingual
from gui.tab_glossary import TabGlossary
from gui.tab_settings import TabSettings
from gui.tab_translate import TabTranslate
from gui.tab_validator import TabValidator
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

        toolbar.addSeparator()

        # 7. Pengaturan
        self.action_settings = QAction(assets.get_settings_icon(), "Pengaturan", self)
        self.action_settings.setStatusTip("Buka tab pengaturan mesin penerjemah dan API Keys")
        self.action_settings.triggered.connect(lambda: self.tab_widget.setCurrentWidget(self.tab_settings))
        toolbar.addAction(self.action_settings)

    def _setup_central_tabs(self) -> None:
        """Create central tab widget with 5 modular tabs."""
        self.tab_widget = QTabWidget(self)
        self.tab_widget.setObjectName("mainTabs")
        self.tab_widget.setIconSize(QSize(18, 18))

        # Tab 1: Penerjemahan & Monitor
        self.tab_translate = TabTranslate(parent=self)
        self.tab_translate.sig_open_epub_requested.connect(self._on_open_epub)
        self.tab_translate.sig_dry_run_requested.connect(self._on_dry_run)
        self.tab_translate.sig_open_settings_requested.connect(
            lambda: self.tab_widget.setCurrentWidget(self.tab_settings)
        )
        self.tab_translate.sig_book_loaded.connect(self._on_book_loaded)
        self.tab_widget.addTab(self.tab_translate, assets.get_open_epub_icon(), "Penerjemahan")

        # Tab 2: Editor Bilingual (Advanced Mode)
        self.tab_bilingual = TabBilingual(parent=self)
        self.tab_editor = self.tab_bilingual  # Alias for backward compatibility
        self.tab_widget.addTab(self.tab_bilingual, assets.get_editor_icon(), "Editor Bilingual")

        # Tab 3: Glosarium Istilah
        self.tab_glossary = TabGlossary(parent=self)
        self.tab_widget.addTab(self.tab_glossary, assets.get_glossary_icon(), "Glosarium")

        # Tab 4: Pengaturan Mesin & API
        self.tab_settings = TabSettings(parent=self)
        self.tab_settings.sig_config_saved.connect(self._on_config_saved)
        self.tab_widget.addTab(self.tab_settings, assets.get_settings_icon(), "Pengaturan")

        # Tab 5: Validasi EPUB
        self.tab_validator = TabValidator(parent=self)
        self.tab_widget.addTab(self.tab_validator, assets.get_validate_icon(), "Validasi")

        self.setCentralWidget(self.tab_widget)

    def _setup_statusbar(self) -> None:
        """Configure status bar with status text and system indicators."""
        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)

        # Permanent status widgets on the right
        cfg = Config.load()
        if cfg.provider == "gemini":
            keys_info = f"{len(cfg.api_keys)} Kunci" if cfg.api_keys else "Siap"
            self.status_engine_label = QLabel(f"Mesin: {cfg.model} | API Keys: {keys_info}")
        else:
            self.status_engine_label = QLabel(f"Mesin: {cfg.model} (Ollama)")

        self.status_engine_label.setStyleSheet("padding: 0 8px; color: #334155;")
        status_bar.addPermanentWidget(self.status_engine_label)

        self.status_checkpoint_label = QLabel("💾 Checkpoint: Aktif")
        self.status_checkpoint_label.setStyleSheet("padding: 0 8px; color: #0284c7; font-weight: 500;")
        status_bar.addPermanentWidget(self.status_checkpoint_label)

        status_bar.showMessage("Siap")

    def _on_config_saved(self, config: Config) -> None:
        """Update status bar and tab views when settings are saved."""
        if config.provider == "gemini":
            keys_info = f"{len(config.api_keys)} Kunci" if config.api_keys else "Tanpa Kunci"
            self.status_engine_label.setText(f"Mesin: {config.model} | API Keys: {keys_info}")
        else:
            self.status_engine_label.setText(f"Mesin: {config.model} (Ollama)")
        self.tab_translate.update_engine_summary(config)
        self.statusBar().showMessage("Pengaturan berhasil diperbarui dan diterapkan.", 3000)

    # =========================================================================
    # Toolbar Action Handlers & EPUB Management
    # =========================================================================

    def load_epub(self, epub_path: Path) -> None:
        """Load and inspect EPUB file in TabTranslate."""
        try:
            self.current_epub_path = epub_path
            self.tab_translate.load_epub(epub_path)
            self.tab_bilingual.load_book(epub_path, self.tab_translate.current_book_info)
            self.setWindowTitle(f"EPUB Translator - {epub_path.name}")
            self.statusBar().showMessage(f"EPUB berhasil dimuat: {epub_path.name}", 4000)
            self.action_start.setEnabled(True)
            self.action_dry_run.setEnabled(True)
        except Exception as exc:
            logger.exception("Gagal membuka EPUB: %s", exc)
            QMessageBox.critical(self, "Kesalahan EPUB", f"Gagal membaca file EPUB:\n{exc}")

    def _on_book_loaded(self, info: dict) -> None:
        """Propagate loaded book information to dependent tabs."""
        if self.current_epub_path:
            self.tab_bilingual.load_book(self.current_epub_path, book_info=info)

    def _on_open_epub(self) -> None:
        """Handler for Open EPUB action."""
        logger.info("Toolbar action: Buka EPUB triggered.")
        default_dir = (
            str(self.current_epub_path.parent)
            if self.current_epub_path and self.current_epub_path.parent.exists()
            else str(Path.cwd())
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Pilih File EPUB",
            default_dir,
            "EPUB Files (*.epub);;All Files (*)",
        )
        if file_path:
            self.load_epub(Path(file_path))

    def _on_start_translation(self) -> None:
        """Handler for Start Translation action."""
        logger.info("Toolbar action: Mulai Terjemahkan triggered.")
        if not self.current_epub_path:
            QMessageBox.information(
                self,
                "Pilih Buku EPUB",
                "Silakan buka file EPUB terlebih dahulu sebelum memulai penerjemahan.",
            )
            return

        filter_str = self.tab_translate.get_selected_chapters_filter()
        if filter_str == "":
            QMessageBox.warning(
                self,
                "Pilih Bab",
                "Tidak ada bab yang dipilih. Silakan centang minimal satu bab pada tabel.",
            )
            return

        self.output_directory.mkdir(parents=True, exist_ok=True)
        stem = self.current_epub_path.stem
        output_file = self.output_directory / f"{stem}_id.epub"

        config = self.tab_settings.get_config()
        glossary = self.tab_glossary.get_glossary()
        glossary_to_pass = glossary if (len(glossary) > 0 or glossary.notes) else None
        self.tab_bilingual.glossary = glossary_to_pass

        logger.info(
            "Starting translation worker for %s -> %s (filter=%s, glossary_terms=%d)",
            self.current_epub_path,
            output_file,
            filter_str,
            len(glossary_to_pass.terms) if glossary_to_pass else 0,
        )
        self.worker = TranslationWorker(
            input_path=self.current_epub_path,
            output_path=output_file,
            config=config,
            chapter_filter=filter_str,
            resume=True,
            retry_failed=False,
            glossary=glossary_to_pass,
            parent=self,
        )

        # Connect signals
        self.worker.sig_log.connect(self.tab_translate.append_log)
        self.worker.sig_overall_progress.connect(self.tab_translate.update_overall_progress)
        self.worker.sig_batch_progress.connect(self.tab_translate.update_batch_progress)
        self.worker.sig_chapter_status.connect(self.tab_translate.update_chapter_status)
        self.worker.sig_quota_warning.connect(self._on_quota_warning)
        self.worker.sig_completed.connect(self._on_translation_completed)
        self.worker.sig_error.connect(self._on_translation_error)
        self.worker.finished.connect(self._on_worker_finished)

        # Toolbar UI State
        self.action_start.setEnabled(False)
        self.action_pause.setEnabled(True)
        self.action_pause.setText("Jeda")
        self.action_stop.setEnabled(True)
        self.action_open.setEnabled(False)
        self.action_dry_run.setEnabled(False)

        self.statusBar().showMessage(f"Menerjemahkan: {self.current_epub_path.name}...")
        self.worker.start()

    def _on_pause_resume(self) -> None:
        """Handler for Pause / Resume action."""
        if not self.worker:
            return

        if self.worker.is_paused():
            self.worker.resume()
            self.action_pause.setText("Jeda")
            self.statusBar().showMessage("Penerjemahan dilanjutkan.")
            self.tab_translate.append_log("INFO", "Proses penerjemahan dilanjutkan.")
        else:
            self.worker.pause()
            self.action_pause.setText("Lanjut")
            self.statusBar().showMessage("Penerjemahan dijeda.")
            self.tab_translate.append_log("INFO", "Proses penerjemahan dijeda sementara.")

    def _on_stop_translation(self) -> None:
        """Handler for Stop action."""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Hentikan Penerjemahan",
                "Apakah Anda yakin ingin membatalkan proses penerjemahan?\n"
                "Progres yang sudah selesai tetap aman tersimpan di checkpoint.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.worker.cancel()
                self.statusBar().showMessage("Membatalkan penerjemahan...")
                self.tab_translate.append_log("WARN", "Membatalkan proses penerjemahan...")

    def _on_dry_run(self) -> None:
        """Handler for Dry Run action."""
        logger.info("Toolbar action: Estimasi Kuota (Dry Run) triggered.")
        if not self.current_epub_path:
            QMessageBox.information(
                self,
                "Estimasi Kuota (Dry Run)",
                "Silakan buka file EPUB terlebih dahulu untuk melakukan estimasi kuota.",
            )
            return

        config = self.tab_settings.get_config()
        glossary = self.tab_glossary.get_glossary()
        glossary_to_pass = glossary if (len(glossary) > 0 or glossary.notes) else None
        self.tab_translate.current_glossary = glossary_to_pass
        self.tab_translate.show_dry_run_dialog(config=config)

    def _on_open_output_folder(self) -> None:
        """Open output directory in OS file manager."""
        folder = self.output_directory.resolve()
        folder.mkdir(parents=True, exist_ok=True)
        logger.info("Opening output directory: %s", folder)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        self.statusBar().showMessage(f"Membuka folder output: {folder.name}", 3000)

    # =========================================================================
    # Worker Signal Handlers
    # =========================================================================

    def _on_quota_warning(self, error_msg: str) -> None:
        """Handle quota warning from translation worker."""
        self.statusBar().showMessage("Peringatan kuota harian API tercapai!", 5000)
        QMessageBox.warning(
            self,
            "Batas Kuota API Tercapai",
            f"Proses terhenti karena kuota harian API habis:\n\n{error_msg}\n\n"
            "Progres telah tersimpan di checkpoint. Anda dapat melanjutkannya kembali.",
        )

    def _on_translation_completed(self, output_path: str, elapsed: float, report: Any) -> None:
        """Handle completion of translation task."""
        msg = f"Penerjemahan selesai dalam {elapsed:.1f} detik."
        self.statusBar().showMessage(msg, 5000)
        logger.info("Translation completed. Output: %s, Elapsed: %.1fs", output_path, elapsed)

        self.tab_validator.set_epub_path(output_path)
        reply = QMessageBox.question(
            self,
            "Penerjemahan Selesai",
            f"File EPUB berhasil diterjemahkan dalam {elapsed:.1f} detik!\n\n"
            f"Tersimpan di:\n{output_path}\n\n"
            "Apakah Anda ingin membuka Tab Validasi untuk memverifikasi dokumen ini?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self.tab_widget.setCurrentWidget(self.tab_validator)
            self.tab_validator.run_validation()

    def _on_translation_error(self, error_msg: str) -> None:
        """Handle translation error signal."""
        self.statusBar().showMessage(f"Error: {error_msg}", 5000)
        logger.error("Translation error: %s", error_msg)

    def _on_worker_finished(self) -> None:
        """Reset toolbar actions when worker thread finishes."""
        logger.info("Worker thread finished. Resetting action toolbar buttons.")
        self.action_start.setEnabled(True)
        self.action_pause.setEnabled(False)
        self.action_pause.setText("Jeda / Lanjut")
        self.action_stop.setEnabled(False)
        self.action_open.setEnabled(True)
        self.action_dry_run.setEnabled(True)

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


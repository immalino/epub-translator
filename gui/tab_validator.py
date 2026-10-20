"""Tab 5: EPUB Document Structure & Calibre Validator Widget.

Provides:
- EPUB file selector with auto-fill for latest translated output
- Execution of EPUBValidator (ZIP integrity, mimetype, XML/OPF, hyperlinks)
- Calibre CLI (ebook-validate) integration when installed
- Visual status cards (green/red badges) and detailed diagnostic logs
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from validator import EPUBValidator, ValidationReport

logger = logging.getLogger("epub_translate.gui.tab_validator")


class CheckCard(QFrame):
    """Card widget representing an individual validation checkpoint."""

    def __init__(self, title: str, description: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background-color: #f8fafc; border: 1px solid #cbd5e1; "
            "border-radius: 6px; padding: 6px 10px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        # Status Icon / Badge
        self.lbl_badge = QLabel("⚪")
        self.lbl_badge.setStyleSheet("font-size: 18px;")
        self.lbl_badge.setAlignment(Qt.AlignCenter)
        self.lbl_badge.setFixedWidth(30)
        layout.addWidget(self.lbl_badge)

        # Texts
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("font-weight: 600; font-size: 13px; color: #1e293b;")
        info_layout.addWidget(self.lbl_title)

        self.lbl_desc = QLabel(description)
        self.lbl_desc.setStyleSheet("color: #64748b; font-size: 11px;")
        self.lbl_desc.setWordWrap(True)
        info_layout.addWidget(self.lbl_desc)

        layout.addLayout(info_layout, stretch=1)

        # Status text
        self.lbl_status = QLabel("Belum Diuji")
        self.lbl_status.setStyleSheet("font-weight: 500; font-size: 12px; color: #64748b;")
        self.lbl_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.lbl_status)

    def set_status(self, passed: Optional[bool], status_text: str = "") -> None:
        """Update card visual state based on pass/fail."""
        if passed is True:
            self.lbl_badge.setText("✅")
            self.lbl_status.setText(status_text or "Lolos")
            self.lbl_status.setStyleSheet("font-weight: bold; color: #16a34a; font-size: 12px;")
            self.setStyleSheet(
                "QFrame { background-color: #f0fdf4; border: 1px solid #86efac; "
                "border-radius: 6px; padding: 6px 10px; }"
            )
        elif passed is False:
            self.lbl_badge.setText("❌")
            self.lbl_status.setText(status_text or "Gagal")
            self.lbl_status.setStyleSheet("font-weight: bold; color: #dc2626; font-size: 12px;")
            self.setStyleSheet(
                "QFrame { background-color: #fef2f2; border: 1px solid #fca5a5; "
                "border-radius: 6px; padding: 6px 10px; }"
            )
        else:
            self.lbl_badge.setText("⚪")
            self.lbl_status.setText(status_text or "Tidak Tersedia")
            self.lbl_status.setStyleSheet("font-weight: 500; color: #64748b; font-size: 12px;")
            self.setStyleSheet(
                "QFrame { background-color: #f8fafc; border: 1px solid #cbd5e1; "
                "border-radius: 6px; padding: 6px 10px; }"
            )


class TabValidator(QWidget):
    """Calibre-inspired EPUB Validation interface."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.current_report: Optional[ValidationReport] = None
        self._setup_ui()
        logger.info("TabValidator initialized successfully.")

    def _setup_ui(self) -> None:
        """Construct the validation dashboard."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("tabValidatorScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        content_widget = QWidget()
        content_widget.setObjectName("tabValidatorContent")
        main_layout = QVBoxLayout(content_widget)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # ---------------------------------------------------------------------
        # 1. Top File Selection Bar
        # ---------------------------------------------------------------------
        file_frame = QFrame()
        file_frame.setStyleSheet(
            "QFrame { background-color: #f8fafc; border: 1px solid #e2e8f0; "
            "border-radius: 6px; padding: 6px 10px; }"
        )
        f_layout = QHBoxLayout(file_frame)
        f_layout.setContentsMargins(4, 4, 4, 4)
        f_layout.setSpacing(10)

        lbl = QLabel("File EPUB:")
        lbl.setStyleSheet("font-weight: 600; color: #334155;")
        f_layout.addWidget(lbl)

        self.input_epub_path = QLineEdit()
        self.input_epub_path.setPlaceholderText("Pilih file EPUB yang ingin divalidasi...")
        f_layout.addWidget(self.input_epub_path, stretch=1)

        self.btn_browse = QPushButton("Pilih File...")
        self.btn_browse.clicked.connect(self._on_browse_clicked)
        f_layout.addWidget(self.btn_browse)

        self.btn_use_latest = QPushButton("Terjemahan Terakhir")
        self.btn_use_latest.setToolTip("Cari file EPUB terbaru di direktori output")
        self.btn_use_latest.clicked.connect(self._on_use_latest_clicked)
        f_layout.addWidget(self.btn_use_latest)

        self.btn_validate = QPushButton("🔍 Jalankan Validasi")
        self.btn_validate.setStyleSheet(
            "QPushButton { background-color: #0284c7; color: white; font-weight: bold; "
            "padding: 6px 16px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #0369a1; }"
        )
        self.btn_validate.clicked.connect(lambda: self.run_validation())
        f_layout.addWidget(self.btn_validate)

        main_layout.addWidget(file_frame)

        # ---------------------------------------------------------------------
        # 2. Overall Status Banner
        # ---------------------------------------------------------------------
        self.banner = QFrame()
        self.banner.setStyleSheet(
            "QFrame { background-color: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 6px; padding: 12px; }"
        )
        b_layout = QHBoxLayout(self.banner)
        b_layout.setContentsMargins(8, 8, 8, 8)
        b_layout.setSpacing(12)

        self.banner_icon = QLabel("📋")
        self.banner_icon.setStyleSheet("font-size: 26px;")
        b_layout.addWidget(self.banner_icon)

        b_text_layout = QVBoxLayout()
        self.banner_title = QLabel("Validasi Standar Dokumen EPUB")
        self.banner_title.setStyleSheet("font-weight: bold; font-size: 15px; color: #1e293b;")
        b_text_layout.addWidget(self.banner_title)

        self.banner_desc = QLabel("Pilih file buku EPUB lalu klik 'Jalankan Validasi' untuk memeriksa kepatuhan spesifikasi.")
        self.banner_desc.setStyleSheet("color: #64748b; font-size: 12px;")
        b_text_layout.addWidget(self.banner_desc)

        b_layout.addLayout(b_text_layout, stretch=1)
        main_layout.addWidget(self.banner)

        # ---------------------------------------------------------------------
        # 3. Validation Checkpoints Cards Grid
        # ---------------------------------------------------------------------
        grid_group = QGroupBox("Daftar Modul Pemeriksaan Dokumen")
        grid_layout = QGridLayout(grid_group)
        grid_layout.setSpacing(8)

        # Card 1: ZIP & Mimetype
        self.card_zip = CheckCard(
            "Arsip ZIP & Header Mimetype",
            "Mimetype harus menjadi entri pertama dan disimpan tanpa kompresi (Store).",
        )
        grid_layout.addWidget(self.card_zip, 0, 0)

        # Card 2: Container XML
        self.card_container = CheckCard(
            "Container XML (META-INF/container.xml)",
            "Memeriksa struktur container dan deklarasi rootfile path ke file OPF.",
        )
        grid_layout.addWidget(self.card_container, 0, 1)

        # Card 3: OPF Metadata & Spine
        self.card_opf = CheckCard(
            "Paket OPF Metadata & Spine",
            "Memastikan elemen metadata, manifest id unik, dan daftar urutan bab spine lengkap.",
        )
        grid_layout.addWidget(self.card_opf, 1, 0)

        # Card 4: XHTML & Hyperlink Internal
        self.card_xhtml = CheckCard(
            "Struktur XHTML & Tautan Internal",
            "Memvalidasi parse XML well-formedness pada dokumen bab dan keterjangkauan file.",
        )
        grid_layout.addWidget(self.card_xhtml, 1, 1)

        # Card 5: Calibre ebook-validate CLI
        self.card_calibre = CheckCard(
            "Calibre CLI (ebook-validate)",
            "Validasi tingkat industri menggunakan tool bawaan Calibre (opsional).",
        )
        grid_layout.addWidget(self.card_calibre, 2, 0, 1, 2)

        main_layout.addWidget(grid_group)

        # ---------------------------------------------------------------------
        # 4. Detailed Diagnostic Log
        # ---------------------------------------------------------------------
        log_group = QGroupBox("Detail Laporan Diagnostik")
        l_layout = QVBoxLayout(log_group)
        l_layout.setContentsMargins(10, 8, 10, 8)

        self.log_details = QPlainTextEdit()
        self.log_details.setReadOnly(True)
        self.log_details.setPlaceholderText("Hasil detail pemeriksaan akan ditampilkan di sini...")
        self.log_details.setMinimumHeight(140)
        self.log_details.setStyleSheet("font-family: monospace; font-size: 12px;")
        l_layout.addWidget(self.log_details)

        main_layout.addWidget(log_group, stretch=1)

        self.scroll_area.setWidget(content_widget)
        outer_layout.addWidget(self.scroll_area)

    # =========================================================================
    # Path Controls
    # =========================================================================

    def set_epub_path(self, path: str | Path) -> None:
        """Set target EPUB file path to validate."""
        p = Path(path)
        self.input_epub_path.setText(str(p.resolve()))

    def _on_browse_clicked(self) -> None:
        """Open file dialog to pick an EPUB."""
        default_dir = str(Path.cwd() / "output") if (Path.cwd() / "output").exists() else str(Path.cwd())
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Pilih File EPUB untuk Divalidasi",
            default_dir,
            "EPUB Files (*.epub);;All Files (*)",
        )
        if file_path:
            self.set_epub_path(file_path)

    def _on_use_latest_clicked(self) -> None:
        """Find and select the most recently modified EPUB file in output folder."""
        out_dir = Path("output")
        if not out_dir.exists():
            QMessageBox.information(self, "Folder Kosong", "Folder output belum dibuat.")
            return

        epubs = list(out_dir.glob("*.epub"))
        if not epubs:
            QMessageBox.information(
                self, "Tidak Ada File", "Belum ada file EPUB di folder output."
            )
            return

        latest = max(epubs, key=lambda p: p.stat().st_mtime)
        self.set_epub_path(latest)
        logger.info("Selected latest output EPUB: %s", latest)

    # =========================================================================
    # Validation Execution
    # =========================================================================

    def run_validation(self, epub_path: Optional[str | Path] = None) -> Optional[ValidationReport]:
        """Execute validation suite and update UI."""
        path_str = str(epub_path) if epub_path else self.input_epub_path.text().strip()
        if not path_str:
            QMessageBox.warning(
                self, "Pilih File", "Silakan pilih file EPUB terlebih dahulu untuk divalidasi."
            )
            return None

        p = Path(path_str)
        if not p.is_file():
            QMessageBox.critical(self, "File Tidak Ditemukan", f"File tidak ditemukan:\n{p}")
            return None

        self.input_epub_path.setText(str(p.resolve()))
        logger.info("Running EPUB validation on: %s", p)

        try:
            validator = EPUBValidator(p)
            report = validator.validate(run_calibre=True)
            self.current_report = report
            self._update_ui_from_report(report)
            return report
        except Exception as exc:
            logger.exception("Gagal memvalidasi EPUB: %s", exc)
            QMessageBox.critical(self, "Kesalahan Validasi", f"Terjadi kesalahan saat memvalidasi:\n{exc}")
            return None

    def _update_ui_from_report(self, report: ValidationReport) -> None:
        """Reflect validation report onto banner, cards, and log."""
        # 1. Update Banner
        if report.is_valid:
            self.banner_icon.setText("✅")
            self.banner_title.setText(f"VALID: {report.epub_path.name}")
            self.banner_title.setStyleSheet("font-weight: bold; font-size: 15px; color: #15803d;")
            self.banner_desc.setText(
                "Struktur dokumen EPUB ini sepenuhnya memenuhi spesifikasi dan siap dibaca di semua perangkat!"
            )
            self.banner.setStyleSheet(
                "QFrame { background-color: #f0fdf4; border: 1px solid #86efac; border-radius: 6px; padding: 12px; }"
            )
        else:
            self.banner_icon.setText("❌")
            self.banner_title.setText(f"TIDAK VALID: {report.epub_path.name}")
            self.banner_title.setStyleSheet("font-weight: bold; font-size: 15px; color: #b91c1c;")
            self.banner_desc.setText(
                f"Ditemukan {len(report.errors)} kesalahan struktural pada file EPUB ini."
            )
            self.banner.setStyleSheet(
                "QFrame { background-color: #fef2f2; border: 1px solid #fca5a5; border-radius: 6px; padding: 12px; }"
            )

        # 2. Update Check Cards based on checks passed and errors
        passed_texts = " ".join(report.checks_passed).lower()
        error_texts = " ".join(report.errors).lower()

        # ZIP & Mimetype
        zip_ok = ("mimetype" in passed_texts or report.is_valid) and "mimetype" not in error_texts
        self.card_zip.set_status(zip_ok, "Lolos" if zip_ok else "Gagal")

        # Container
        cont_ok = ("container" in passed_texts or report.is_valid) and "container" not in error_texts
        self.card_container.set_status(cont_ok, "Lolos" if cont_ok else "Gagal")

        # OPF
        opf_ok = (
            ("manifest" in passed_texts or "opf" in passed_texts or report.is_valid)
            and "manifest" not in error_texts
            and "opf" not in error_texts
        )
        self.card_opf.set_status(opf_ok, "Lolos" if opf_ok else "Gagal")

        # XHTML & Links
        xhtml_ok = (
            ("xhtml" in passed_texts or "xml" in passed_texts or report.is_valid)
            and "xhtml" not in error_texts
            and "xml" not in error_texts
        )
        self.card_xhtml.set_status(xhtml_ok, "Lolos" if xhtml_ok else "Gagal")

        # Calibre
        if report.calibre_available:
            self.card_calibre.set_status(
                report.calibre_passed,
                "Lolos Calibre CLI" if report.calibre_passed else "Peringatan Calibre CLI",
            )
        else:
            self.card_calibre.set_status(
                None, "Calibre CLI Tidak Terpasang (Gunakan Validasi Internal)"
            )

        # 3. Update Detailed Diagnostic Log
        log_lines = []
        log_lines.append(f"=== LAPORAN VALIDASI EPUB: {report.epub_path.name} ===")
        log_lines.append(f"Status Keseluruhan: {'VALID' if report.is_valid else 'TIDAK VALID'}\n")

        log_lines.append("[Pemeriksaan Berhasil]")
        if report.checks_passed:
            for item in report.checks_passed:
                log_lines.append(f"  ✓ {item}")
        else:
            log_lines.append("  (Tidak ada pemeriksaan yang lolos)")

        if report.warnings:
            log_lines.append("\n[Peringatan]")
            for item in report.warnings:
                log_lines.append(f"  ⚠ {item}")

        if report.errors:
            log_lines.append("\n[Kesalahan / Errors]")
            for item in report.errors:
                log_lines.append(f"  ✗ {item}")

        if report.calibre_available:
            log_lines.append("\n[Calibre ebook-validate Output]")
            st = "PASSED" if report.calibre_passed else "FAILED"
            log_lines.append(f"  Status: {st}")
            if report.calibre_output:
                log_lines.append(report.calibre_output.strip())
        else:
            log_lines.append("\n[Catatan Lingkungan]")
            log_lines.append("  Calibre (ebook-validate) tidak terdeteksi di PATH sistem.")

        self.log_details.setPlainText("\n".join(log_lines))

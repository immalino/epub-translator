"""Tab 1: Translation and Task Monitor Widget (Calibre-inspired).

Provides:
- Book Information panel with cover thumbnail and metadata
- Interactive chapters table with selection checkboxes and status badges
- Dry Run Quota & Cost Estimation modal dialog
- Dual Progress Bars (Overall Book progress and Active Chapter/Batch progress)
- Real-time auto-scrolling log console with copy and clear actions
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import Config
from glossary import Glossary
from runner import TranslationRunner

logger = logging.getLogger("epub_translate.gui.tab_translate")


class DryRunDialog(QDialog):
    """Modal dialog displaying dry-run statistics for API quota, tokens, and time."""

    def __init__(self, stats: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Estimasi Biaya & Kuota API (Dry Run)")
        self.resize(560, 480)
        self.setModal(True)
        self._setup_ui(stats)

    def _setup_ui(self, stats: Dict[str, Any]) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header Info Card
        header_card = QFrame()
        header_card.setStyleSheet(
            "background-color: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px;"
        )
        h_layout = QVBoxLayout(header_card)
        h_layout.setContentsMargins(6, 6, 6, 6)

        title_lbl = QLabel(f"<b>Buku:</b> {stats.get('book_title', 'Tanpa Judul')}")
        title_lbl.setStyleSheet("font-size: 14px; color: #1e293b;")
        title_lbl.setWordWrap(True)

        provider = str(stats.get("provider", "gemini")).upper()
        model = str(stats.get("model", "gemini-2.5-flash"))
        model_lbl = QLabel(f"<b>Mesin AI:</b> {provider} ({model})")
        model_lbl.setStyleSheet("color: #475569; font-size: 12px;")

        h_layout.addWidget(title_lbl)
        h_layout.addWidget(model_lbl)
        layout.addWidget(header_card)

        # Detail Grid
        grid_group = QGroupBox("Detail Estimasi Beban Kerja")
        grid = QGridLayout(grid_group)
        grid.setSpacing(8)

        def _add_row(r: int, label: str, value: str) -> None:
            lbl_key = QLabel(f"<b>{label}:</b>")
            lbl_key.setStyleSheet("color: #334155;")
            lbl_val = QLabel(value)
            lbl_val.setStyleSheet("color: #0f172a;")
            grid.addWidget(lbl_key, r, 0)
            grid.addWidget(lbl_val, r, 1)

        target_ch = stats.get("target_chapters", 0)
        total_ch = stats.get("total_spine_chapters", 0)
        _add_row(0, "Bab yang Dipilih", f"{target_ch} dari {total_ch} bab")

        total_segs = stats.get("total_segments", 0)
        total_chars = stats.get("total_chars", 0)
        _add_row(1, "Total Segmen", f"{total_segs:,} segmen")
        _add_row(2, "Total Karakter", f"{total_chars:,} karakter")

        words = stats.get("approx_words", 0)
        tokens = stats.get("approx_tokens", 0)
        _add_row(3, "Perkiraan Kata / Token", f"~{words:,} kata  /  ~{tokens:,} token")

        batches = stats.get("batches_count", 0)
        completed_b = stats.get("completed_batches", 0)
        remaining_b = stats.get("remaining_batches", 0)
        _add_row(4, "Total Batch Request", f"{batches} batch")
        _add_row(5, "Tersimpan di Cache", f"{completed_b} batch (akan dilewati)")
        _add_row(6, "Sisa Batch untuk AI", f"{remaining_b} batch")

        est_min = stats.get("est_minutes", 0.0)
        _add_row(7, "Estimasi Waktu Proses", f"~{est_min} menit")

        layout.addWidget(grid_group)

        # Quota Status Badge
        rpd_ok = stats.get("rpd_sufficient", True)
        quota_box = QFrame()
        q_layout = QHBoxLayout(quota_box)
        q_layout.setContentsMargins(10, 8, 10, 8)

        if rpd_ok:
            quota_box.setStyleSheet(
                "background-color: #f0fdf4; border: 1px solid #86efac; border-radius: 6px;"
            )
            q_text = (
                f"✅ <b>Kuota Harian Cukup:</b> Sisa {remaining_b} batch request "
                "berada di bawah kuota gratis 1.500 RPD (Request Per Day)."
            )
            q_lbl = QLabel(q_text)
            q_lbl.setStyleSheet("color: #166534;")
        else:
            quota_box.setStyleSheet(
                "background-color: #fef2f2; border: 1px solid #fca5a5; border-radius: 6px;"
            )
            q_text = (
                f"⚠️ <b>Perhatian Kuota:</b> Sisa {remaining_b} batch melebihi batas "
                "harian 1.500 RPD. Gunakan rotasi API Keys atau terjemahkan bertahap per bab."
            )
            q_lbl = QLabel(q_text)
            q_lbl.setStyleSheet("color: #991b1b;")

        q_lbl.setWordWrap(True)
        q_layout.addWidget(q_lbl)
        layout.addWidget(quota_box)

        # Dialog Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)


class TabTranslate(QWidget):
    """Tab 1: Translation and Task Monitor Widget."""

    sig_book_loaded = Signal(dict)
    sig_open_epub_requested = Signal()
    sig_dry_run_requested = Signal()
    sig_open_settings_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.current_epub_path: Optional[Path] = None
        self.current_book_info: Optional[Dict[str, Any]] = None
        self.current_glossary: Optional[Glossary] = None
        self._chapter_row_map: Dict[int, int] = {}
        self._is_populating: bool = False

        self._setup_ui()
        self._set_placeholder_cover()

    def _setup_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("tabTranslateScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        content_widget = QWidget()
        content_widget.setObjectName("tabTranslateContent")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(12)

        # 1. Book Info Panel (Top)
        content_layout.addWidget(self._create_book_info_panel())

        # 2. Chapter Table Panel (Middle)
        content_layout.addWidget(self._create_chapter_table_panel())

        # 3. Progress Bars Panel
        content_layout.addWidget(self._create_progress_panel())

        # 4. Live Log Console Panel
        content_layout.addWidget(self._create_log_console_panel())

        self.scroll_area.setWidget(content_widget)
        outer_layout.addWidget(self.scroll_area)

    # =========================================================================
    # Panel Creators
    # =========================================================================

    def _create_book_info_panel(self) -> QGroupBox:
        """Create the top panel displaying cover thumbnail and metadata."""
        group = QGroupBox("Informasi Buku")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(14)

        # Cover Thumbnail
        self.label_cover = QLabel()
        self.label_cover.setFixedSize(96, 130)
        self.label_cover.setStyleSheet(
            "border: 1px solid #cbd5e1; border-radius: 4px; background-color: #f8fafc;"
        )
        self.label_cover.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label_cover)

        # Metadata Vertical Layout
        meta_layout = QVBoxLayout()
        meta_layout.setSpacing(4)

        self.label_title = QLabel("Belum Ada Buku Dimuat")
        self.label_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #1e293b;")
        self.label_title.setWordWrap(True)

        self.label_creator = QLabel("Pengarang: -")
        self.label_creator.setStyleSheet("color: #475569; font-size: 12px;")

        self.label_language = QLabel("Bahasa Sumber: -")
        self.label_language.setStyleSheet("color: #475569; font-size: 12px;")

        self.label_summary = QLabel("Total: 0 Bab • 0 Segmen • 0 Karakter")
        self.label_summary.setStyleSheet("color: #0369a1; font-weight: 500; font-size: 12px;")

        self.label_engine_summary = QLabel()
        self.label_engine_summary.setStyleSheet("color: #059669; font-weight: 500; font-size: 11px;")

        self.label_path = QLabel("Lokasi File: -")
        self.label_path.setStyleSheet("color: #64748b; font-size: 11px;")
        self.label_path.setWordWrap(True)

        meta_layout.addWidget(self.label_title)
        meta_layout.addWidget(self.label_creator)
        meta_layout.addWidget(self.label_language)
        meta_layout.addWidget(self.label_summary)
        meta_layout.addWidget(self.label_engine_summary)
        meta_layout.addWidget(self.label_path)
        meta_layout.addStretch()

        layout.addLayout(meta_layout, stretch=1)

        # Quick Actions on Right of Info Panel
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)
        actions_layout.setAlignment(Qt.AlignTop)

        self.btn_open_epub = QPushButton("📂 Buka EPUB...")
        self.btn_open_epub.setStatusTip("Pilih dan buka file EPUB dari komputer")
        self.btn_open_epub.clicked.connect(self.sig_open_epub_requested.emit)
        actions_layout.addWidget(self.btn_open_epub)

        self.btn_dry_run = QPushButton("📊 Estimasi Kuota")
        self.btn_dry_run.setStatusTip("Hitung perkiraan token, batch, dan waktu proses")
        self.btn_dry_run.setEnabled(False)
        self.btn_dry_run.clicked.connect(self.show_dry_run_dialog)
        actions_layout.addWidget(self.btn_dry_run)

        self.btn_settings = QPushButton("⚙️ Ubah Mesin / Kunci")
        self.btn_settings.setStatusTip("Buka pengaturan untuk mengedit model AI dan API Keys secara langsung")
        self.btn_settings.clicked.connect(self.sig_open_settings_requested.emit)
        actions_layout.addWidget(self.btn_settings)

        layout.addLayout(actions_layout)

        try:
            self.update_engine_summary(Config.load())
        except Exception:
            pass

        return group

    def _create_chapter_table_panel(self) -> QGroupBox:
        """Create the chapter selection table and selection controls."""
        group = QGroupBox("Daftar Bab & Pemilihan Terjemahan")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Action Toolbar above table
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.btn_select_all = QPushButton("Pilih Semua")
        self.btn_select_all.clicked.connect(self.select_all_chapters)
        top_bar.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton("Batalkan Semua")
        self.btn_deselect_all.clicked.connect(self.deselect_all_chapters)
        top_bar.addWidget(self.btn_deselect_all)

        self.label_selection_summary = QLabel("0 bab dipilih")
        self.label_selection_summary.setStyleSheet("color: #475569; font-weight: 500;")
        top_bar.addWidget(self.label_selection_summary)

        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Chapters Table Widget
        self.table_chapters = QTableWidget(0, 6)
        self.table_chapters.setHorizontalHeaderLabels([
            "Pilih",
            "#",
            "File Spine / Path",
            "Segmen",
            "Karakter",
            "Status",
        ])
        self.table_chapters.setAlternatingRowColors(True)
        self.table_chapters.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_chapters.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_chapters.verticalHeader().setVisible(False)

        header = self.table_chapters.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)

        self.table_chapters.setColumnWidth(0, 50)
        self.table_chapters.setColumnWidth(1, 45)
        self.table_chapters.setColumnWidth(3, 85)
        self.table_chapters.setColumnWidth(4, 95)
        self.table_chapters.setColumnWidth(5, 110)
        self.table_chapters.setMinimumHeight(180)

        self.table_chapters.itemChanged.connect(self._on_table_item_changed)
        layout.addWidget(self.table_chapters)

        return group

    def _create_progress_panel(self) -> QGroupBox:
        """Create the dual progress bars panel."""
        group = QGroupBox("Kemajuan Terjemahan")
        group.setMinimumHeight(175)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # 1. Overall Progress
        overall_header = QHBoxLayout()
        overall_title = QLabel("<b>Progres Keseluruhan Buku:</b>")
        self.label_overall_percent = QLabel("0%")
        self.label_overall_percent.setStyleSheet("font-weight: bold; color: #0284c7; font-size: 13px;")
        overall_header.addWidget(overall_title)
        overall_header.addStretch()
        overall_header.addWidget(self.label_overall_percent)
        layout.addLayout(overall_header)

        self.progress_overall = QProgressBar()
        self.progress_overall.setObjectName("overallProgress")
        self.progress_overall.setRange(0, 100)
        self.progress_overall.setValue(0)
        self.progress_overall.setMinimumHeight(22)
        self.progress_overall.setTextVisible(True)
        layout.addWidget(self.progress_overall)

        self.label_overall_status = QLabel("Siap untuk menerjemahkan.")
        self.label_overall_status.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.label_overall_status)

        layout.addSpacing(6)

        # 2. Active Chapter / Batch Progress
        batch_header = QHBoxLayout()
        batch_title = QLabel("<b>Progres Bab Aktif:</b>")
        self.label_batch_percent = QLabel("0%")
        self.label_batch_percent.setStyleSheet("font-weight: bold; color: #10b981; font-size: 13px;")
        batch_header.addWidget(batch_title)
        batch_header.addStretch()
        batch_header.addWidget(self.label_batch_percent)
        layout.addLayout(batch_header)

        self.progress_batch = QProgressBar()
        self.progress_batch.setObjectName("chapterProgress")
        self.progress_batch.setRange(0, 100)
        self.progress_batch.setValue(0)
        self.progress_batch.setMinimumHeight(22)
        self.progress_batch.setTextVisible(True)
        layout.addWidget(self.progress_batch)

        self.label_batch_status = QLabel("-")
        self.label_batch_status.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.label_batch_status)

        return group

    def _create_log_console_panel(self) -> QGroupBox:
        """Create the real-time live log console."""
        group = QGroupBox("Log Konsol Real-time")
        group.setMinimumHeight(200)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Header with actions
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Aktivitas Penerjemahan:</b>"))
        header.addStretch()

        self.btn_copy_log = QPushButton("Salin Log")
        self.btn_copy_log.setStatusTip("Salin seluruh isi log konsol ke clipboard")
        self.btn_copy_log.clicked.connect(self.copy_log)
        header.addWidget(self.btn_copy_log)

        self.btn_clear_log = QPushButton("Bersihkan Log")
        self.btn_clear_log.setStatusTip("Hapus tampilan log konsol")
        self.btn_clear_log.clicked.connect(self.clear_log)
        header.addWidget(self.btn_clear_log)

        layout.addLayout(header)

        # Console Text Box
        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMinimumHeight(140)
        self.log_console.setMaximumBlockCount(3000)
        self.log_console.setPlaceholderText("Log aktivitas penerjemahan akan ditampilkan di sini...")
        layout.addWidget(self.log_console)

        return group

    # =========================================================================
    # Book Loading & Inspection
    # =========================================================================

    def _set_placeholder_cover(self) -> None:
        """Render a clean placeholder image when no cover is available."""
        pixmap = QPixmap(96, 130)
        pixmap.fill(QColor("#f1f5f9"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#94a3b8"))
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawRect(0, 0, 95, 129)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "Tanpa\nCover")
        painter.end()
        self.label_cover.setPixmap(pixmap)

    def update_engine_summary(self, cfg: Config) -> None:
        """Update active engine badge text."""
        if not hasattr(self, "label_engine_summary") or self.label_engine_summary is None:
            return
        if cfg.provider == "gemini":
            keys_info = f"{len(cfg.api_keys)} Kunci API" if cfg.api_keys else "Belum ada Kunci API"
            self.label_engine_summary.setText(f"Mesin: Google Gemini ({cfg.model}) • {keys_info}")
        else:
            self.label_engine_summary.setText(f"Mesin: Ollama ({cfg.model})")

    def load_epub(self, file_path: str | Path) -> None:
        """Inspect EPUB file, populate book info, cover, and chapter table."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File EPUB tidak ditemukan: {path}")

        logger.info("Inspecting EPUB: %s", path)
        info = TranslationRunner.inspect_epub(path)
        self.current_epub_path = path
        self.current_book_info = info

        # 1. Update Cover Thumbnail
        cover_bytes = info.get("cover_bytes")
        if cover_bytes:
            pixmap = QPixmap()
            if pixmap.loadFromData(cover_bytes):
                scaled = pixmap.scaled(
                    self.label_cover.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self.label_cover.setPixmap(scaled)
            else:
                self._set_placeholder_cover()
        else:
            self._set_placeholder_cover()

        # 2. Update Book Info Labels
        title = info.get("title") or path.stem
        creator = info.get("creator") or "Tidak diketahui"
        lang = info.get("language") or "en"
        chapters = info.get("chapters", [])

        total_segs = sum(ch.get("segment_count", 0) for ch in chapters)
        total_chars = sum(ch.get("char_count", 0) for ch in chapters)
        approx_words = int(total_chars / 5.5)

        self.label_title.setText(title)
        self.label_creator.setText(f"Pengarang: {creator}")
        self.label_language.setText(f"Bahasa Sumber: {lang}")
        self.label_summary.setText(
            f"{len(chapters)} Bab • {total_segs:,} Segmen • ~{total_chars:,} Karakter (~{approx_words:,} Kata)"
        )
        self.label_path.setText(f"File: {path.name}")
        self.label_path.setToolTip(str(path.resolve()))

        self.btn_dry_run.setEnabled(True)

        # 3. Populate Chapter Table
        self._populate_chapter_table(chapters)

        # 4. Reset Progress
        self.reset_progress()

        self.append_log("INFO", f"Berhasil memuat buku: {title} ({len(chapters)} bab, {total_segs} segmen)")
        self.sig_book_loaded.emit(info)

    def _populate_chapter_table(self, chapters: List[Dict[str, Any]]) -> None:
        """Populate chapters table with items and checkboxes."""
        self._is_populating = True
        self.table_chapters.setRowCount(0)
        self._chapter_row_map.clear()
        self.table_chapters.setRowCount(len(chapters))

        for row, ch in enumerate(chapters):
            ch_idx = ch["index"]
            self._chapter_row_map[ch_idx] = row

            # Col 0: Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked)
            chk_item.setTextAlignment(Qt.AlignCenter)
            self.table_chapters.setItem(row, 0, chk_item)

            # Col 1: Chapter Index (#)
            no_item = QTableWidgetItem(str(ch_idx))
            no_item.setTextAlignment(Qt.AlignCenter)
            no_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table_chapters.setItem(row, 1, no_item)

            # Col 2: File Spine Path
            spine_path = ch.get("href") or ch.get("zip_path", "")
            spine_item = QTableWidgetItem(spine_path)
            spine_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            spine_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            spine_item.setToolTip(ch.get("zip_path", ""))
            self.table_chapters.setItem(row, 2, spine_item)

            # Col 3: Segment Count
            seg_item = QTableWidgetItem(str(ch.get("segment_count", 0)))
            seg_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            seg_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table_chapters.setItem(row, 3, seg_item)

            # Col 4: Character Count
            chars = ch.get("char_count", 0)
            char_item = QTableWidgetItem(f"{chars:,}")
            char_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            char_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table_chapters.setItem(row, 4, char_item)

            # Col 5: Initial Status
            status_item = QTableWidgetItem("Belum")
            status_item.setTextAlignment(Qt.AlignCenter)
            status_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            status_item.setForeground(QColor("#64748b"))
            self.table_chapters.setItem(row, 5, status_item)

        self._is_populating = False
        self._update_selection_summary()

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        """Handle checkbox click to update selection counters."""
        if self._is_populating or item.column() != 0:
            return
        self._update_selection_summary()

    def _update_selection_summary(self) -> None:
        """Update the label displaying selected chapters count."""
        selected = self.get_selected_chapter_indices()
        total = self.table_chapters.rowCount()
        self.label_selection_summary.setText(f"{len(selected)} dari {total} bab dipilih")

    # =========================================================================
    # Chapter Selection & Filtering
    # =========================================================================

    def select_all_chapters(self) -> None:
        """Check all chapters in the table."""
        self._is_populating = True
        for row in range(self.table_chapters.rowCount()):
            item = self.table_chapters.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked)
        self._is_populating = False
        self._update_selection_summary()

    def deselect_all_chapters(self) -> None:
        """Uncheck all chapters in the table."""
        self._is_populating = True
        for row in range(self.table_chapters.rowCount()):
            item = self.table_chapters.item(row, 0)
            if item:
                item.setCheckState(Qt.Unchecked)
        self._is_populating = False
        self._update_selection_summary()

    def get_selected_chapter_indices(self) -> List[int]:
        """Return list of 1-based chapter numbers currently checked."""
        selected: List[int] = []
        for row in range(self.table_chapters.rowCount()):
            chk_item = self.table_chapters.item(row, 0)
            no_item = self.table_chapters.item(row, 1)
            if chk_item and chk_item.checkState() == Qt.Checked and no_item:
                try:
                    selected.append(int(no_item.text()))
                except ValueError:
                    pass
        return sorted(selected)

    def get_selected_chapters_filter(self) -> Optional[str]:
        """Return chapter filter string formatted for EPUBParser/TranslationRunner.
        
        - If no chapters selected: returns ""
        - If all chapters selected: returns None (meaning all)
        - Otherwise: returns comma-separated string, e.g. "1,2,4"
        """
        selected = self.get_selected_chapter_indices()
        total = self.table_chapters.rowCount()
        if not selected:
            return ""
        if len(selected) == total:
            return None
        return ",".join(str(i) for i in selected)

    # =========================================================================
    # Status & Progress Updates (Connected to Worker Signals)
    # =========================================================================

    def update_chapter_status(self, chapter_idx: int, status_text: str) -> None:
        """Update status column for the specified chapter index."""
        row = self._chapter_row_map.get(chapter_idx)
        if row is None:
            for r in range(self.table_chapters.rowCount()):
                item = self.table_chapters.item(r, 1)
                if item and item.text() == str(chapter_idx):
                    row = r
                    break

        if row is not None:
            status_item = self.table_chapters.item(row, 5)
            if status_item:
                status_item.setText(status_text)
                st_lower = status_text.lower()
                if "selesai" in st_lower or "done" in st_lower:
                    status_item.setForeground(QColor("#16a34a"))  # green
                elif "proses" in st_lower or "memproses" in st_lower:
                    status_item.setForeground(QColor("#0284c7"))  # blue
                elif "gagal" in st_lower or "error" in st_lower:
                    status_item.setForeground(QColor("#dc2626"))  # red
                else:
                    status_item.setForeground(QColor("#64748b"))  # gray

    def update_overall_progress(self, fraction: float, message: str) -> None:
        """Update overall book progress bar and text."""
        pct = max(0, min(100, int(round(fraction * 100))))
        self.progress_overall.setValue(pct)
        self.label_overall_percent.setText(f"{pct}%")
        self.label_overall_status.setText(message)

    def update_batch_progress(self, fraction: float, message: str) -> None:
        """Update current chapter batch progress bar and text."""
        pct = max(0, min(100, int(round(fraction * 100))))
        self.progress_batch.setValue(pct)
        self.label_batch_percent.setText(f"{pct}%")
        self.label_batch_status.setText(message)

    def reset_progress(self) -> None:
        """Reset progress bars and status labels."""
        self.progress_overall.setValue(0)
        self.label_overall_percent.setText("0%")
        self.label_overall_status.setText("Siap untuk menerjemahkan.")

        self.progress_batch.setValue(0)
        self.label_batch_percent.setText("0%")
        self.label_batch_status.setText("-")

    # =========================================================================
    # Console Log
    # =========================================================================

    def append_log(self, level: str, message: str) -> None:
        """Append formatted timestamped message to the log console."""
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        lvl = level.upper()
        entry = f"[{now_str}] [{lvl}] {message}"
        self.log_console.appendPlainText(entry)

        # Auto scroll to bottom
        bar = self.log_console.verticalScrollBar()
        bar.setValue(bar.maximum())

    def copy_log(self) -> None:
        """Copy console log contents to system clipboard."""
        text = self.log_console.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
                self.append_log("INFO", "Log konsol berhasil disalin ke clipboard.")

    def clear_log(self) -> None:
        """Clear the console log."""
        self.log_console.clear()

    # =========================================================================
    # Dry Run Estimation Dialog
    # =========================================================================

    def show_dry_run_dialog(self, config: Optional[Config] = None) -> None:
        """Calculate dry-run workload statistics and display modal dialog."""
        if not self.current_epub_path:
            QMessageBox.information(
                self,
                "Estimasi Kuota (Dry Run)",
                "Silakan buka file EPUB terlebih dahulu sebelum menghitung estimasi.",
            )
            return

        filter_str = self.get_selected_chapters_filter()
        if filter_str == "":
            QMessageBox.warning(
                self,
                "Estimasi Kuota (Dry Run)",
                "Pilih minimal satu bab pada tabel untuk menghitung estimasi.",
            )
            return

        if config is None:
            config = Config.load()

        try:
            stats = TranslationRunner.get_dry_run_stats(
                input_path=self.current_epub_path,
                config=config,
                chapter_filter=filter_str,
                glossary=self.current_glossary,
            )
            dialog = DryRunDialog(stats, parent=self)
            dialog.exec()
        except Exception as exc:
            logger.exception("Gagal menghitung estimasi dry run: %s", exc)
            QMessageBox.critical(
                self,
                "Kesalahan Estimasi",
                f"Gagal menghitung estimasi kuota:\n{exc}",
            )


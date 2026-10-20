"""Tab 2: Bilingual Side-by-Side Editor (Advanced Mode Calibre).

Provides:
- Chapter selector dropdown synced with loaded EPUB
- Side-by-side segment review: ID, Original Source (read-only), Translation (editable)
- Fast live text search and row filtering
- Save manual edits directly into CheckpointManager cache
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from checkpoint import BatchRecord, CheckpointManager
from config import Config
from epub_parser import EPUBParser
from glossary import Glossary
from runner import TranslationRunner
from text_mapper import XHTMLTextMapper

logger = logging.getLogger("epub_translate.gui.tab_bilingual")


class TabBilingual(QWidget):
    """Calibre-inspired Bilingual Chapter Editor for manual inspection and corrections."""

    sig_cache_saved = Signal(int)  # Emits count of saved segments

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.current_epub_path: Optional[Path] = None
        self.current_book_info: Optional[Dict[str, Any]] = None
        self.output_path: Optional[Path] = None
        self.config: Config = Config.load()
        self.glossary: Optional[Glossary] = None

        self._current_pairs: List[Dict[str, Any]] = []
        self._is_populating: bool = False

        self._setup_ui()
        logger.info("TabBilingual initialized successfully.")

    def _setup_ui(self) -> None:
        """Construct the bilingual editor layout and controls."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # ---------------------------------------------------------------------
        # 1. Top Control Bar (Chapter selector, search filter, save button)
        # ---------------------------------------------------------------------
        controls_frame = QFrame()
        controls_frame.setStyleSheet(
            "QFrame { background-color: #f8fafc; border: 1px solid #e2e8f0; "
            "border-radius: 6px; padding: 6px 10px; }"
        )
        ctrl_layout = QHBoxLayout(controls_frame)
        ctrl_layout.setContentsMargins(4, 4, 4, 4)
        ctrl_layout.setSpacing(10)

        # Chapter Dropdown
        lbl_chapter = QLabel("Pilih Bab:")
        lbl_chapter.setStyleSheet("font-weight: 600; color: #334155;")
        ctrl_layout.addWidget(lbl_chapter)

        self.combo_chapters = QComboBox()
        self.combo_chapters.setMinimumWidth(260)
        self.combo_chapters.setStyleSheet("padding: 4px 8px; font-size: 13px;")
        self.combo_chapters.currentIndexChanged.connect(self._on_chapter_changed)
        ctrl_layout.addWidget(self.combo_chapters)

        # Refresh button
        self.btn_refresh = QPushButton("Segarkan")
        self.btn_refresh.setToolTip("Muat ulang segmen bab aktif dari disk/cache")
        self.btn_refresh.clicked.connect(self.reload_current_chapter)
        ctrl_layout.addWidget(self.btn_refresh)

        ctrl_layout.addSpacing(10)

        # Search / Filter Box
        lbl_search = QLabel("Cari Teks:")
        lbl_search.setStyleSheet("font-weight: 600; color: #334155;")
        ctrl_layout.addWidget(lbl_search)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter teks asli / terjemahan...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        ctrl_layout.addWidget(self.search_input)

        ctrl_layout.addStretch()

        # Save to Cache Button
        self.btn_save_cache = QPushButton("💾 Simpan Perubahan ke Cache")
        self.btn_save_cache.setStyleSheet(
            "QPushButton { background-color: #0284c7; color: white; font-weight: bold; "
            "padding: 6px 14px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #0369a1; } "
            "QPushButton:disabled { background-color: #cbd5e1; color: #94a3b8; }"
        )
        self.btn_save_cache.setToolTip(
            "Perbarui teks terjemahan ke cache CheckpointManager untuk finalisasi EPUB"
        )
        self.btn_save_cache.clicked.connect(lambda: self.save_changes_to_cache(quiet=False))
        ctrl_layout.addWidget(self.btn_save_cache)

        main_layout.addWidget(controls_frame)

        # ---------------------------------------------------------------------
        # 2. Side-by-side Bilingual Table
        # ---------------------------------------------------------------------
        self.table_segments = QTableWidget(0, 3)
        self.table_segments.setObjectName("bilingualTable")
        self.table_segments.setHorizontalHeaderLabels([
            "ID",
            "Teks Asli (Read-only)",
            "Teks Terjemahan (Editable)",
        ])
        self.table_segments.setAlternatingRowColors(True)
        self.table_segments.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_segments.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_segments.verticalHeader().setVisible(False)
        self.table_segments.setWordWrap(True)

        header = self.table_segments.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_segments.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        main_layout.addWidget(self.table_segments, stretch=1)

        # ---------------------------------------------------------------------
        # 3. Bottom Status Bar Info
        # ---------------------------------------------------------------------
        status_bar = QHBoxLayout()
        self.lbl_stats = QLabel("Belum ada buku atau bab yang dimuat.")
        self.lbl_stats.setStyleSheet("color: #64748b; font-size: 12px;")
        status_bar.addWidget(self.lbl_stats)

        status_bar.addStretch()

        self.lbl_filter_info = QLabel("")
        self.lbl_filter_info.setStyleSheet("color: #0369a1; font-weight: 500; font-size: 12px;")
        status_bar.addWidget(self.lbl_filter_info)

        main_layout.addLayout(status_bar)

    # =========================================================================
    # Book & Chapter Loading
    # =========================================================================

    def load_book(
        self,
        epub_path: str | Path,
        book_info: Optional[Dict[str, Any]] = None,
        output_path: Optional[Path] = None,
    ) -> None:
        """Load book chapters into combo box and display the first chapter."""
        path = Path(epub_path)
        if not path.is_file():
            logger.warning("File EPUB tidak ditemukan: %s", path)
            return

        self.current_epub_path = path
        self.output_path = output_path
        if book_info:
            self.current_book_info = book_info
        else:
            try:
                self.current_book_info = TranslationRunner.inspect_epub(path)
            except Exception as e:
                logger.error("Gagal inspeksi EPUB untuk bilingual editor: %s", e)
                return

        chapters = self.current_book_info.get("chapters", [])
        self.combo_chapters.blockSignals(True)
        self.combo_chapters.clear()

        for ch in chapters:
            idx = ch.get("index", 1)
            href = ch.get("href") or ch.get("zip_path", "")
            segs = ch.get("segment_count", 0)
            label = f"Bab {idx}: {href} ({segs} segmen)"
            self.combo_chapters.addItem(label, ch.get("zip_path", ""))

        self.combo_chapters.blockSignals(False)

        if self.combo_chapters.count() > 0:
            self.combo_chapters.setCurrentIndex(0)
            self._load_selected_chapter()
        else:
            self.table_segments.setRowCount(0)
            self.lbl_stats.setText("Buku tidak memiliki bab teks.")

    def _on_chapter_changed(self, index: int) -> None:
        """Slot called when combo box chapter selection changes."""
        if index >= 0:
            self._load_selected_chapter()

    def reload_current_chapter(self) -> None:
        """Reload the currently selected chapter preview."""
        self._load_selected_chapter()

    def _load_selected_chapter(self) -> None:
        """Fetch bilingual pairs via TranslationRunner and populate table."""
        if not self.current_epub_path or self.combo_chapters.currentIndex() < 0:
            return

        zip_path = self.combo_chapters.currentData()
        if not zip_path:
            return

        logger.info("Loading bilingual preview for chapter: %s", zip_path)
        try:
            pairs = TranslationRunner.get_bilingual_preview(
                input_path=self.current_epub_path,
                chapter_zip_path=zip_path,
                output_path=self.output_path,
                config=self.config,
                glossary=self.glossary,
            )
        except Exception as exc:
            logger.exception("Gagal memuat bilingual preview: %s", exc)
            pairs = []

        self._current_pairs = pairs
        self._populate_table(pairs)

    def _populate_table(self, pairs: List[Dict[str, Any]]) -> None:
        """Populate the table with bilingual segment pairs."""
        self._is_populating = True
        self.table_segments.setRowCount(len(pairs))

        translated_count = 0
        for row, pair in enumerate(pairs):
            seg_id = str(pair.get("id", ""))
            src_text = str(pair.get("source", ""))
            trans_text = pair.get("translated")
            is_translated = pair.get("is_translated", False)

            # Col 0: Segment ID (read-only)
            item_id = QTableWidgetItem(seg_id)
            item_id.setTextAlignment(Qt.AlignCenter)
            item_id.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item_id.setForeground(QColor("#64748b"))
            self.table_segments.setItem(row, 0, item_id)

            # Col 1: Original Source (read-only)
            item_src = QTableWidgetItem(src_text)
            item_src.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
            item_src.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table_segments.setItem(row, 1, item_src)

            # Col 2: Translated Text (editable)
            target_str = str(trans_text) if trans_text is not None else ""
            item_tgt = QTableWidgetItem(target_str)
            item_tgt.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
            item_tgt.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)

            if is_translated:
                translated_count += 1
                item_tgt.setForeground(QColor("#0f172a"))
            else:
                # Dim placeholder style for untranslated rows
                item_tgt.setForeground(QColor("#94a3b8"))

            self.table_segments.setItem(row, 2, item_tgt)

        self._is_populating = False

        total_segs = len(pairs)
        self.lbl_stats.setText(
            f"Total {total_segs} segmen | {translated_count} telah diterjemahkan "
            f"({total_segs - translated_count} belum diterjemahkan)"
        )

        # Apply active filter
        self._on_search_text_changed(self.search_input.text())

    # =========================================================================
    # Live Search & Filter
    # =========================================================================

    def _on_search_text_changed(self, text: str) -> None:
        """Filter table rows based on query matching source, translation, or ID."""
        query = text.strip().lower()
        total_rows = self.table_segments.rowCount()
        if not query:
            for r in range(total_rows):
                self.table_segments.setRowHidden(r, False)
            self.lbl_filter_info.setText("")
            return

        visible_count = 0
        for r in range(total_rows):
            item_id = self.table_segments.item(r, 0)
            item_src = self.table_segments.item(r, 1)
            item_tgt = self.table_segments.item(r, 2)

            id_str = item_id.text().lower() if item_id else ""
            src_str = item_src.text().lower() if item_src else ""
            tgt_str = item_tgt.text().lower() if item_tgt else ""

            matched = (query in id_str) or (query in src_str) or (query in tgt_str)
            self.table_segments.setRowHidden(r, not matched)
            if matched:
                visible_count += 1

        self.lbl_filter_info.setText(f"Menampilkan {visible_count} dari {total_rows} segmen")

    # =========================================================================
    # Checkpoint Cache Save
    # =========================================================================

    def save_changes_to_cache(self, quiet: bool = False) -> int:
        """Save manual translations from the table into CheckpointManager cache.

        Returns:
            Number of segment translations saved to cache.
        """
        if not self.current_epub_path:
            if not quiet:
                QMessageBox.warning(self, "Buku Belum Dibuka", "Silakan buka file EPUB terlebih dahulu.")
            return 0

        zip_path = self.combo_chapters.currentData()
        if not zip_path:
            if not quiet:
                QMessageBox.warning(self, "Pilih Bab", "Tidak ada bab yang dipilih.")
            return 0

        # Extract current translations from table
        translations: Dict[str, str] = {}
        for r in range(self.table_segments.rowCount()):
            item_id = self.table_segments.item(r, 0)
            item_tgt = self.table_segments.item(r, 2)
            if item_id and item_tgt:
                val = item_tgt.text().strip()
                if val:
                    translations[item_id.text()] = val

        if not translations:
            if not quiet:
                QMessageBox.information(
                    self, "Tidak Ada Terjemahan", "Belum ada teks terjemahan yang diisi pada bab ini."
                )
            return 0

        try:
            epub_hash = CheckpointManager.compute_file_hash(self.current_epub_path)
            glossary_hash = self.glossary.hash if self.glossary else "none"
            checkpoint = CheckpointManager(
                epub_hash=epub_hash,
                model=self.config.model,
                glossary_hash=glossary_hash,
                checkpoint_dir=self.config.checkpoint_dir,
            )

            # Check if chapter exists in checkpoint
            ch_record = checkpoint.chapters.get(zip_path)
            if ch_record and ch_record.batches:
                # Update existing batch records
                for batch in ch_record.batches.values():
                    updated_in_batch = False
                    for item_id in batch.item_ids:
                        if item_id in translations:
                            batch.translated_texts[item_id] = translations[item_id]
                            updated_in_batch = True
                    if updated_in_batch and len(batch.translated_texts) == len(batch.item_ids):
                        batch.status = "COMPLETED"
            else:
                # Create chapter and batch structure if checkpoint not initialized
                parser = EPUBParser(self.current_epub_path)
                raw_bytes = parser.read_zip_file(zip_path)
                mapper = XHTMLTextMapper()
                _, segments = mapper.extract_segments(raw_bytes)

                checkpoint.register_chapter(
                    href=zip_path,
                    title=f"Spine ({zip_path})",
                    total_segments=len(segments),
                )
                ch_record = checkpoint.chapters[zip_path]

                batch_size = self.config.batch_size or 10
                batches = [segments[i : i + batch_size] for i in range(0, len(segments), batch_size)]
                for b_idx, batch in enumerate(batches, 1):
                    b_id = f"b{b_idx:03d}"
                    item_ids = [s.id for s in batch]
                    b_src_hash = CheckpointManager.compute_content_hash("".join(s.inner_html for s in batch))
                    b_trans = {sid: translations[sid] for sid in item_ids if sid in translations}
                    is_full = len(b_trans) == len(item_ids)

                    ch_record.batches[b_id] = BatchRecord(
                        batch_id=b_id,
                        item_ids=item_ids,
                        source_hash=b_src_hash,
                        status="COMPLETED" if is_full else "IN_PROGRESS",
                        translated_texts=b_trans,
                    )

            checkpoint.save()
            count = len(translations)
            logger.info("Saved %d segment translations to checkpoint cache for %s", count, zip_path)

            self.sig_cache_saved.emit(count)
            if not quiet:
                QMessageBox.information(
                    self,
                    "Cache Tersimpan",
                    f"Berhasil menyimpan {count} terjemahan segmen ke cache checkpoint!\n"
                    f"Bab: {zip_path}\n"
                    f"Sesi Checkpoint: {checkpoint.session_id}",
                )
            return count

        except Exception as exc:
            logger.exception("Gagal menyimpan perubahan ke cache: %s", exc)
            if not quiet:
                QMessageBox.critical(
                    self, "Gagal Simpan Cache", f"Terjadi kesalahan saat menyimpan ke cache:\n{exc}"
                )
            return 0


"""Tab 3: Glossary and Terminology Management Widget.

Provides:
- Table management for novel terminology, character names, and consistency rules:
  Columns: Istilah Sumber, Terjemahan, Catatan Konteks, Peka Huruf Besar (Case-sensitive).
- Actions: Add Row, Delete Row, Import JSON, Export JSON.
- Fast search filter for glossary terms.
- Synchronization with core Glossary object for translation runners.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from glossary import Glossary

logger = logging.getLogger("epub_translate.gui.tab_glossary")


class TabGlossary(QWidget):
    """Calibre-inspired Glossary Manager for consistent character names and terminology."""

    sig_glossary_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._is_populating: bool = False
        self._setup_ui()
        logger.info("TabGlossary initialized successfully.")

    def _setup_ui(self) -> None:
        """Construct the glossary management interface."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # ---------------------------------------------------------------------
        # 1. Top Action Toolbar
        # ---------------------------------------------------------------------
        top_bar = QFrame()
        top_bar.setStyleSheet(
            "QFrame { background-color: #f8fafc; border: 1px solid #e2e8f0; "
            "border-radius: 6px; padding: 4px 8px; }"
        )
        bar_layout = QHBoxLayout(top_bar)
        bar_layout.setContentsMargins(4, 4, 4, 4)
        bar_layout.setSpacing(8)

        # Tambah Baris
        self.btn_add_row = QPushButton("➕ Tambah Baris")
        self.btn_add_row.setStyleSheet("font-weight: 500; padding: 5px 10px;")
        self.btn_add_row.clicked.connect(lambda: self.add_row())
        bar_layout.addWidget(self.btn_add_row)

        # Hapus Baris
        self.btn_remove_row = QPushButton("➖ Hapus Baris")
        self.btn_remove_row.setStyleSheet("font-weight: 500; padding: 5px 10px;")
        self.btn_remove_row.clicked.connect(self.remove_selected_rows)
        bar_layout.addWidget(self.btn_remove_row)

        bar_layout.addSpacing(10)

        # Impor JSON
        self.btn_import_json = QPushButton("📂 Impor JSON")
        self.btn_import_json.setStyleSheet("padding: 5px 10px;")
        self.btn_import_json.setToolTip("Muat file glosarium dalam format JSON")
        self.btn_import_json.clicked.connect(lambda: self.import_json())
        bar_layout.addWidget(self.btn_import_json)

        # Ekspor JSON
        self.btn_export_json = QPushButton("💾 Ekspor JSON")
        self.btn_export_json.setStyleSheet("padding: 5px 10px;")
        self.btn_export_json.setToolTip("Simpan glosarium aktif ke file JSON")
        self.btn_export_json.clicked.connect(lambda: self.export_json())
        bar_layout.addWidget(self.btn_export_json)

        bar_layout.addSpacing(10)

        # Search Bar
        lbl_search = QLabel("Cari:")
        lbl_search.setStyleSheet("color: #475569; font-weight: 600;")
        bar_layout.addWidget(lbl_search)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter istilah atau terjemahan...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(180)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        bar_layout.addWidget(self.search_input)

        bar_layout.addStretch()

        self.lbl_count = QLabel("0 istilah")
        self.lbl_count.setStyleSheet("color: #64748b; font-weight: 600; font-size: 13px;")
        bar_layout.addWidget(self.lbl_count)

        main_layout.addWidget(top_bar)

        # ---------------------------------------------------------------------
        # 2. Glossary Table Widget
        # ---------------------------------------------------------------------
        self.table_glossary = QTableWidget(0, 4)
        self.table_glossary.setObjectName("glossaryTable")
        self.table_glossary.setHorizontalHeaderLabels([
            "Istilah Sumber",
            "Terjemahan",
            "Catatan Konteks",
            "Peka Huruf Besar",
        ])
        self.table_glossary.setAlternatingRowColors(True)
        self.table_glossary.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_glossary.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table_glossary.verticalHeader().setVisible(False)

        header = self.table_glossary.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table_glossary.setColumnWidth(3, 130)

        self.table_glossary.itemChanged.connect(self._on_table_item_changed)
        main_layout.addWidget(self.table_glossary, stretch=3)

        # ---------------------------------------------------------------------
        # 3. Notes Panel (Prompt instruction & style notes)
        # ---------------------------------------------------------------------
        notes_group = QGroupBox("Catatan Tambahan Gaya & Terjemahan (Prompt Notes)")
        notes_layout = QVBoxLayout(notes_group)
        notes_layout.setContentsMargins(10, 8, 10, 8)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMaximumHeight(85)
        self.notes_edit.setPlaceholderText(
            "Contoh: Gunakan gaya bahasa sastra klasik Victoria. Pertahankan sapaan hormat."
        )
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        notes_layout.addWidget(self.notes_edit)

        main_layout.addWidget(notes_group, stretch=1)

    # =========================================================================
    # Row Operations
    # =========================================================================

    def add_row(
        self,
        source: str = "",
        target: str = "",
        context: str = "",
        case_sensitive: bool = True,
    ) -> int:
        """Add a new row to the glossary table."""
        self._is_populating = True
        row = self.table_glossary.rowCount()
        self.table_glossary.insertRow(row)

        # Col 0: Source Term
        item_src = QTableWidgetItem(source)
        item_src.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table_glossary.setItem(row, 0, item_src)

        # Col 1: Target Translation
        item_tgt = QTableWidgetItem(target)
        item_tgt.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table_glossary.setItem(row, 1, item_tgt)

        # Col 2: Context Note
        item_ctx = QTableWidgetItem(context)
        item_ctx.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table_glossary.setItem(row, 2, item_ctx)

        # Col 3: Case-sensitive Checkbox
        item_cs = QTableWidgetItem()
        item_cs.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item_cs.setCheckState(Qt.Checked if case_sensitive else Qt.Unchecked)
        item_cs.setTextAlignment(Qt.AlignCenter)
        self.table_glossary.setItem(row, 3, item_cs)

        self._is_populating = False
        self._update_count()
        self.sig_glossary_changed.emit()
        return row

    def remove_selected_rows(self) -> None:
        """Remove all currently selected rows from table."""
        selected_rows = sorted(
            list(set(idx.row() for idx in self.table_glossary.selectedIndexes())),
            reverse=True,
        )
        if not selected_rows:
            return

        self._is_populating = True
        for row in selected_rows:
            self.table_glossary.removeRow(row)
        self._is_populating = False

        self._update_count()
        self.sig_glossary_changed.emit()

    def clear_rows(self) -> None:
        """Clear all entries from glossary table."""
        self._is_populating = True
        self.table_glossary.setRowCount(0)
        self._is_populating = False
        self._update_count()
        self.sig_glossary_changed.emit()

    def _update_count(self) -> None:
        """Update label showing total glossary entries."""
        count = self.table_glossary.rowCount()
        self.lbl_count.setText(f"{count} istilah")

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        """Trigger change signal when item edited."""
        if not self._is_populating:
            self.sig_glossary_changed.emit()

    def _on_notes_changed(self) -> None:
        """Trigger change signal when notes text modified."""
        if not self._is_populating:
            self.sig_glossary_changed.emit()

    # =========================================================================
    # Search & Filter
    # =========================================================================

    def _on_search_text_changed(self, text: str) -> None:
        """Filter table rows matching source, translation, or context note."""
        query = text.strip().lower()
        total_rows = self.table_glossary.rowCount()

        if not query:
            for r in range(total_rows):
                self.table_glossary.setRowHidden(r, False)
            self._update_count()
            return

        visible_count = 0
        for r in range(total_rows):
            item_src = self.table_glossary.item(r, 0)
            item_tgt = self.table_glossary.item(r, 1)
            item_ctx = self.table_glossary.item(r, 2)

            src = item_src.text().lower() if item_src else ""
            tgt = item_tgt.text().lower() if item_tgt else ""
            ctx = item_ctx.text().lower() if item_ctx else ""

            matched = (query in src) or (query in tgt) or (query in ctx)
            self.table_glossary.setRowHidden(r, not matched)
            if matched:
                visible_count += 1

        self.lbl_count.setText(f"{visible_count}/{total_rows} istilah")

    # =========================================================================
    # Import / Export JSON
    # =========================================================================

    def import_json(self, file_path: Optional[str | Path] = None) -> bool:
        """Import glossary terms from a JSON file."""
        if file_path is None:
            path_str, _ = QFileDialog.getOpenFileName(
                self,
                "Impor Glosarium JSON",
                "",
                "JSON Files (*.json);;All Files (*)",
            )
            if not path_str:
                return False
            path = Path(path_str)
        else:
            path = Path(file_path)

        if not path.is_file():
            QMessageBox.warning(self, "File Tidak Ditemukan", f"File glosarium tidak ditemukan:\n{path}")
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.clear_rows()
            self._is_populating = True

            notes = ""
            entries: List[Dict[str, Any]] = []

            if isinstance(data, dict):
                notes = str(data.get("notes", ""))
                # Check for detailed entries list
                if "entries" in data and isinstance(data["entries"], list):
                    for item in data["entries"]:
                        if isinstance(item, dict):
                            entries.append({
                                "source": item.get("source", ""),
                                "target": item.get("target", ""),
                                "context": item.get("context", ""),
                                "case_sensitive": bool(item.get("case_sensitive", True)),
                            })
                # Check for terms dict
                elif "terms" in data and isinstance(data["terms"], dict):
                    for src, tgt in data["terms"].items():
                        entries.append({
                            "source": str(src),
                            "target": str(tgt),
                            "context": "",
                            "case_sensitive": True,
                        })
                else:
                    # Flat dict format {src: tgt}
                    for k, v in data.items():
                        if k != "notes" and isinstance(v, (str, int, float)):
                            entries.append({
                                "source": str(k),
                                "target": str(v),
                                "context": "",
                                "case_sensitive": True,
                            })

            elif isinstance(data, list):
                # List of objects
                for item in data:
                    if isinstance(item, dict):
                        src = item.get("source") or item.get("from") or item.get("en") or ""
                        tgt = item.get("target") or item.get("to") or item.get("id") or ""
                        ctx = item.get("context") or item.get("notes") or ""
                        cs = bool(item.get("case_sensitive", True))
                        if src or tgt:
                            entries.append({
                                "source": str(src),
                                "target": str(tgt),
                                "context": str(ctx),
                                "case_sensitive": cs,
                            })

            # Populate table
            for entry in entries:
                self.add_row(
                    source=entry["source"],
                    target=entry["target"],
                    context=entry.get("context", ""),
                    case_sensitive=entry.get("case_sensitive", True),
                )

            self.notes_edit.setPlainText(notes)
            self._is_populating = False
            self._update_count()
            self.sig_glossary_changed.emit()

            logger.info("Imported %d terms from %s", len(entries), path)
            return True

        except Exception as exc:
            self._is_populating = False
            logger.exception("Gagal mengimpor glosarium dari %s: %s", path, exc)
            QMessageBox.critical(self, "Gagal Impor", f"Gagal membaca file JSON glosarium:\n{exc}")
            return False

    def export_json(self, file_path: Optional[str | Path] = None) -> bool:
        """Export current glossary table to a JSON file."""
        if file_path is None:
            path_str, _ = QFileDialog.getSaveFileName(
                self,
                "Ekspor Glosarium JSON",
                "glossary.json",
                "JSON Files (*.json);;All Files (*)",
            )
            if not path_str:
                return False
            path = Path(path_str)
        else:
            path = Path(file_path)

        try:
            terms: Dict[str, str] = {}
            entries: List[Dict[str, Any]] = []

            for r in range(self.table_glossary.rowCount()):
                item_src = self.table_glossary.item(r, 0)
                item_tgt = self.table_glossary.item(r, 1)
                item_ctx = self.table_glossary.item(r, 2)
                item_cs = self.table_glossary.item(r, 3)

                src = item_src.text().strip() if item_src else ""
                tgt = item_tgt.text().strip() if item_tgt else ""
                ctx = item_ctx.text().strip() if item_ctx else ""
                cs = (item_cs.checkState() == Qt.Checked) if item_cs else True

                if src:
                    terms[src] = tgt
                    entries.append({
                        "source": src,
                        "target": tgt,
                        "context": ctx,
                        "case_sensitive": cs,
                    })

            data = {
                "terms": terms,
                "notes": self.notes_edit.toPlainText().strip(),
                "entries": entries,
            }

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info("Exported %d terms to %s", len(terms), path)
            return True

        except Exception as exc:
            logger.exception("Gagal mengekspor glosarium ke %s: %s", path, exc)
            QMessageBox.critical(self, "Gagal Ekspor", f"Gagal menyimpan file glosarium:\n{exc}")
            return False

    # =========================================================================
    # Glossary Backend Synchronization
    # =========================================================================

    def get_entries(self) -> List[Dict[str, Any]]:
        """Return list of all glossary entries formatted as dictionaries."""
        entries = []
        for r in range(self.table_glossary.rowCount()):
            item_src = self.table_glossary.item(r, 0)
            item_tgt = self.table_glossary.item(r, 1)
            item_ctx = self.table_glossary.item(r, 2)
            item_cs = self.table_glossary.item(r, 3)

            src = item_src.text().strip() if item_src else ""
            tgt = item_tgt.text().strip() if item_tgt else ""
            ctx = item_ctx.text().strip() if item_ctx else ""
            cs = (item_cs.checkState() == Qt.Checked) if item_cs else True

            if src:
                entries.append({
                    "source": src,
                    "target": tgt,
                    "context": ctx,
                    "case_sensitive": cs,
                })
        return entries

    def get_glossary(self) -> Glossary:
        """Construct and return a core Glossary instance for the translation runner."""
        terms: Dict[str, str] = {}
        for r in range(self.table_glossary.rowCount()):
            item_src = self.table_glossary.item(r, 0)
            item_tgt = self.table_glossary.item(r, 1)
            src = item_src.text().strip() if item_src else ""
            tgt = item_tgt.text().strip() if item_tgt else ""
            if src:
                terms[src] = tgt

        notes = self.notes_edit.toPlainText().strip()
        return Glossary(terms=terms, notes=notes)

    def load_glossary(self, glossary: Glossary) -> None:
        """Populate the table from an existing core Glossary instance."""
        self.clear_rows()
        self._is_populating = True
        for src, tgt in sorted(glossary.terms.items()):
            self.add_row(source=src, target=tgt, context="", case_sensitive=True)
        self.notes_edit.setPlainText(glossary.notes)
        self._is_populating = False
        self._update_count()
        self.sig_glossary_changed.emit()


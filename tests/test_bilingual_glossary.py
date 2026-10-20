"""Unit tests for Tab 2 (Bilingual Editor) and Tab 3 (Glossary Manager)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# Ensure headless offscreen platform
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(scope="session")
def qapp():
    """Fixture ensuring a single QApplication instance exists for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_epub_path():
    """Path to sample EPUB fixture."""
    path = Path("tests/fixtures/sample_novel.epub")
    assert path.is_file(), f"Fixture not found at {path}"
    return path


@pytest.fixture
def sample_glossary_json_path():
    """Path to sample glossary JSON fixture."""
    path = Path("tests/fixtures/glossary.json")
    assert path.is_file(), f"Fixture not found at {path}"
    return path


# =============================================================================
# TabBilingual Tests
# =============================================================================

def test_tab_bilingual_initialization(qapp):
    """Test bilingual editor widget initialization and controls."""
    from gui.tab_bilingual import TabBilingual

    tab = TabBilingual()
    assert tab.combo_chapters is not None
    assert tab.btn_refresh is not None
    assert tab.search_input is not None
    assert tab.btn_save_cache is not None
    assert tab.table_segments is not None

    assert tab.table_segments.columnCount() == 3
    headers = [tab.table_segments.horizontalHeaderItem(i).text() for i in range(3)]
    assert "ID" in headers[0]
    assert "Teks Asli" in headers[1]
    assert "Teks Terjemahan" in headers[2]


def test_tab_bilingual_load_book(qapp, sample_epub_path):
    """Test loading EPUB book into TabBilingual."""
    from gui.tab_bilingual import TabBilingual

    tab = TabBilingual()
    tab.load_book(sample_epub_path)

    # Chapters should be populated in combo box
    assert tab.combo_chapters.count() > 0
    assert "chap1.xhtml" in tab.combo_chapters.itemText(0)

    # Table segments should be populated with first chapter's segments
    row_count = tab.table_segments.rowCount()
    assert row_count > 0

    # Column 0 (ID) and Column 1 (Source) must be read-only
    item_id = tab.table_segments.item(0, 0)
    item_src = tab.table_segments.item(0, 1)
    assert not (item_id.flags() & Qt.ItemIsEditable)
    assert not (item_src.flags() & Qt.ItemIsEditable)

    # Column 2 (Translation) must be editable
    item_tgt = tab.table_segments.item(0, 2)
    assert bool(item_tgt.flags() & Qt.ItemIsEditable)


def test_tab_bilingual_search_filter(qapp, sample_epub_path):
    """Test filtering table rows using search input."""
    from gui.tab_bilingual import TabBilingual

    tab = TabBilingual()
    tab.load_book(sample_epub_path)
    total_rows = tab.table_segments.rowCount()
    assert total_rows > 1

    # Search for a term likely present in chapter 1
    # First get a word from the first row's source text
    first_src = tab.table_segments.item(0, 1).text()
    word = first_src.split()[0] if first_src else "a"

    tab.search_input.setText(word)
    # Check that visible rows match
    visible_count = sum(
        1 for r in range(total_rows) if not tab.table_segments.isRowHidden(r)
    )
    assert visible_count > 0
    assert visible_count <= total_rows

    # Search for an impossible string
    tab.search_input.setText("xyzNonExistent998877")
    visible_none = sum(
        1 for r in range(total_rows) if not tab.table_segments.isRowHidden(r)
    )
    assert visible_none == 0

    # Clear search
    tab.search_input.setText("")
    visible_all = sum(
        1 for r in range(total_rows) if not tab.table_segments.isRowHidden(r)
    )
    assert visible_all == total_rows


def test_tab_bilingual_save_to_cache(qapp, sample_epub_path, tmp_path):
    """Test editing translation in table and saving to CheckpointManager cache."""
    from checkpoint import CheckpointManager
    from gui.tab_bilingual import TabBilingual

    tab = TabBilingual()
    # Configure custom checkpoint directory to avoid polluting real cache
    tab.config.checkpoint_dir = tmp_path / "test_cache"
    tab.load_book(sample_epub_path)

    assert tab.table_segments.rowCount() > 0

    # Edit the first row translation
    seg_0_id = tab.table_segments.item(0, 0).text()
    edited_translation = "Ini adalah hasil editan manual pengguna."
    tab.table_segments.item(0, 2).setText(edited_translation)

    # Save to cache quietly (no modal message box)
    saved_count = tab.save_changes_to_cache(quiet=True)
    assert saved_count >= 1

    # Verify CheckpointManager has the updated translation
    epub_hash = CheckpointManager.compute_file_hash(sample_epub_path)
    checkpoint = CheckpointManager(
        epub_hash=epub_hash,
        model=tab.config.model,
        glossary_hash="none",
        checkpoint_dir=tab.config.checkpoint_dir,
    )
    zip_path = tab.combo_chapters.currentData()
    assert zip_path in checkpoint.chapters
    ch_rec = checkpoint.chapters[zip_path]

    # Find the batch containing seg_0_id
    found_text = None
    for batch in ch_rec.batches.values():
        if seg_0_id in batch.translated_texts:
            found_text = batch.translated_texts[seg_0_id]
            break

    assert found_text == edited_translation

    # Verify reload fetches from cache
    tab.reload_current_chapter()
    assert tab.table_segments.item(0, 2).text() == edited_translation


# =============================================================================
# TabGlossary Tests
# =============================================================================

def test_tab_glossary_initialization(qapp):
    """Test glossary tab initialization and controls."""
    from gui.tab_glossary import TabGlossary

    tab = TabGlossary()
    assert tab.btn_add_row is not None
    assert tab.btn_remove_row is not None
    assert tab.btn_import_json is not None
    assert tab.btn_export_json is not None
    assert tab.search_input is not None
    assert tab.table_glossary is not None
    assert tab.notes_edit is not None

    assert tab.table_glossary.columnCount() == 4
    headers = [tab.table_glossary.horizontalHeaderItem(i).text() for i in range(4)]
    assert "Istilah Sumber" in headers[0]
    assert "Terjemahan" in headers[1]
    assert "Catatan Konteks" in headers[2]
    assert "Peka Huruf Besar" in headers[3]


def test_tab_glossary_add_and_remove_rows(qapp):
    """Test adding and removing rows in TabGlossary."""
    from gui.tab_glossary import TabGlossary

    tab = TabGlossary()
    assert tab.table_glossary.rowCount() == 0

    # Add row
    r1 = tab.add_row(
        source="Forgotten Kingdom",
        target="Kerajaan Terlupakan",
        context="Nama tempat fiksi",
        case_sensitive=True,
    )
    assert r1 == 0
    assert tab.table_glossary.rowCount() == 1

    item_src = tab.table_glossary.item(0, 0)
    item_tgt = tab.table_glossary.item(0, 1)
    item_ctx = tab.table_glossary.item(0, 2)
    item_cs = tab.table_glossary.item(0, 3)

    assert item_src.text() == "Forgotten Kingdom"
    assert item_tgt.text() == "Kerajaan Terlupakan"
    assert item_ctx.text() == "Nama tempat fiksi"
    assert item_cs.checkState() == Qt.Checked

    # Add second row
    tab.add_row(
        source="wand",
        target="tongkat sihir",
        context="",
        case_sensitive=False,
    )
    assert tab.table_glossary.rowCount() == 2
    assert tab.table_glossary.item(1, 3).checkState() == Qt.Unchecked

    # Test get_glossary
    tab.notes_edit.setPlainText("Gaya bahasa klasik.")
    glossary = tab.get_glossary()
    assert len(glossary) == 2
    assert glossary.terms["Forgotten Kingdom"] == "Kerajaan Terlupakan"
    assert glossary.terms["wand"] == "tongkat sihir"
    assert glossary.notes == "Gaya bahasa klasik."

    # Remove selected row
    tab.table_glossary.selectRow(0)
    tab.remove_selected_rows()
    assert tab.table_glossary.rowCount() == 1
    assert tab.table_glossary.item(0, 0).text() == "wand"

    # Clear rows
    tab.clear_rows()
    assert tab.table_glossary.rowCount() == 0


def test_tab_glossary_import_export_json(qapp, tmp_path, sample_glossary_json_path):
    """Test importing and exporting glossary files."""
    from gui.tab_glossary import TabGlossary

    tab = TabGlossary()

    # 1. Import fixture glossary.json
    success = tab.import_json(sample_glossary_json_path)
    assert success is True
    assert tab.table_glossary.rowCount() == 5
    assert tab.notes_edit.toPlainText().startswith("Gunakan gaya bahasa sastra")

    entries = tab.get_entries()
    assert len(entries) == 5
    src_terms = [e["source"] for e in entries]
    assert "London" in src_terms
    assert "Clara" in src_terms

    # Add a custom context note to one entry
    tab.table_glossary.item(0, 2).setText("Tokoh utama")

    # 2. Export to temporary file
    export_file = tmp_path / "exported_glossary.json"
    exp_ok = tab.export_json(export_file)
    assert exp_ok is True
    assert export_file.is_file()

    # Verify JSON structure
    with open(export_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "terms" in data
    assert "notes" in data
    assert "entries" in data
    assert len(data["entries"]) == 5

    # 3. Round-trip import from the newly exported file
    tab2 = TabGlossary()
    tab2.import_json(export_file)
    assert tab2.table_glossary.rowCount() == 5
    assert tab2.table_glossary.item(0, 2).text() == "Tokoh utama"
    assert tab2.notes_edit.toPlainText() == tab.notes_edit.toPlainText()


def test_tab_glossary_search_filter(qapp, sample_glossary_json_path):
    """Test filtering terms in glossary table."""
    from gui.tab_glossary import TabGlossary

    tab = TabGlossary()
    tab.import_json(sample_glossary_json_path)
    total_rows = tab.table_glossary.rowCount()
    assert total_rows == 5

    # Filter for London
    tab.search_input.setText("london")
    visible = sum(
        1 for r in range(total_rows) if not tab.table_glossary.isRowHidden(r)
    )
    assert visible == 1

    # Filter for non-existent term
    tab.search_input.setText("zxcvbnm12345")
    visible_none = sum(
        1 for r in range(total_rows) if not tab.table_glossary.isRowHidden(r)
    )
    assert visible_none == 0

    # Reset filter
    tab.search_input.setText("")
    visible_all = sum(
        1 for r in range(total_rows) if not tab.table_glossary.isRowHidden(r)
    )
    assert visible_all == 5


# =============================================================================
# MainWindow Integration Tests
# =============================================================================

def test_main_window_tabs_integration(qapp, sample_epub_path, sample_glossary_json_path):
    """Test integration of TabBilingual and TabGlossary within MainWindow."""
    from gui.main_window import MainWindow
    from gui.tab_bilingual import TabBilingual
    from gui.tab_glossary import TabGlossary

    window = MainWindow()

    # Tab 2 and Tab 3 must be instances of TabBilingual and TabGlossary
    assert isinstance(window.tab_bilingual, TabBilingual)
    assert isinstance(window.tab_glossary, TabGlossary)
    assert window.tab_editor is window.tab_bilingual

    # Load EPUB book into MainWindow
    window.load_epub(sample_epub_path)

    # Verify TabBilingual synchronized chapter list
    assert window.tab_bilingual.combo_chapters.count() > 0
    assert window.tab_bilingual.table_segments.rowCount() > 0

    # Import glossary into TabGlossary
    window.tab_glossary.import_json(sample_glossary_json_path)
    assert window.tab_glossary.table_glossary.rowCount() > 0

    # Mock TranslationWorker to test passing glossary to worker
    with patch("gui.main_window.TranslationWorker") as mock_worker_cls:
        mock_worker = MagicMock()
        mock_worker_cls.return_value = mock_worker

        window._on_start_translation()

        # Check worker initialized with glossary from tab_glossary
        mock_worker_cls.assert_called_once()
        call_kwargs = mock_worker_cls.call_args[1]
        passed_glossary = call_kwargs.get("glossary")

        assert passed_glossary is not None
        assert "London" in passed_glossary.terms
        assert len(passed_glossary.terms) == 5


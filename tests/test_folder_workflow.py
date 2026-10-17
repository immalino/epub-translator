"""Integration tests for input/output folder workflow."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tests.create_fixture import create_fixture_epub
from epub_translate import main
from validator import EPUBValidator


def test_empty_input_folder_exits_cleanly(tmp_path: Path, monkeypatch):
    in_dir = tmp_path / "input"
    out_dir = tmp_path / "output"
    in_dir.mkdir()
    out_dir.mkdir()

    monkeypatch.setattr(
        "sys.argv",
        [
            "epub_translate.py",
            "--input-dir",
            str(in_dir),
            "--output-dir",
            str(out_dir),
        ],
    )

    exit_code = main()
    assert exit_code == 0


def test_folder_workflow_translates_to_same_name_in_output(tmp_path: Path, monkeypatch):
    in_dir = tmp_path / "input"
    out_dir = tmp_path / "output"
    in_dir.mkdir()
    out_dir.mkdir()

    book1 = in_dir / "my_fantasy_novel.epub"
    create_fixture_epub(book1)

    expected_output = out_dir / "my_fantasy_novel.epub"
    assert not expected_output.exists()

    # Mock OllamaTranslator
    def mock_translate_batch(self, batch):
        return {seg.id: f"Terjemahan lokal {seg.id}" for seg in batch}

    with patch("translator.OllamaTranslator.check_connection", return_value=True), \
         patch("translator.OllamaTranslator.translate_batch", mock_translate_batch):

        monkeypatch.setattr(
            "sys.argv",
            [
                "epub_translate.py",
                "--input-dir",
                str(in_dir),
                "--output-dir",
                str(out_dir),
                "--provider",
                "ollama",
                "--checkpoint-dir",
                str(tmp_path / ".cache"),
            ],
        )

        exit_code = main()

    assert exit_code == 0
    assert expected_output.is_file()

    # Validate output EPUB
    val = EPUBValidator(expected_output)
    report = val.validate(run_calibre=False)
    assert report.is_valid, f"Output EPUB validation failed: {report.errors}"


def test_specific_file_defaults_to_output_folder_with_same_name(tmp_path: Path, monkeypatch):
    in_dir = tmp_path / "input"
    out_dir = tmp_path / "output"
    in_dir.mkdir()
    out_dir.mkdir()

    book_file = in_dir / "scifi_story.epub"
    create_fixture_epub(book_file)

    expected_output = out_dir / "scifi_story.epub"

    def mock_translate_batch(self, batch):
        return {seg.id: f"Terjemahan {seg.id}" for seg in batch}

    with patch("translator.OllamaTranslator.check_connection", return_value=True), \
         patch("translator.OllamaTranslator.translate_batch", mock_translate_batch):

        monkeypatch.setattr(
            "sys.argv",
            [
                "epub_translate.py",
                str(book_file),
                "--output-dir",
                str(out_dir),
                "--provider",
                "ollama",
                "--checkpoint-dir",
                str(tmp_path / ".cache"),
            ],
        )

        exit_code = main()

    assert exit_code == 0
    assert expected_output.is_file()


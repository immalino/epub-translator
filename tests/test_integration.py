"""End-to-end integration tests for EPUB translation pipeline."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tests.create_fixture import create_fixture_epub
from epub_translate import main
from epub_parser import EPUBParser
from validator import EPUBValidator


def test_full_translation_pipeline(tmp_path: Path, monkeypatch):
    src_epub = tmp_path / "sample_novel.epub"
    out_epub = tmp_path / "sample_novel_id.epub"
    glossary_path = Path("tests/fixtures/glossary.json")
    create_fixture_epub(src_epub)

    # Mock Gemini client returning realistic Indonesian translations
    def mock_generate(*args, **kwargs):
        config_arg = kwargs.get("config")
        contents_str = kwargs.get("contents", "")

        # Extract IDs from the prompt
        import re
        ids = re.findall(r'"id":\s*"([^"]+)"', contents_str)

        translations = []
        for seg_id in ids:
            translations.append(
                {
                    "id": seg_id,
                    "text": f"Terjemahan bahasa Indonesia untuk segmen {seg_id} dengan <em>gaya novel</em>.",
                }
            )

        resp = MagicMock()
        resp.text = json.dumps({"translations": translations})
        return resp

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate

    cli_args = [
        "epub_translate.py",
        str(src_epub),
        "-o",
        str(out_epub),
        "--api-keys",
        "mock_key_1",
        "mock_key_2",
        "--glossary",
        str(glossary_path),
        "--translate-metadata",
        "--checkpoint-dir",
        str(tmp_path / ".cache"),
    ]

    monkeypatch.setattr("sys.argv", cli_args)

    with patch("google.genai.Client", return_value=mock_client):
        exit_code = main()

    assert exit_code == 0
    assert out_epub.is_file()

    # Validate output with EPUBValidator
    report = EPUBValidator(out_epub).validate(run_calibre=False)
    assert report.is_valid, f"Validation failed with errors: {report.errors}"

    # Verify translated contents
    book = EPUBParser(out_epub).parse()
    assert book.language == "id"

    # Read chapter 1 content
    chap1_bytes = EPUBParser(out_epub).read_zip_file("OEBPS/chap1.xhtml")
    chap1_text = chap1_bytes.decode("utf-8")
    assert "Terjemahan bahasa Indonesia" in chap1_text
    assert "<em>gaya novel</em>" in chap1_text


def test_chapter_selective_translation(tmp_path: Path, monkeypatch):
    src_epub = tmp_path / "sample.epub"
    out_epub = tmp_path / "sample_chap1_only.epub"
    create_fixture_epub(src_epub)

    def mock_generate(*args, **kwargs):
        import re
        contents_str = kwargs.get("contents", "")
        ids = re.findall(r'"id":\s*"([^"]+)"', contents_str)
        return MagicMock(text=json.dumps({"translations": [{"id": i, "text": f"Terjemahan {i}"} for i in ids]}))

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate

    cli_args = [
        "epub_translate.py",
        str(src_epub),
        "-o",
        str(out_epub),
        "--api-keys",
        "mock_key",
        "--chapter",
        "1",
        "--checkpoint-dir",
        str(tmp_path / ".cache2"),
    ]

    monkeypatch.setattr("sys.argv", cli_args)

    with patch("google.genai.Client", return_value=mock_client):
        exit_code = main()

    assert exit_code == 0
    assert out_epub.is_file()

    # Chap 1 should be modified, Chap 2 should remain original English
    p = EPUBParser(out_epub)
    c1 = p.read_zip_file("OEBPS/chap1.xhtml").decode("utf-8")
    c2 = p.read_zip_file("OEBPS/chap2.xhtml").decode("utf-8")

    assert "Terjemahan" in c1
    assert "Midnight arrived" in c2  # Original English


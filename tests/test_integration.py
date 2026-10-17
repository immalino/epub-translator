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


def test_dry_run_cli(tmp_path: Path, monkeypatch, capsys):
    src_epub = tmp_path / "sample.epub"
    create_fixture_epub(src_epub)

    cli_args = [
        "epub_translate.py",
        str(src_epub),
        "--dry-run",
        "--api-keys",
        "mock_key",
    ]
    monkeypatch.setattr("sys.argv", cli_args)

    exit_code = main()
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "DRY RUN & ESTIMASI KUOTA" in captured
    assert "ESTIMASI PERMINTAAN API" in captured
    assert "Limit RPM" in captured
    assert "Limit RPD" in captured


def test_resume_workflow_skips_completed_batches(tmp_path: Path, monkeypatch):
    from google.genai.errors import ClientError

    src_epub = tmp_path / "sample.epub"
    out_epub = tmp_path / "sample_out.epub"
    cache_dir = tmp_path / ".cache_resume"
    create_fixture_epub(src_epub)

    call_count = 0
    generated_ids = []

    def mock_generate_first_pass(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        contents_str = kwargs.get("contents", "")
        import re
        ids = re.findall(r'"id":\s*"([^"]+)"', contents_str)
        generated_ids.extend(ids)

        if call_count == 1:
            # Batch 1 succeeds
            return MagicMock(text=json.dumps({"translations": [{"id": i, "text": f"Terjemahan {i}"} for i in ids]}))
        else:
            # Batch 2 hits daily limit
            raise ClientError(
                429,
                {
                    "error": {
                        "code": 429,
                        "message": "Resource exhausted",
                        "status": "RESOURCE_EXHAUSTED",
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                "metadata": {
                                    "quotaId": "GenerateContentRequestsPerDayPerProjectPerRegion",
                                    "quotaLimit": "1500",
                                    "model": "gemini-2.5-flash",
                                },
                            }
                        ],
                    }
                },
            )

    mock_client1 = MagicMock()
    mock_client1.models.generate_content.side_effect = mock_generate_first_pass

    cli_args_pass1 = [
        "epub_translate.py",
        str(src_epub),
        "-o",
        str(out_epub),
        "--api-keys",
        "mock_key",
        "--batch-size",
        "1",  # Forces multiple batches
        "--checkpoint-dir",
        str(cache_dir),
    ]
    monkeypatch.setattr("sys.argv", cli_args_pass1)

    with patch("google.genai.Client", return_value=mock_client1):
        exit_code_1 = main()

    # Pass 1 should exit with code 2 on daily quota limit
    assert exit_code_1 == 2
    first_pass_calls = call_count
    assert first_pass_calls == 2

    # Now Pass 2 with --resume after "quota recovery":
    call_count_pass2 = 0
    pass2_called_ids = []

    def mock_generate_second_pass(*args, **kwargs):
        nonlocal call_count_pass2
        call_count_pass2 += 1
        contents_str = kwargs.get("contents", "")
        import re
        ids = re.findall(r'"id":\s*"([^"]+)"', contents_str)
        pass2_called_ids.extend(ids)
        return MagicMock(text=json.dumps({"translations": [{"id": i, "text": f"Terjemahan {i}"} for i in ids]}))

    mock_client2 = MagicMock()
    mock_client2.models.generate_content.side_effect = mock_generate_second_pass

    cli_args_pass2 = [
        "epub_translate.py",
        str(src_epub),
        "-o",
        str(out_epub),
        "--api-keys",
        "mock_key",
        "--batch-size",
        "1",
        "--resume",
        "--checkpoint-dir",
        str(cache_dir),
    ]
    monkeypatch.setattr("sys.argv", cli_args_pass2)

    with patch("google.genai.Client", return_value=mock_client2):
        exit_code_2 = main()

    assert exit_code_2 == 0
    assert out_epub.is_file()
    # Total segments across 3 chapters, TOC, and nav were 17.
    # Pass 1 completed 1 batch (b001 with s0001 in chap1).
    # Pass 2 resumed, skipped b001 of chap1, and completed the remaining 16 batches starting with s0002.
    assert call_count_pass2 == 16
    assert pass2_called_ids[0] == "s0002"



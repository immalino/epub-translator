"""Tests for EPUB validator, detecting valid and corrupted archives."""

import zipfile
from pathlib import Path
import pytest
from validator import EPUBValidator
from tests.create_fixture import create_fixture_epub


def test_validator_valid_epub(tmp_path: Path):
    epub_path = tmp_path / "valid.epub"
    create_fixture_epub(epub_path)

    val = EPUBValidator(epub_path)
    report = val.validate(run_calibre=False)

    assert report.is_valid
    assert len(report.errors) == 0
    assert any("mimetype" in c for c in report.checks_passed)


def test_validator_corrupted_mimetype(tmp_path: Path):
    corrupt_path = tmp_path / "corrupt.epub"
    # Create invalid zip where mimetype is not first
    with zipfile.ZipFile(corrupt_path, "w") as zf:
        zf.writestr("other.txt", b"something")
        zf.writestr("mimetype", b"application/epub+zip")

    val = EPUBValidator(corrupt_path)
    report = val.validate(run_calibre=False)

    assert not report.is_valid
    assert any("mimetype" in e for e in report.errors)


def test_validator_corrupted_xml(tmp_path: Path):
    corrupt_path = tmp_path / "bad_xml.epub"
    create_fixture_epub(corrupt_path)

    # Overwrite chap1 with broken xml
    with zipfile.ZipFile(corrupt_path, "a") as zf:
        zf.writestr("OEBPS/chap1.xhtml", b"<html unclosed")

    val = EPUBValidator(corrupt_path)
    report = val.validate(run_calibre=False)

    assert not report.is_valid
    assert any("Sintaks XML tidak valid" in e for e in report.errors)


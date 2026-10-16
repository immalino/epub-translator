"""Tests for EPUB parsing, chapter filtering, and standard-compliant EPUB packaging."""

import zipfile
from pathlib import Path
import pytest
from epub_parser import EPUBParser, EPUBBuilder, parse_chapter_filter
from tests.create_fixture import create_fixture_epub


def test_epub_parser_and_filter(tmp_path: Path):
    fixture_path = tmp_path / "test.epub"
    create_fixture_epub(fixture_path)

    parser = EPUBParser(fixture_path)
    book = parser.parse()

    assert book.title == "The Chronicles of Finch"
    assert book.language == "en"
    assert len(book.spine) == 3
    assert book.spine[0].manifest_item.href == "chap1.xhtml"
    assert book.spine[1].manifest_item.href == "chap2.xhtml"
    assert book.spine[2].manifest_item.href == "chap3.xhtml"

    # Test chapter filtering
    filtered_range = parse_chapter_filter("1-2", book.spine)
    assert len(filtered_range) == 2
    assert [x.index for x in filtered_range] == [1, 2]

    filtered_comma = parse_chapter_filter("1,3", book.spine)
    assert len(filtered_comma) == 2
    assert [x.index for x in filtered_comma] == [1, 3]

    filtered_name = parse_chapter_filter("chap2.xhtml", book.spine)
    assert len(filtered_name) == 1
    assert filtered_name[0].index == 2


def test_epub_builder_mimetype_and_language(tmp_path: Path):
    src_epub = tmp_path / "src.epub"
    out_epub = tmp_path / "out.epub"
    create_fixture_epub(src_epub)

    parser = EPUBParser(src_epub)
    book = parser.parse()

    modified = {
        "OEBPS/chap1.xhtml": b"<?xml version=\"1.0\" encoding=\"utf-8\"?><html xmlns=\"http://www.w3.org/1999/xhtml\"><body><p>Terjemahan</p></body></html>"
    }

    EPUBBuilder.build(
        source_epub=src_epub,
        output_epub=out_epub,
        book=book,
        modified_files=modified,
        target_lang="id",
        new_title="Kronik Finch",
    )

    assert out_epub.is_file()

    # Verify mimetype is first and uncompressed
    with zipfile.ZipFile(out_epub, "r") as zf:
        namelist = zf.namelist()
        assert namelist[0] == "mimetype"
        m_info = zf.getinfo("mimetype")
        assert m_info.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"

        # Check modified file
        assert zf.read("OEBPS/chap1.xhtml") == modified["OEBPS/chap1.xhtml"]

        # Check unmodified file preserved
        assert len(zf.read("OEBPS/images/cover.png")) > 0

    # Parse output to verify language update
    out_book = EPUBParser(out_epub).parse()
    assert out_book.language == "id"
    assert out_book.title == "Kronik Finch"


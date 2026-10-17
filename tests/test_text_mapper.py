"""Tests for XHTML parsing, inline tag preservation, entity handling, and reconstruction."""

import pytest
from lxml import etree
from text_mapper import XHTMLTextMapper, sanitize_xml_entities, clean_inner_for_prompt


def test_sanitize_xml_entities():
    # Unescaped & should become &amp;
    assert sanitize_xml_entities("Salt & Pepper") == "Salt &amp; Pepper"
    # Already escaped entities should remain unchanged
    assert sanitize_xml_entities("Tom &amp; Jerry &lt; 5") == "Tom &amp; Jerry &lt; 5"


def test_text_mapper_extraction_and_inline_preservation():
    xhtml = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Test Doc</title></head>
<body>
  <div class="main">
    <h1>Chapter 1</h1>
    <p class="dialogue">"Wait!" she cried, looking at the <a href="map.xhtml"><em>old map</em></a> carefully.</p>
    <p>Ordinary paragraph without tags.</p>
  </div>
</body>
</html>"""

    mapper = XHTMLTextMapper()
    tree, segments = mapper.extract_segments(xhtml)

    assert len(segments) == 3
    # Check title, h1, and paragraphs
    assert segments[0].plain_text == "Chapter 1"
    assert "<em>old map</em>" in segments[1].inner_html
    assert '<a href="map.xhtml">' in segments[1].inner_html

    # Apply translations
    translations = {
        segments[0].id: "Bab 1",
        segments[1].id: '"Tunggu!" serunya, menatap <a href="map.xhtml"><em>peta kuno</em></a> itu dengan saksama.',
        segments[2].id: "Paragraf biasa tanpa tag.",
    }

    out_bytes = mapper.apply_translations(tree, segments, translations)
    out_xml = out_bytes.decode("utf-8")

    assert "Bab 1" in out_xml
    assert 'menatap <a href="map.xhtml"><em>peta kuno</em></a>' in out_xml
    assert 'class="dialogue"' in out_xml

    # Verify output is well-formed XML
    re_parsed = etree.fromstring(out_bytes)
    assert re_parsed is not None


def test_text_mapper_broken_tag_recovery():
    xhtml = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<body>
  <p>Some text</p>
</body>
</html>"""

    mapper = XHTMLTextMapper()
    tree, segments = mapper.extract_segments(xhtml)

    # Simulate translation returning unclosed inline tag
    translations = {
        segments[0].id: "Teks dengan <em>tag tidak tertutup"
    }

    out_bytes = mapper.apply_translations(tree, segments, translations)
    re_parsed = etree.fromstring(out_bytes)
    assert re_parsed is not None


def test_text_mapper_html5_unclosed_void_tags_in_head():
    """Verify that HTML5-style unclosed <meta> and <link> tags in <head> do not swallow <body> elements."""
    html5_doc = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8">
    <title>HTML5 Novel</title>
    <link href="style.css" rel="stylesheet" type="text/css">
  </head>
  <body>
    <h1>Chapter 1</h1>
    <p>This is paragraph 1.</p>
    <p>This is paragraph 2.</p>
  </body>
</html>"""

    mapper = XHTMLTextMapper()
    tree, segments = mapper.extract_segments(html5_doc)

    assert len(segments) == 3
    assert segments[0].plain_text == "Chapter 1"
    assert segments[1].plain_text == "This is paragraph 1."
    assert segments[2].plain_text == "This is paragraph 2."

    # Test serialization maintains valid structure
    translations = {s.id: f"Terjemahan: {s.plain_text}" for s in segments}
    out_bytes = mapper.apply_translations(tree, segments, translations)
    re_parsed = etree.fromstring(out_bytes)
    assert re_parsed is not None


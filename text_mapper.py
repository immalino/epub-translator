"""XHTML text extraction and structured DOM mapping.

Extracts reader-visible text and block elements from XHTML documents while
preserving inline HTML tags (<em>, <strong>, <a>, <span>), attributes, and
nesting structure. Reconstructs valid, well-formed XHTML from translated fragments.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
from lxml import etree, html

logger = logging.getLogger(__name__)

XHTML_NS = "http://www.w3.org/1999/xhtml"
NAMESPACES = {"xhtml": XHTML_NS}

# Tags that represent block-level reader text
BLOCK_TAGS: Set[str] = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "li",
    "figcaption",
    "dd",
    "dt",
    "th",
    "td",
    "caption",
    "title",
}

# Tags that should NEVER be translated
SKIP_TAGS: Set[str] = {
    "head",
    "script",
    "style",
    "svg",
    "math",
    "pre",
    "code",
}


@dataclass
class TranslatableSegment:
    """Represents a translatable chunk of text/HTML from an XHTML element."""

    id: str
    inner_html: str
    plain_text: str
    char_count: int
    element: etree._Element


def local_tag_name(element: etree._Element) -> str:
    """Return tag name without XML namespace."""
    if not isinstance(element.tag, str):
        return ""
    if "}" in element.tag:
        return element.tag.split("}", 1)[1].lower()
    return element.tag.lower()


def clean_inner_for_prompt(inner_xml: str) -> str:
    """Strip redundant xmlns declarations from inner snippet to save prompt tokens."""
    return re.sub(r'\s+xmlns(?::[a-zA-Z0-9_-]+)?=\"[^\"]*\"', '', inner_xml)


def sanitize_xml_entities(s: str) -> str:
    """Replace unescaped ampersands with &amp; without breaking existing entities."""
    return re.sub(r'&(?!(?:[a-zA-Z0-9]+|#[0-9]+|#x[0-9a-fA-F]+);)', '&amp;', s)


class XHTMLTextMapper:
    """Parses and reconstructs XHTML documents with preserved structure."""

    def __init__(self, translate_titles: bool = True) -> None:
        self.translate_titles = translate_titles

    def extract_segments(self, xhtml_content: bytes | str) -> Tuple[etree._Element, List[TranslatableSegment]]:
        """Parse XHTML and extract all reader-visible translatable segments."""
        if isinstance(xhtml_content, str):
            raw_bytes = xhtml_content.encode("utf-8")
        else:
            raw_bytes = xhtml_content

        parser = etree.XMLParser(recover=True, remove_blank_text=False)
        try:
            tree = etree.fromstring(raw_bytes, parser=parser)
        except Exception as e:
            # Fallback to HTML parser if XML parser fails completely
            tree = html.fromstring(raw_bytes)

        segments: List[TranslatableSegment] = []
        seg_index = 1

        # Traverse elements looking for candidate blocks
        for elem in tree.iter():
            tag = local_tag_name(elem)

            # Skip non-content tags or ignored classes
            if tag in SKIP_TAGS:
                continue

            # Check if this element or an ancestor is in skip tags
            ancestor_tags = {local_tag_name(anc) for anc in elem.iterancestors()}
            if any(anc in SKIP_TAGS for anc in ancestor_tags):
                continue

            # Skip title if translate_titles is False
            if tag == "title" and not self.translate_titles:
                continue

            # Check if element is a translatable candidate
            is_block = tag in BLOCK_TAGS
            is_leaf_div = (tag == "div" and not any(local_tag_name(c) in BLOCK_TAGS for c in elem))

            if is_block or is_leaf_div:
                # If a block element contains child block elements (e.g. blockquote containing <p>),
                # skip the parent and let the child blocks be extracted
                has_child_blocks = any(local_tag_name(c) in BLOCK_TAGS for c in elem)
                if has_child_blocks and tag != "title":
                    continue

                # Extract plain text to see if there is any readable content
                plain = "".join(elem.itertext()).strip()
                if not plain:
                    continue

                # Extract inner content including inline markup
                inner_parts = []
                if elem.text:
                    inner_parts.append(elem.text)
                for child in elem:
                    inner_parts.append(etree.tostring(child, encoding="unicode"))
                inner_html = "".join(inner_parts)
                clean_inner = clean_inner_for_prompt(inner_html).strip()

                if not clean_inner:
                    continue

                seg_id = f"s{seg_index:04d}"
                seg_index += 1
                segment = TranslatableSegment(
                    id=seg_id,
                    inner_html=clean_inner,
                    plain_text=plain,
                    char_count=len(plain),
                    element=elem,
                )
                segments.append(segment)

        return tree, segments

    def apply_translations(
        self,
        tree: etree._Element,
        segments: List[TranslatableSegment],
        translations: Dict[str, str],
    ) -> bytes:
        """Replace element contents with validated translated fragments and serialize to XHTML."""
        for seg in segments:
            if seg.id not in translations:
                continue

            trans_raw = translations[seg.id].strip()
            if not trans_raw:
                continue

            elem = seg.element
            sanitized = sanitize_xml_entities(trans_raw)

            # Attempt parsing inner fragment as XML with XHTML namespace
            fragment_parsed = False
            try:
                wrapped = f'<div xmlns="{XHTML_NS}">{sanitized}</div>'
                dummy = etree.fromstring(wrapped.encode("utf-8"))
                fragment_parsed = True
            except Exception as xml_err:
                logger.debug("Strict XML parse failed for segment %s ('%s'): %s. Trying HTML recovery.", seg.id, sanitized[:30], xml_err)
                try:
                    # Fallback to lxml.html fragment parsing which auto-closes broken tags
                    html_frag = html.fragment_fromstring(sanitized, create_parent="div")
                    # Convert html fragment back to xml etree
                    frag_xml = etree.tostring(html_frag, encoding="unicode")
                    dummy = etree.fromstring(frag_xml.encode("utf-8"))
                    fragment_parsed = True
                except Exception as html_err:
                    logger.warning("HTML recovery failed for segment %s: %s. Using plain text.", seg.id, html_err)
                    fragment_parsed = False

            # Preserve all element attributes (class, id, style, etc.)
            attribs = dict(elem.attrib)
            elem.clear()
            elem.attrib.update(attribs)

            if fragment_parsed:
                elem.text = dummy.text
                for child in dummy:
                    elem.append(child)
            else:
                # Absolute fallback: plain text assignment to prevent XML corruption
                elem.text = trans_raw

        # Serialize to standard UTF-8 XHTML with XML declaration
        output_bytes = etree.tostring(
            tree,
            encoding="utf-8",
            xml_declaration=True,
            method="xml",
            pretty_print=False,
        )
        return output_bytes


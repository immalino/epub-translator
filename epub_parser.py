"""EPUB reader, spine inspector, and standards-compliant EPUB packager.

Reads EPUB container.xml, parses the OPF package document (metadata, manifest, spine),
handles reading order, chapter filtering, and creates a standard-compliant EPUB
output archive with uncompressed mimetype at offset 0 and updated language metadata.
"""

from __future__ import annotations

import logging
import os
import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from lxml import etree

logger = logging.getLogger(__name__)

CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"

NAMESPACES = {
    "c": CONTAINER_NS,
    "opf": OPF_NS,
    "dc": DC_NS,
    "ncx": NCX_NS,
}


@dataclass
class ManifestItem:
    """An item listed in the EPUB OPF manifest."""

    id: str
    href: str
    media_type: str
    full_zip_path: str
    properties: Optional[str] = None


@dataclass
class SpineItem:
    """An entry in the reading order spine."""

    index: int  # 1-based reading order
    idref: str
    manifest_item: ManifestItem
    linear: bool = True


@dataclass
class EPUBBook:
    """Representation of an EPUB book structure and contents."""

    file_path: Path
    opf_zip_path: str
    opf_bytes: bytes
    title: str
    language: str
    identifier: str
    description: Optional[str]
    manifest: Dict[str, ManifestItem] = field(default_factory=dict)
    spine: List[SpineItem] = field(default_factory=list)
    toc_item: Optional[ManifestItem] = None
    nav_item: Optional[ManifestItem] = None


class EPUBParser:
    """Reads and parses EPUB files."""

    def __init__(self, epub_path: str | Path) -> None:
        self.epub_path = Path(epub_path)
        if not self.epub_path.is_file():
            raise FileNotFoundError(f"File EPUB tidak ditemukan: {self.epub_path}")

    def parse(self) -> EPUBBook:
        """Parse EPUB container and OPF package."""
        with zipfile.ZipFile(self.epub_path, "r") as zf:
            # 1. Read META-INF/container.xml
            if "META-INF/container.xml" not in zf.namelist():
                raise ValueError("Format EPUB tidak valid: 'META-INF/container.xml' tidak ditemukan.")

            container_bytes = zf.read("META-INF/container.xml")
            c_tree = etree.fromstring(container_bytes)
            rootfile_nodes = c_tree.xpath(
                "//c:rootfile[@media-type='application/oebps-package+xml']",
                namespaces={"c": CONTAINER_NS},
            )
            if not rootfile_nodes:
                # Fallback to any rootfile
                rootfile_nodes = c_tree.xpath("//c:rootfile", namespaces={"c": CONTAINER_NS})

            if not rootfile_nodes:
                raise ValueError("File OPF package tidak ditemukan di container.xml.")

            opf_path = rootfile_nodes[0].attrib.get("full-path", "").strip()
            if not opf_path or opf_path not in zf.namelist():
                raise ValueError(f"File OPF package '{opf_path}' tidak ditemukan dalam arsip EPUB.")

            # 2. Read OPF
            opf_dir = posixpath.dirname(opf_path)
            opf_bytes = zf.read(opf_path)
            opf_tree = etree.fromstring(opf_bytes)

            # Metadata
            title_nodes = opf_tree.xpath("//dc:title", namespaces=NAMESPACES)
            title = title_nodes[0].text if title_nodes and title_nodes[0].text else "Untitled"

            lang_nodes = opf_tree.xpath("//dc:language", namespaces=NAMESPACES)
            lang = lang_nodes[0].text if lang_nodes and lang_nodes[0].text else "en"

            id_nodes = opf_tree.xpath("//dc:identifier", namespaces=NAMESPACES)
            identifier = id_nodes[0].text if id_nodes and id_nodes[0].text else "unknown-id"

            desc_nodes = opf_tree.xpath("//dc:description", namespaces=NAMESPACES)
            description = desc_nodes[0].text if desc_nodes and desc_nodes[0].text else None

            # Manifest
            manifest: Dict[str, ManifestItem] = {}
            toc_item: Optional[ManifestItem] = None
            nav_item: Optional[ManifestItem] = None

            for item_elem in opf_tree.xpath("//opf:manifest/opf:item", namespaces=NAMESPACES):
                item_id = item_elem.attrib.get("id", "")
                href = item_elem.attrib.get("href", "")
                mtype = item_elem.attrib.get("media-type", "")
                props = item_elem.attrib.get("properties")

                # Compute full zip path
                full_path = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else href

                m_item = ManifestItem(
                    id=item_id,
                    href=href,
                    media_type=mtype,
                    full_zip_path=full_path,
                    properties=props,
                )
                manifest[item_id] = m_item

                if props and "nav" in props.split():
                    nav_item = m_item
                if mtype == "application/x-dtbncx+xml":
                    toc_item = m_item

            # Spine
            spine: List[SpineItem] = []
            spine_elem = opf_tree.xpath("//opf:spine", namespaces=NAMESPACES)
            if spine_elem:
                spine_toc_id = spine_elem[0].attrib.get("toc")
                if spine_toc_id and spine_toc_id in manifest and not toc_item:
                    toc_item = manifest[spine_toc_id]

            for idx, ref_elem in enumerate(
                opf_tree.xpath("//opf:spine/opf:itemref", namespaces=NAMESPACES), start=1
            ):
                idref = ref_elem.attrib.get("idref", "")
                linear = ref_elem.attrib.get("linear", "yes").lower() != "no"
                if idref in manifest:
                    spine.append(
                        SpineItem(
                            index=idx,
                            idref=idref,
                            manifest_item=manifest[idref],
                            linear=linear,
                        )
                    )

            return EPUBBook(
                file_path=self.epub_path,
                opf_zip_path=opf_path,
                opf_bytes=opf_bytes,
                title=title,
                language=lang,
                identifier=identifier,
                description=description,
                manifest=manifest,
                spine=spine,
                toc_item=toc_item,
                nav_item=nav_item,
            )

    def read_zip_file(self, full_zip_path: str) -> bytes:
        """Read arbitrary file bytes from the EPUB archive."""
        with zipfile.ZipFile(self.epub_path, "r") as zf:
            return zf.read(full_zip_path)


def parse_chapter_filter(filter_str: Optional[str], spine: List[SpineItem]) -> List[SpineItem]:
    """Filter spine items based on user criteria (index, range, idref, or filename)."""
    if not filter_str:
        return list(spine)

    clean = filter_str.strip()
    selected: List[SpineItem] = []

    # Check for range: e.g. "1-3"
    if "-" in clean and clean.replace("-", "").isdigit():
        parts = clean.split("-", 1)
        start, end = int(parts[0]), int(parts[1])
        return [item for item in spine if start <= item.index <= end]

    # Check for comma-separated indices or identifiers: e.g. "1,2,5"
    sub_items = [s.strip() for s in clean.split(",") if s.strip()]
    if all(s.isdigit() for s in sub_items):
        target_indices = {int(s) for s in sub_items}
        return [item for item in spine if item.index in target_indices]

    # Match by idref, href, or filename
    for s in sub_items:
        s_lower = s.lower()
        matched = False
        for item in spine:
            href_name = posixpath.basename(item.manifest_item.href).lower()
            if (
                item.idref.lower() == s_lower
                or item.manifest_item.href.lower() == s_lower
                or href_name == s_lower
            ):
                if item not in selected:
                    selected.append(item)
                matched = True
        if not matched and s.isdigit():
            idx = int(s)
            for item in spine:
                if item.index == idx and item not in selected:
                    selected.append(item)

    return selected if selected else list(spine)


class EPUBBuilder:
    """Assembles and writes a valid, standards-compliant EPUB file."""

    @staticmethod
    def build(
        source_epub: Path,
        output_epub: Path,
        book: EPUBBook,
        modified_files: Dict[str, bytes],
        target_lang: str = "id",
        new_title: Optional[str] = None,
        new_description: Optional[str] = None,
    ) -> None:
        """Build the translated EPUB archive ensuring compliance and XTEINK X4 Pro compatibility."""
        output_epub.parent.mkdir(parents=True, exist_ok=True)

        # Update OPF XML with target language
        opf_tree = etree.fromstring(book.opf_bytes)
        lang_nodes = opf_tree.xpath("//dc:language", namespaces=NAMESPACES)
        if lang_nodes:
            lang_nodes[0].text = target_lang
        else:
            meta = opf_tree.xpath("//opf:metadata", namespaces=NAMESPACES)
            if meta:
                new_lang_elem = etree.SubElement(meta[0], f"{{{DC_NS}}}language")
                new_lang_elem.text = target_lang

        if new_title:
            title_nodes = opf_tree.xpath("//dc:title", namespaces=NAMESPACES)
            if title_nodes:
                title_nodes[0].text = new_title

        if new_description:
            desc_nodes = opf_tree.xpath("//dc:description", namespaces=NAMESPACES)
            if desc_nodes:
                desc_nodes[0].text = new_description

        updated_opf_bytes = etree.tostring(
            opf_tree, encoding="utf-8", xml_declaration=True, method="xml"
        )
        modified_files[book.opf_zip_path] = updated_opf_bytes

        # Write to temporary file first then replace
        temp_out = output_epub.with_suffix(".tmp.epub")
        try:
            with zipfile.ZipFile(temp_out, "w") as zf_out:
                # 1. Write 'mimetype' FIRST, uncompressed (ZIP_STORED)
                mimetype_info = zipfile.ZipInfo("mimetype")
                mimetype_info.compress_type = zipfile.ZIP_STORED
                # Extra field must be empty for EPUB spec compliance
                mimetype_info.extra = b""
                zf_out.writestr(mimetype_info, b"application/epub+zip")

                # 2. Copy or update all other files
                with zipfile.ZipFile(source_epub, "r") as zf_src:
                    for item in zf_src.infolist():
                        if item.filename == "mimetype":
                            continue

                        # Check if this file has been modified
                        if item.filename in modified_files:
                            content = modified_files[item.filename]
                        else:
                            content = zf_src.read(item.filename)

                        # Write deflated
                        zf_out.writestr(item.filename, content, compress_type=zipfile.ZIP_DEFLATED)

            # Move temp to final target
            temp_out.replace(output_epub)
            logger.info("Successfully built translated EPUB: %s", output_epub)

        except Exception as e:
            if temp_out.exists():
                temp_out.unlink(missing_ok=True)
            raise e


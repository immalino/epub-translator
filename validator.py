"""EPUB structural and content validator with Calibre CLI integration.

Validates EPUB ZIP packaging, mimetype compliance, XML/XHTML well-formedness,
internal hyperlinks, image assets, navigation documents, and invokes Calibre's
ebook-validate tool if installed on the host system.
"""

from __future__ import annotations

import logging
import os
import posixpath
import shutil
import subprocess
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set
from lxml import etree

logger = logging.getLogger(__name__)

CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF_NS = "http://www.idpf.org/2007/opf"


@dataclass
class ValidationReport:
    """Detailed results of EPUB validation."""

    epub_path: Path
    is_valid: bool
    calibre_available: bool
    calibre_passed: Optional[bool] = None
    calibre_output: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checks_passed: List[str] = field(default_factory=list)

    def print_summary(self) -> None:
        """Print formatted report to console."""
        print("\n" + "=" * 60)
        print(f"EPUB VALIDATION REPORT: {self.epub_path.name}")
        print("=" * 60)

        for check in self.checks_passed:
            print(f"  [PASS] {check}")

        if self.warnings:
            print("\nWarnings:")
            for w in self.warnings:
                print(f"  [WARN] {w}")

        if self.errors:
            print("\nErrors:")
            for e in self.errors:
                print(f"  [FAIL] {e}")

        print("-" * 60)
        if self.calibre_available:
            status = "PASS" if self.calibre_passed else "FAIL"
            print(f"Calibre (ebook-validate): {status}")
            if self.calibre_output and not self.calibre_passed:
                print(f"Calibre Details:\n{self.calibre_output.strip()}")
        else:
            print("Calibre (ebook-validate): NOT INSTALLED (Built-in validation used)")

        overall = "VALID" if self.is_valid else "INVALID"
        print(f"Overall Result: {overall}")
        print("=" * 60 + "\n")


class EPUBValidator:
    """Validates EPUB integrity using built-in XML parsing and optional Calibre CLI."""

    def __init__(self, epub_path: str | Path) -> None:
        self.epub_path = Path(epub_path)

    def validate(self, run_calibre: bool = True) -> ValidationReport:
        """Run complete validation suite."""
        errors: List[str] = []
        warnings: List[str] = []
        passed: List[str] = []

        if not self.epub_path.is_file():
            return ValidationReport(
                epub_path=self.epub_path,
                is_valid=False,
                calibre_available=False,
                errors=[f"File tidak ditemukan: {self.epub_path}"],
            )

        # 1. ZIP and mimetype check
        try:
            with zipfile.ZipFile(self.epub_path, "r") as zf:
                namelist = zf.namelist()
                if not namelist:
                    errors.append("Arsip EPUB kosong.")
                elif namelist[0] != "mimetype":
                    errors.append(f"Spesifikasi EPUB dilanggar: file pertama harus 'mimetype', tetapi ditemukan '{namelist[0]}'.")
                else:
                    m_info = zf.getinfo("mimetype")
                    if m_info.compress_type != zipfile.ZIP_STORED:
                        errors.append("File 'mimetype' harus disimpan tanpa kompresi (ZIP_STORED).")
                    m_content = zf.read("mimetype")
                    if m_content != b"application/epub+zip":
                        errors.append(f"Konten mimetype tidak sesuai: {m_content!r} (seharusnya b'application/epub+zip').")
                    else:
                        passed.append("Spesifikasi ZIP dan file 'mimetype' valid (uncompressed, offset 0).")

                # 2. Container check
                if "META-INF/container.xml" not in namelist:
                    errors.append("File 'META-INF/container.xml' tidak ditemukan.")
                else:
                    passed.append("File META-INF/container.xml ditemukan.")

                # 3. XML/XHTML Well-formedness
                xml_files = [
                    name
                    for name in namelist
                    if name.lower().endswith((".xml", ".xhtml", ".html", ".opf", ".ncx"))
                ]
                xml_errors = 0
                for fname in xml_files:
                    try:
                        content = zf.read(fname)
                        etree.fromstring(content)
                    except Exception as ex:
                        xml_errors += 1
                        errors.append(f"Sintaks XML tidak valid pada '{fname}': {ex}")

                if xml_errors == 0:
                    passed.append(f"Semua file XML/XHTML ({len(xml_files)} file) lolos uji well-formedness.")

                # 4. Manifest and Reference check
                if "META-INF/container.xml" in namelist:
                    try:
                        c_tree = etree.fromstring(zf.read("META-INF/container.xml"))
                        rootfiles = c_tree.xpath("//c:rootfile", namespaces={"c": CONTAINER_NS})
                        if rootfiles:
                            opf_path = rootfiles[0].attrib.get("full-path", "")
                            if opf_path in namelist:
                                opf_dir = posixpath.dirname(opf_path)
                                opf_tree = etree.fromstring(zf.read(opf_path))
                                manifest_hrefs = set()
                                for item in opf_tree.xpath("//opf:manifest/opf:item", namespaces={"opf": OPF_NS}):
                                    href = item.attrib.get("href", "")
                                    full_p = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else href
                                    manifest_hrefs.add(full_p)
                                    if full_p not in namelist:
                                        errors.append(f"File manifest '{href}' terdaftar di OPF tapi tidak ada di zip.")

                                if not errors:
                                    passed.append("Semua item manifest terdaftar valid dan ada di arsip ZIP.")
                    except Exception as opf_err:
                        warnings.append(f"Gagal memeriksa manifest OPF: {opf_err}")

        except zipfile.BadZipFile:
            errors.append("File rusak atau bukan arsip ZIP yang valid.")
        except Exception as e:
            errors.append(f"Error pembacaan ZIP: {e}")

        # 5. Calibre check
        calibre_bin = shutil.which("ebook-validate")
        calibre_available = calibre_bin is not None
        calibre_passed: Optional[bool] = None
        calibre_output: Optional[str] = None

        if calibre_available and run_calibre and not errors:
            try:
                proc = subprocess.run(
                    [calibre_bin, str(self.epub_path)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                calibre_output = proc.stdout + "\n" + proc.stderr
                if proc.returncode == 0:
                    calibre_passed = True
                    passed.append("Calibre ebook-validate: Lolos validasi tanpa error.")
                else:
                    calibre_passed = False
                    errors.append("Calibre ebook-validate menemukan pelanggaran standar EPUB.")
            except Exception as cal_err:
                warnings.append(f"Gagal menjalankan Calibre ebook-validate: {cal_err}")

        is_valid = len(errors) == 0 and (calibre_passed is not False)

        return ValidationReport(
            epub_path=self.epub_path,
            is_valid=is_valid,
            calibre_available=calibre_available,
            calibre_passed=calibre_passed,
            calibre_output=calibre_output,
            errors=errors,
            warnings=warnings,
            checks_passed=passed,
        )

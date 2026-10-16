#!/usr/bin/env python3
"""EPUB Translator CLI: Translate EPUB books from English to Indonesian.

Features:
- Powered by official Google Gemini SDK (`google-genai`)
- Multiple API keys rotation and quota limit (429) fallback
- Natural Indonesian novel translation preserving literary quality
- Full preservation of inline HTML tags (em, strong, a, span) and EPUB structure
- Resilient checkpoint/resume system (--resume, --retry-failed)
- Compatible with e-ink devices like XTEINK X4 Pro (CrossInk / CrossPoint)
- Built-in EPUB validator with optional Calibre (ebook-validate) integration
"""

from __future__ import annotations

import argparse
import logging
import os
import posixpath
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from config import Config, parse_api_keys
from glossary import Glossary
from checkpoint import CheckpointManager
from text_mapper import XHTMLTextMapper, TranslatableSegment
from translator import GeminiTranslator, KeyManager
from epub_parser import EPUBParser, EPUBBuilder, parse_chapter_filter
from validator import EPUBValidator

logger = logging.getLogger("epub_translate")


def setup_logging(verbose: bool = False) -> None:
    """Setup console logging with appropriate level."""
    level = logging.DEBUG if verbose else logging.INFO
    format_str = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=format_str, datefmt="%H:%M:%S")


def translate_toc(
    book,
    modified_files: Dict[str, bytes],
    translator: GeminiTranslator,
) -> None:
    """Optionally translate titles in TOC (NCX and Nav doc) to match translated chapters."""
    from lxml import etree

    # 1. NCX TOC
    if book.toc_item and book.toc_item.full_zip_path in book.manifest:
        try:
            ncx_path = book.toc_item.full_zip_path
            parser = EPUBParser(book.file_path)
            ncx_bytes = parser.read_zip_file(ncx_path)
            ncx_tree = etree.fromstring(ncx_bytes)
            nav_labels = ncx_tree.xpath("//*[local-name()='navLabel']/*[local-name()='text']")

            segments = []
            for i, node in enumerate(nav_labels, 1):
                text_val = (node.text or "").strip()
                if text_val:
                    segments.append(
                        TranslatableSegment(
                            id=f"toc_{i:03d}",
                            inner_html=text_val,
                            plain_text=text_val,
                            char_count=len(text_val),
                            element=node,
                        )
                    )

            if segments:
                logger.info("Menerjemahkan %d judul pada TOC NCX...", len(segments))
                batches = translator.create_batches(segments)
                for b in batches:
                    trans_map = translator.translate_batch(b)
                    for seg in b:
                        if seg.id in trans_map:
                            seg.element.text = trans_map[seg.id]

                modified_files[ncx_path] = etree.tostring(
                    ncx_tree, encoding="utf-8", xml_declaration=True, method="xml"
                )
        except Exception as e:
            logger.warning("Gagal menerjemahkan NCX TOC: %s", e)

    # 2. EPUB 3 Nav Document
    if book.nav_item and book.nav_item.full_zip_path:
        try:
            nav_path = book.nav_item.full_zip_path
            parser = EPUBParser(book.file_path)
            nav_bytes = parser.read_zip_file(nav_path)
            mapper = XHTMLTextMapper()
            nav_tree, nav_segs = mapper.extract_segments(nav_bytes)
            if nav_segs:
                logger.info("Menerjemahkan %d teks pada EPUB 3 Navigation Document...", len(nav_segs))
                batches = translator.create_batches(nav_segs)
                all_trans = {}
                for b in batches:
                    all_trans.update(translator.translate_batch(b))
                modified_files[nav_path] = mapper.apply_translations(nav_tree, nav_segs, all_trans)
        except Exception as e:
            logger.warning("Gagal menerjemahkan EPUB 3 Nav Document: %s", e)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Terjemahkan buku EPUB Inggris ke Indonesia menggunakan Gemini API & Calibre Validator."
    )
    parser.add_argument("input_epub", help="Path ke file EPUB sumber (bahasa Inggris).")
    parser.add_argument("-o", "--output", help="Path untuk menyimpan file EPUB hasil terjemahan.")
    parser.add_argument("--chapter", help="Pilih bab tertentu (misal: '1', '1-3', '1,2,5', atau 'chapter01.xhtml').")
    parser.add_argument("--resume", action="store_true", help="Lanjutkan proses translasi dari checkpoint terakhir.")
    parser.add_argument("--retry-failed", action="store_true", help="Ulangi translasi hanya pada bagian yang gagal.")
    parser.add_argument("--source-lang", default="en", help="Bahasa sumber (default: 'en').")
    parser.add_argument("--target-lang", default="id", help="Bahasa target (default: 'id').")
    parser.add_argument("--style", default="natural", help="Gaya bahasa terjemahan (default: 'natural').")
    parser.add_argument("--glossary", help="Path ke file glosarium JSON untuk konsistensi istilah/nama.")
    parser.add_argument("--batch-size", type=int, default=20, help="Jumlah paragraf per batch permintaan API (default: 20).")
    parser.add_argument("--model", help="Model Gemini yang digunakan (default: 'gemini-2.5-flash').")
    parser.add_argument("--api-keys", nargs="*", help="Daftar satu atau lebih API key Gemini (dipisahkan spasi atau koma).")
    parser.add_argument("--rotate-strategy", choices=["round_robin", "fallback_on_limit"], default="round_robin", help="Strategi rotasi multi API key.")
    parser.add_argument("--translate-metadata", action="store_true", help="Terjemahkan judul buku dan deskripsi metadata.")
    parser.add_argument("--dry-run", action="store_true", help="Hitung estimasi bagian, kata, karakter, dan token tanpa memanggil API.")
    parser.add_argument("--validate", action="store_true", help="Jalankan pemeriksaan validitas standar EPUB pada file output.")
    parser.add_argument("--checkpoint-dir", default=".epub_translate_cache", help="Direktori penyimpanan checkpoint.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Tampilkan log debug detail.")

    args = parser.parse_args()
    setup_logging(args.verbose)

    input_path = Path(args.input_epub)
    if not input_path.is_file():
        logger.error("File input tidak ditemukan: %s", input_path)
        return 1

    # If only validating existing output file
    if args.validate and not args.output and input_path.suffix.lower() == ".epub":
        logger.info("Menjalankan validasi pada: %s", input_path)
        val = EPUBValidator(input_path)
        report = val.validate()
        report.print_summary()
        return 0 if report.is_valid else 1

    if not args.output and not args.dry_run:
        logger.error("Argumen -o / --output wajib diisi kecuali saat --dry-run.")
        return 1

    output_path = Path(args.output) if args.output else None

    # Load Config
    config = Config.from_env(
        api_keys=args.api_keys,
        model=args.model,
        batch_size=args.batch_size,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        style=args.style,
        checkpoint_dir=Path(args.checkpoint_dir),
        rotate_strategy=args.rotate_strategy,
        translate_metadata=args.translate_metadata,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    # Load Glossary
    glossary = None
    if args.glossary:
        try:
            glossary = Glossary.load(args.glossary)
            logger.info("Glosarium berhasil dimuat: %d istilah (Hash: %s)", len(glossary), glossary.hash)
        except Exception as e:
            logger.error("Gagal memuat glosarium: %s", e)
            return 1

    # Parse EPUB
    logger.info("Membaca file EPUB sumber: %s", input_path)
    epub_parser = EPUBParser(input_path)
    book = epub_parser.parse()
    logger.info("Buku terdeteksi: '%s' | Total Bab (Spine): %d", book.title, len(book.spine))

    # Filter chapters
    target_spine = parse_chapter_filter(args.chapter, book.spine)
    logger.info("Bab yang akan diproses: %d dari %d bab", len(target_spine), len(book.spine))

    # Text mapping & segmentation
    mapper = XHTMLTextMapper()
    chapter_segments: Dict[str, List[TranslatableSegment]] = {}
    chapter_trees = {}

    total_segments_count = 0
    total_chars_count = 0

    for item in target_spine:
        raw_xhtml = epub_parser.read_zip_file(item.manifest_item.full_zip_path)
        tree, segments = mapper.extract_segments(raw_xhtml)
        chapter_segments[item.manifest_item.full_zip_path] = segments
        chapter_trees[item.manifest_item.full_zip_path] = tree
        total_segments_count += len(segments)
        total_chars_count += sum(s.char_count for s in segments)

    # Handle Dry Run
    if config.dry_run:
        print("\n" + "=" * 60)
        print("EPUB TRANSLATOR - DRY RUN ESTIMATION")
        print("=" * 60)
        print(f"File Input          : {input_path.name}")
        print(f"Judul Buku          : {book.title}")
        print(f"Model Gemini        : {config.model}")
        print(f"Status Kunci API    : {config.masked_keys_summary()}")
        print(f"Jumlah Bab Terpilih : {len(target_spine)}")
        print(f"Total Segmen Teks   : {total_segments_count}")
        print(f"Total Karakter Teks : {total_chars_count:,}")
        approx_words = int(total_chars_count / 5.5)
        approx_tokens = int(approx_words * 1.33)
        batches_count = sum(
            len(GeminiTranslator(config).create_batches(segs))
            for segs in chapter_segments.values()
        )
        print(f"Estimasi Kata       : ~{approx_words:,}")
        print(f"Estimasi Token Teks : ~{approx_tokens:,}")
        print(f"Estimasi Panggilan  : {batches_count} batch API (ukuran batch: {config.batch_size})")
        print("=" * 60 + "\n")
        return 0

    # Ensure API keys are present for translation
    if not config.api_keys:
        logger.error(
            "Tidak ditemukan Gemini API key! "
            "Setel environment variable GEMINI_API_KEY atau berikan melalui flag --api-keys key1 key2 ..."
        )
        return 1

    logger.info("Kunci API aktif: %s", config.masked_keys_summary())

    # Initialize Checkpoint & Translator
    epub_hash = CheckpointManager.compute_file_hash(input_path)
    glossary_hash = glossary.hash if glossary else "none"
    checkpoint = CheckpointManager(
        epub_hash=epub_hash,
        model=config.model,
        glossary_hash=glossary_hash,
        checkpoint_dir=config.checkpoint_dir,
    )

    key_manager = KeyManager(
        api_keys=config.api_keys,
        default_cooldown=config.key_cooldown_seconds,
        strategy=config.rotate_strategy,
    )
    translator = GeminiTranslator(config, key_manager=key_manager, glossary=glossary)

    # Translation loop
    start_time = time.time()
    modified_files: Dict[str, bytes] = {}
    completed_chapters = 0
    failed_chapters = 0

    for idx, spine_item in enumerate(target_spine, 1):
        zip_path = spine_item.manifest_item.full_zip_path
        segments = chapter_segments[zip_path]
        tree = chapter_trees[zip_path]

        logger.info(
            "[%d/%d] Memproses Bab '%s' (%d segmen)...",
            idx,
            len(target_spine),
            zip_path,
            len(segments),
        )

        ch_record = checkpoint.register_chapter(
            href=zip_path,
            title=f"Spine {spine_item.index}",
            total_segments=len(segments),
        )

        batches = translator.create_batches(segments)
        chapter_translations: Dict[str, str] = {}
        chapter_has_failure = False

        for b_idx, batch in enumerate(batches, 1):
            batch_id = f"b{b_idx:03d}"
            item_ids = [s.id for s in batch]
            batch_src_hash = CheckpointManager.compute_content_hash(
                "".join(s.inner_html for s in batch)
            )

            # Check resume status
            if args.resume and not args.retry_failed:
                if checkpoint.is_batch_completed(zip_path, batch_id, batch_src_hash):
                    cached = checkpoint.get_batch_translations(zip_path, batch_id)
                    if cached:
                        chapter_translations.update(cached)
                        logger.debug("Batch %s dilewati (sudah selesai di checkpoint).", batch_id)
                        continue

            logger.info("  Menerjemahkan Batch %s/%d (%d segmen)...", batch_id, len(batches), len(batch))

            try:
                trans_map = translator.translate_batch(batch)
                chapter_translations.update(trans_map)
                checkpoint.record_batch_success(
                    href=zip_path,
                    batch_id=batch_id,
                    item_ids=item_ids,
                    source_hash=batch_src_hash,
                    translations=trans_map,
                )
            except Exception as e:
                logger.error("  Gagal menerjemahkan batch %s: %s", batch_id, e)
                checkpoint.record_batch_failure(
                    href=zip_path,
                    batch_id=batch_id,
                    item_ids=item_ids,
                    source_hash=batch_src_hash,
                    error_msg=str(e),
                )
                chapter_has_failure = True
                break

        if chapter_has_failure:
            failed_chapters += 1
            logger.error("Bab '%s' gagal selesai. Progres tersimpan di checkpoint.", zip_path)
            continue

        # Reconstruct translated XHTML
        translated_xhtml_bytes = mapper.apply_translations(tree, segments, chapter_translations)
        modified_files[zip_path] = translated_xhtml_bytes
        checkpoint.mark_chapter_completed(zip_path)
        completed_chapters += 1
        logger.info("  Bab '%s' berhasil diterjemahkan.", zip_path)

    # Translate TOC and metadata if requested
    new_title = None
    new_description = None

    if config.translate_metadata and book.title:
        try:
            logger.info("Menerjemahkan judul dan deskripsi buku...")
            meta_segs = [
                TranslatableSegment(
                    id="meta_title",
                    inner_html=book.title,
                    plain_text=book.title,
                    char_count=len(book.title),
                    element=None,
                )
            ]
            if book.description:
                meta_segs.append(
                    TranslatableSegment(
                        id="meta_desc",
                        inner_html=book.description,
                        plain_text=book.description,
                        char_count=len(book.description),
                        element=None,
                    )
                )
            meta_res = translator.translate_batch(meta_segs)
            new_title = meta_res.get("meta_title")
            new_description = meta_res.get("meta_desc")
        except Exception as e:
            logger.warning("Gagal menerjemahkan metadata: %s", e)

    # Translate TOC
    translate_toc(book, modified_files, translator)

    # Build output EPUB
    if output_path and modified_files:
        logger.info("Membangun file EPUB terjemahan ke: %s", output_path)
        EPUBBuilder.build(
            source_epub=input_path,
            output_epub=output_path,
            book=book,
            modified_files=modified_files,
            target_lang=config.target_lang,
            new_title=new_title,
            new_description=new_description,
        )

        elapsed = time.time() - start_time
        logger.info(
            "Translasi selesai dalam %.1f detik! Selesai: %d bab, Gagal: %d bab.",
            elapsed,
            completed_chapters,
            failed_chapters,
        )

        # Run Validation
        if args.validate or True:
            logger.info("Memvalidasi hasil output EPUB...")
            val = EPUBValidator(output_path)
            report = val.validate()
            report.print_summary()

    return 0 if failed_chapters == 0 else 2


if __name__ == "__main__":
    sys.exit(main())


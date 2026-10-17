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
from typing import Dict, List, Optional, Tuple

from config import Config, parse_api_keys
from glossary import Glossary
from checkpoint import CheckpointManager
from text_mapper import XHTMLTextMapper, TranslatableSegment
from translator import (
    GeminiTranslator,
    OllamaTranslator,
    KeyManager,
    GeminiDailyQuotaExhaustedError,
    get_translator,
)
from epub_parser import EPUBParser, EPUBBuilder, parse_chapter_filter
from validator import EPUBValidator

logger = logging.getLogger("epub_translate")


def setup_logging(verbose: bool = False) -> None:
    """Setup console logging with appropriate level."""
    level = logging.DEBUG if verbose else logging.INFO
    format_str = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=format_str, datefmt="%H:%M:%S")


def print_quota_exhausted_banner(
    error: GeminiDailyQuotaExhaustedError,
    checkpoint: CheckpointManager,
    input_path: Path,
    output_path: Optional[Path],
    args: argparse.Namespace,
) -> None:
    """Print informative guide when daily quota or limit: 0 is reached."""
    details = error.quota_details
    limit_type = details.limit_type if details else "RPD"
    limit_desc = (
        "Batas Kuota Harian (Requests Per Day / RPD)"
        if limit_type == "RPD"
        else "Kuota Tidak Tersedia (limit: 0)"
    )
    summary = checkpoint.get_summary()

    cmd_parts = ["python", "epub_translate.py", f'"{input_path}"']
    if output_path:
        cmd_parts.extend(["-o", f'"{output_path}"'])
    if getattr(args, "model", None):
        cmd_parts.extend(["--model", args.model])
    if getattr(args, "glossary", None):
        cmd_parts.extend(["--glossary", f'"{args.glossary}"'])
    if getattr(args, "chapter", None):
        cmd_parts.extend(["--chapter", f'"{args.chapter}"'])
    cmd_parts.append("--resume")
    resume_cmd = " ".join(cmd_parts)

    print("\n" + "=" * 72)
    print(" [KUOTA GEMINI API TERCAPAI / RESOURCE_EXHAUSTED]")
    print("=" * 72)
    print(f" Jenis Limit    : {limit_type} ({limit_desc})")
    if details:
        if details.model:
            print(f" Model          : {details.model}")
        if details.quota_id:
            print(f" Quota ID       : {details.quota_id}")
        if details.quota_metric:
            print(f" Quota Metric   : {details.quota_metric}")
        if details.limit_value is not None:
            print(f" Quota Limit    : {details.limit_value}")
        if details.message:
            print(f" Pesan API      : {details.message}")
    print("-" * 72)
    print(" STATUS PROGRES & CHECKPOINT:")
    print(f" - File Checkpoint   : {checkpoint.file_path}")
    print(f" - Batch Selesai     : {summary['completed_batches']} batch (tersimpan aman di disk)")
    print(f" - Bab Selesai       : {summary['completed_chapters']} dari {summary['total_chapters']} bab")
    print("-" * 72)
    print(" CARA MELANJUTKAN PROSES SETELAH KUOTA PULIH:")
    print(" 1. Kuota Free Tier harian Gemini di-reset pada pergantian hari (00:00 UTC / 07:00 WIB).")
    print(" 2. Seluruh batch yang sudah selesai TIDAK AKAN diulang.")
    print(" 3. Jalankan kembali perintah translasi dengan menambahkan flag --resume:")
    print(f"\n    {resume_cmd}\n")
    print("=" * 72 + "\n")


def translate_toc(
    book,
    modified_files: Dict[str, bytes],
    translator,
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


def translate_single_epub(
    input_path: Path,
    output_path: Optional[Path],
    config: Config,
    args: argparse.Namespace,
    glossary: Optional[Glossary] = None,
) -> int:
    """Translate an individual EPUB file."""
    if not input_path.is_file():
        logger.error("File input tidak ditemukan: %s", input_path)
        return 1

    # Ensure provider prerequisites
    key_manager = None
    if config.provider == "gemini":
        if not config.api_keys:
            logger.error(
                "Tidak ditemukan Gemini API key! "
                "Setel environment variable GEMINI_API_KEY atau berikan melalui flag --api-keys key1 key2 ..."
            )
            return 1
        logger.info("Provider: Gemini API | Kunci aktif: %s", config.masked_keys_summary())
        key_manager = KeyManager(
            api_keys=config.api_keys,
            default_cooldown=config.key_cooldown_seconds,
            strategy=config.rotate_strategy,
        )
        translator = GeminiTranslator(config, key_manager=key_manager, glossary=glossary)
    else:
        logger.info("Provider: Ollama Lokal | Model: %s | URL: %s", config.model, config.ollama_base_url)
        translator = OllamaTranslator(config, glossary=glossary)
        if not config.dry_run and not translator.check_connection():
            logger.error(
                "Tidak dapat terhubung ke Ollama di %s. Pastikan Ollama sudah aktif ('ollama serve') "
                "dan model %s sudah diunduh ('ollama pull %s').",
                config.ollama_base_url,
                config.model,
                config.model,
            )
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
        epub_hash = CheckpointManager.compute_file_hash(input_path)
        glossary_hash = glossary.hash if glossary else "none"
        checkpoint = CheckpointManager(
            epub_hash=epub_hash,
            model=config.model,
            glossary_hash=glossary_hash,
            checkpoint_dir=config.checkpoint_dir,
        )

        batches_count = sum(
            len(translator.create_batches(segs))
            for segs in chapter_segments.values()
        )

        completed_batches = 0
        for zip_path, segs in chapter_segments.items():
            bts = translator.create_batches(segs)
            for b_idx, b in enumerate(bts, 1):
                b_id = f"b{b_idx:03d}"
                b_hash = CheckpointManager.compute_content_hash("".join(s.inner_html for s in b))
                if checkpoint.is_batch_completed(zip_path, b_id, b_hash):
                    completed_batches += 1

        remaining_batches = max(0, batches_count - completed_batches)
        approx_words = int(total_chars_count / 5.5)
        approx_tokens = int(approx_words * 1.33)

        if config.provider == "gemini":
            min_minutes_rpm = round(remaining_batches / 15.0, 1)
            rpd_limit = 1500

            print("\n" + "=" * 68)
            print(" EPUB TRANSLATOR - DRY RUN & ESTIMASI KUOTA GEMINI")
            print("=" * 68)
            print(f" File Input          : {input_path.name}")
            print(f" Judul Buku          : {book.title}")
            print(f" Model Gemini        : {config.model}")
            print(f" Status Kunci API    : {config.masked_keys_summary()}")
            print(f" Jumlah Bab Terpilih : {len(target_spine)}")
            print(f" Total Segmen Teks   : {total_segments_count:,}")
            print(f" Total Karakter Teks : {total_chars_count:,}")
            print(f" Estimasi Kata       : ~{approx_words:,}")
            print(f" Estimasi Token Teks : ~{approx_tokens:,}")
            print("-" * 68)
            print(" ESTIMASI PERMINTAAN API (REQUESTS):")
            print(f" Total Batch (Semua) : {batches_count} request (ukuran batch: {config.batch_size})")
            if completed_batches > 0:
                print(f" Batch Selesai (Cache): {completed_batches} request (dilewati)")
                print(f" Batch Tersisa       : {remaining_batches} request (yang akan dipanggil)")
            else:
                print(f" Batch Tersisa       : {remaining_batches} request")
            print("-" * 68)
            print(" ESTIMASI KUOTA GEMINI FREE TIER:")
            print(f" - Limit RPM (~15 RPM) : Estimasi durasi translasi ~{min_minutes_rpm} menit")
            if remaining_batches <= rpd_limit:
                print(f" - Limit RPD (1.500/hari): CUKUP ({remaining_batches} dari 1.500 request/hari)")
            else:
                days_needed = round(remaining_batches / rpd_limit, 1)
                print(f" - Limit RPD (1.500/hari): MELEBIHI 1 HARI! Perlu ~{days_needed} hari atau bagi per bab.")
            print("=" * 68 + "\n")
            return 0
        else:
            est_minutes = round(remaining_batches * 7.0 / 60.0, 1)
            print("\n" + "=" * 68)
            print(" EPUB TRANSLATOR - DRY RUN & ESTIMASI OLLAMA LOKAL")
            print("=" * 68)
            print(f" File Input          : {input_path.name}")
            print(f" Judul Buku          : {book.title}")
            print(f" Provider            : Ollama ({config.ollama_base_url})")
            print(f" Model               : {config.model}")
            print(f" Jumlah Bab Terpilih : {len(target_spine)}")
            print(f" Total Segmen Teks   : {total_segments_count:,}")
            print(f" Total Karakter Teks : {total_chars_count:,}")
            print(f" Estimasi Kata       : ~{approx_words:,}")
            print("-" * 68)
            print(" ESTIMASI INFERENSI LOKAL:")
            print(f" Total Batch (Semua) : {batches_count} batch (ukuran batch: {config.batch_size})")
            if completed_batches > 0:
                print(f" Batch Selesai (Cache): {completed_batches} batch (dilewati)")
                print(f" Batch Tersisa       : {remaining_batches} batch")
            else:
                print(f" Batch Tersisa       : {remaining_batches} batch")
            print(f" Estimasi Durasi CPU : ~{est_minutes} menit (asumsi ~7 detik/batch)")
            print("=" * 68 + "\n")
            return 0

    if not output_path:
        logger.error("Output path tidak ditentukan untuk %s", input_path.name)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize Checkpoint
    epub_hash = CheckpointManager.compute_file_hash(input_path)
    glossary_hash = glossary.hash if glossary else "none"
    checkpoint = CheckpointManager(
        epub_hash=epub_hash,
        model=config.model,
        glossary_hash=glossary_hash,
        checkpoint_dir=config.checkpoint_dir,
    )

    if not args.resume and not args.retry_failed and checkpoint.has_completed_batches():
        logger.info(
            "Ditemukan data checkpoint dari sesi sebelumnya. "
            "Gunakan flag --resume untuk melanjutkan tanpa mengulang segmen yang sudah selesai."
        )

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

            # Check resume status: skip completed batches to avoid re-translation
            if (args.resume or args.retry_failed) and checkpoint.is_batch_completed(zip_path, batch_id, batch_src_hash):
                cached = checkpoint.get_batch_translations(zip_path, batch_id)
                if cached:
                    chapter_translations.update(cached)
                    logger.info("  Batch %s/%d sudah selesai di checkpoint, dilewati.", batch_id, len(batches))
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
            except GeminiDailyQuotaExhaustedError as e:
                logger.error("  Batas kuota Gemini API harian/kuota nol tercapai pada batch %s: %s", batch_id, e)
                checkpoint.record_batch_failure(
                    href=zip_path,
                    batch_id=batch_id,
                    item_ids=item_ids,
                    source_hash=batch_src_hash,
                    error_msg=str(e),
                )
                print_quota_exhausted_banner(e, checkpoint, input_path, output_path, args)
                return 2
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Terjemahkan buku EPUB Inggris ke Indonesia menggunakan Gemini API atau Ollama lokal."
    )
    parser.add_argument("input_epub", nargs="?", default=None, help="Path ke file EPUB sumber atau direktori (opsional, default: pindai folder input/).")
    parser.add_argument("-o", "--output", help="Path untuk menyimpan file EPUB hasil terjemahan (opsional, default: folder output/ dengan nama sama).")
    parser.add_argument("--provider", choices=["gemini", "ollama"], default=None, help="Provider translasi: 'gemini' (default) atau 'ollama'.")
    parser.add_argument("--ollama-url", default=None, help="URL endpoint Ollama (default: http://localhost:11434).")
    parser.add_argument("--input-dir", default=None, help="Folder berkas EPUB sumber (default: 'input').")
    parser.add_argument("--output-dir", default=None, help="Folder penyimpanan EPUB hasil terjemahan (default: 'output').")
    parser.add_argument("--chapter", help="Pilih bab tertentu (misal: '1', '1-3', '1,2,5', atau 'chapter01.xhtml').")
    parser.add_argument("--resume", action="store_true", help="Lanjutkan proses translasi dari checkpoint terakhir.")
    parser.add_argument("--retry-failed", action="store_true", help="Ulangi translasi hanya pada bagian yang gagal.")
    parser.add_argument("--source-lang", default="en", help="Bahasa sumber (default: 'en').")
    parser.add_argument("--target-lang", default="id", help="Bahasa target (default: 'id').")
    parser.add_argument("--style", default="natural", help="Gaya bahasa terjemahan (default: 'natural').")
    parser.add_argument("--glossary", help="Path ke file glosarium JSON untuk konsistensi istilah/nama.")
    parser.add_argument("--batch-size", type=int, default=None, help="Jumlah paragraf per batch permintaan API.")
    parser.add_argument("--model", help="Model yang digunakan (default: 'translategemma:4b' untuk ollama, 'gemini-2.5-flash' untuk gemini).")
    parser.add_argument("--api-keys", nargs="*", help="Daftar satu atau lebih API key Gemini (jika menggunakan provider gemini).")
    parser.add_argument("--rotate-strategy", choices=["round_robin", "fallback_on_limit"], default="round_robin", help="Strategi rotasi multi API key.")
    parser.add_argument("--translate-metadata", action="store_true", help="Terjemahkan judul buku dan deskripsi metadata.")
    parser.add_argument("--dry-run", action="store_true", help="Hitung estimasi bagian, kata, karakter, dan token tanpa memanggil API.")
    parser.add_argument("--max-retries", type=int, default=5, help="Batas maksimum percobaan retry per batch jika gagal (default: 5).")
    parser.add_argument("--timeout", type=float, default=None, help="Batas waktu request timeout dalam detik.")
    parser.add_argument("--validate", action="store_true", help="Jalankan pemeriksaan validitas standar EPUB pada file output.")
    parser.add_argument("--checkpoint-dir", default=".epub_translate_cache", help="Direktori penyimpanan checkpoint.")
    parser.add_argument("--ui", action="store_true", help="Luncurkan antarmuka grafis Web UI (Streamlit).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Tampilkan log debug detail.")

    args = parser.parse_args()

    if args.ui:
        ui_script = Path(__file__).parent / "run_ui.sh"
        if ui_script.is_file():
            os.execv(str(ui_script), [str(ui_script)])
        else:
            streamlit_bin = Path(sys.executable).parent / "streamlit"
            cmd = [str(streamlit_bin if streamlit_bin.is_file() else "streamlit"), "run", "app_streamlit.py"]
            os.execvp(cmd[0], cmd)

    setup_logging(args.verbose)

    # Load Config
    config = Config.from_env(
        provider=args.provider,
        ollama_base_url=args.ollama_url,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
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
        max_retries=args.max_retries,
        request_timeout=args.timeout,
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

    # If only validating existing output file
    if args.validate and not args.output and args.input_epub:
        input_candidate = Path(args.input_epub)
        if input_candidate.is_file() and input_candidate.suffix.lower() == ".epub":
            logger.info("Menjalankan validasi pada: %s", input_candidate)
            val = EPUBValidator(input_candidate)
            report = val.validate()
            report.print_summary()
            return 0 if report.is_valid else 1

    input_dir = config.input_dir
    output_dir = config.output_dir
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    tasks: List[Tuple[Path, Optional[Path]]] = []

    if args.input_epub:
        target_path = Path(args.input_epub)
        if target_path.is_file():
            out_file = Path(args.output) if args.output else (output_dir / target_path.name)
            tasks.append((target_path, out_file))
        elif target_path.is_dir():
            for ep in sorted(target_path.glob("*.epub")):
                tasks.append((ep, output_dir / ep.name))
        else:
            logger.error("File atau direktori input tidak ditemukan: %s", target_path)
            return 1
    else:
        # Scan input_dir
        for ep in sorted(input_dir.glob("*.epub")):
            tasks.append((ep, output_dir / ep.name))

    if not tasks:
        if not args.input_epub:
            logger.info(
                "Folder input '%s' tidak berisi file .epub. "
                "Silakan letakkan file .epub yang ingin diterjemahkan ke dalam folder '%s' lalu jalankan kembali perintah ini.",
                input_dir,
                input_dir,
            )
            return 0
        else:
            logger.error("Tidak ditemukan file .epub untuk diproses.")
            return 1

    total_tasks = len(tasks)
    overall_exit_code = 0

    for idx, (in_f, out_f) in enumerate(tasks, 1):
        if total_tasks > 1:
            logger.info("==================================================================")
            logger.info("[%d/%d] Memproses Buku: %s -> %s", idx, total_tasks, in_f.name, out_f.name if out_f else "Dry Run")
            logger.info("==================================================================")

        ret = translate_single_epub(in_f, out_f, config, args, glossary)
        if ret != 0:
            overall_exit_code = ret

    return overall_exit_code


if __name__ == "__main__":
    sys.exit(main())


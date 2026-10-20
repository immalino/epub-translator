"""Runner and Callback Abstraction for EPUB Translator.

Provides a unified interface used by both CLI and Streamlit Web UI.
Handles EPUB inspection, dry run statistics, bilingual chapter previews,
and orchestrates the translation process with real-time callback hooks.
"""

from __future__ import annotations

import logging
import os
import posixpath
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import Config
from glossary import Glossary
from checkpoint import CheckpointManager
from text_mapper import XHTMLTextMapper, TranslatableSegment
from lxml import etree
from translator import (
    GeminiTranslator,
    OllamaTranslator,
    KeyManager,
    GeminiDailyQuotaExhaustedError,
    get_translator,
)
from epub_parser import EPUBParser, EPUBBuilder, parse_chapter_filter
from validator import EPUBValidator

logger = logging.getLogger("epub_translate.runner")


class TranslationCallback:
    """Base interface for receiving real-time translation events."""

    def on_log(self, level: str, message: str) -> None:
        """Called for informational or warning log messages."""
        pass

    def on_start(
        self,
        total_chapters: int,
        total_chars: int,
        total_segments: int,
        target_spine: List[Any],
    ) -> None:
        """Called when translation starts."""
        pass

    def on_chapter_start(
        self,
        chapter_idx: int,
        chapter_title: str,
        total_batches: int,
    ) -> None:
        """Called when starting a chapter."""
        pass

    def on_batch_complete(
        self,
        chapter_idx: int,
        batch_idx: int,
        total_batches: int,
        translated_count: int,
        is_cache: bool = False,
    ) -> None:
        """Called when a single batch of segments is completed or restored from cache."""
        pass

    def on_chapter_complete(
        self,
        chapter_idx: int,
        chapter_title: str,
    ) -> None:
        """Called when a chapter successfully finishes."""
        pass

    def on_chapter_failed(
        self,
        chapter_idx: int,
        chapter_title: str,
        error_message: str,
    ) -> None:
        """Called when a chapter encounters an unrecoverable failure."""
        pass

    def on_quota_warning(
        self,
        error: GeminiDailyQuotaExhaustedError,
        checkpoint: CheckpointManager,
    ) -> None:
        """Called when API quota limit (RPD / limit 0) is encountered."""
        pass

    def on_complete(
        self,
        output_path: Path,
        elapsed_seconds: float,
        validation_report: Optional[Any] = None,
    ) -> None:
        """Called when the entire book translation run is complete."""
        pass


class TranslationRunner:
    """Core translation orchestrator that works with any TranslationCallback."""

    @staticmethod
    def inspect_epub(input_path: Path) -> Dict[str, Any]:
        """Inspect EPUB file and extract metadata, chapter list, and cover."""
        parser = EPUBParser(input_path)
        book = parser.parse()
        mapper = XHTMLTextMapper()

        chapters = []
        for item in book.spine:
            zip_path = item.manifest_item.full_zip_path
            raw_bytes = parser.read_zip_file(zip_path)
            _, segments = mapper.extract_segments(raw_bytes)
            char_count = sum(s.char_count for s in segments)

            # Try to determine human-friendly title if available in TOC/content
            chapters.append({
                "index": item.index,
                "id": item.manifest_item.id,
                "href": item.manifest_item.href,
                "zip_path": zip_path,
                "segment_count": len(segments),
                "char_count": char_count,
            })

        # Look for cover image
        cover_bytes: Optional[bytes] = None
        cover_mime: Optional[str] = None
        for item_id, m_item in book.manifest.items():
            if m_item.properties and "cover-image" in m_item.properties:
                cover_bytes = parser.read_zip_file(m_item.full_zip_path)
                cover_mime = m_item.media_type
                break
            if "cover" in m_item.id.lower() or "cover" in m_item.href.lower():
                if m_item.media_type.startswith("image/"):
                    cover_bytes = parser.read_zip_file(m_item.full_zip_path)
                    cover_mime = m_item.media_type
                    break

        # Try to extract creator from OPF
        creator = "Unknown"
        try:
            tree = etree.fromstring(book.opf_bytes)
            c_nodes = tree.xpath("//*[local-name()='creator']")
            if c_nodes and c_nodes[0].text:
                creator = c_nodes[0].text.strip()
        except Exception:
            pass

        return {
            "title": book.title,
            "creator": creator,
            "language": book.language,
            "identifier": book.identifier,
            "description": book.description,
            "spine_count": len(book.spine),
            "chapters": chapters,
            "cover_bytes": cover_bytes,
            "cover_mime": cover_mime,
        }

    @staticmethod
    def get_dry_run_stats(
        input_path: Path,
        config: Config,
        chapter_filter: Optional[str] = None,
        glossary: Optional[Glossary] = None,
    ) -> Dict[str, Any]:
        """Calculate dry run statistics without calling external APIs."""
        parser = EPUBParser(input_path)
        book = parser.parse()
        target_spine = parse_chapter_filter(chapter_filter, book.spine)

        mapper = XHTMLTextMapper()
        chapter_segments: Dict[str, List[TranslatableSegment]] = {}
        total_segments_count = 0
        total_chars_count = 0

        for item in target_spine:
            raw_xhtml = parser.read_zip_file(item.manifest_item.full_zip_path)
            _, segments = mapper.extract_segments(raw_xhtml)
            chapter_segments[item.manifest_item.full_zip_path] = segments
            total_segments_count += len(segments)
            total_chars_count += sum(s.char_count for s in segments)

        epub_hash = CheckpointManager.compute_file_hash(input_path)
        glossary_hash = glossary.hash if glossary else "none"
        checkpoint = CheckpointManager(
            epub_hash=epub_hash,
            model=config.model,
            glossary_hash=glossary_hash,
            checkpoint_dir=config.checkpoint_dir,
        )

        # Batch grouping logic (matches translator.create_batches)
        batches_count = 0
        completed_batches = 0

        batch_size = config.batch_size or (10 if config.provider == "gemini" else 15)
        for zip_path, segs in chapter_segments.items():
            # chunking
            batches = [segs[i:i + batch_size] for i in range(0, len(segs), batch_size)]
            batches_count += len(batches)
            for b_idx, b in enumerate(batches, 1):
                b_id = f"b{b_idx:03d}"
                b_hash = CheckpointManager.compute_content_hash("".join(s.inner_html for s in b))
                if checkpoint.is_batch_completed(zip_path, b_id, b_hash):
                    completed_batches += 1

        remaining_batches = max(0, batches_count - completed_batches)
        approx_words = int(total_chars_count / 5.5)
        approx_tokens = int(approx_words * 1.33)

        est_minutes = 0.0
        rpd_sufficient = True
        if config.provider == "gemini":
            est_minutes = round(remaining_batches / 15.0, 1)
            rpd_sufficient = remaining_batches <= 1500
        else:
            est_minutes = round(remaining_batches * 7.0 / 60.0, 1)

        return {
            "book_title": book.title,
            "total_spine_chapters": len(book.spine),
            "target_chapters": len(target_spine),
            "total_segments": total_segments_count,
            "total_chars": total_chars_count,
            "approx_words": approx_words,
            "approx_tokens": approx_tokens,
            "batches_count": batches_count,
            "completed_batches": completed_batches,
            "remaining_batches": remaining_batches,
            "est_minutes": est_minutes,
            "rpd_sufficient": rpd_sufficient,
            "provider": config.provider,
            "model": config.model,
        }

    @staticmethod
    def get_bilingual_preview(
        input_path: Path,
        chapter_zip_path: str,
        output_path: Optional[Path] = None,
        config: Optional[Config] = None,
        glossary: Optional[Glossary] = None,
    ) -> List[Dict[str, Any]]:
        """Get side-by-side bilingual preview for a specific chapter."""
        if not input_path.is_file():
            return []

        parser = EPUBParser(input_path)
        book = parser.parse()
        mapper = XHTMLTextMapper()

        # Extract source segments
        source_raw = parser.read_zip_file(chapter_zip_path)
        _, source_segs = mapper.extract_segments(source_raw)

        # 1. Try to find translation from output EPUB if exists
        translated_map: Dict[str, str] = {}
        if output_path and output_path.is_file():
            try:
                out_parser = EPUBParser(output_path)
                out_raw = out_parser.read_zip_file(chapter_zip_path)
                _, out_segs = mapper.extract_segments(out_raw)
                for s in out_segs:
                    translated_map[s.id] = s.plain_text
            except Exception:
                pass

        # 2. If not found in output EPUB, check checkpoint cache
        if not translated_map and config:
            epub_hash = CheckpointManager.compute_file_hash(input_path)
            glossary_hash = glossary.hash if glossary else "none"
            checkpoint = CheckpointManager(
                epub_hash=epub_hash,
                model=config.model,
                glossary_hash=glossary_hash,
                checkpoint_dir=config.checkpoint_dir,
            )
            # Find all batches recorded for this chapter
            if chapter_zip_path in checkpoint.chapters:
                ch = checkpoint.chapters[chapter_zip_path]
                for b_rec in ch.batches.values():
                    if b_rec.translated_texts:
                        translated_map.update(b_rec.translated_texts)

        pairs = []
        for seg in source_segs:
            pairs.append({
                "id": seg.id,
                "source": seg.plain_text,
                "translated": translated_map.get(seg.id, None),
                "is_translated": seg.id in translated_map,
            })

        return pairs

    @staticmethod
    def run_translation(
        input_path: Path,
        output_path: Path,
        config: Config,
        chapter_filter: Optional[str] = None,
        resume: bool = True,
        retry_failed: bool = False,
        glossary: Optional[Glossary] = None,
        callback: Optional[TranslationCallback] = None,
        pause_event: Optional[threading.Event] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> int:
        """Execute translation with real-time callback hooks."""
        cb = callback or TranslationCallback()

        def _check_interruption() -> bool:
            """Check cancellation and handle pause. Returns True if cancelled."""
            if cancel_event and cancel_event.is_set():
                cb.on_log("WARNING", "Proses terjemahan dibatalkan oleh pengguna.")
                return True

            if pause_event and pause_event.is_set():
                cb.on_log("INFO", "Proses terjemahan dijeda. Menunggu untuk dilanjutkan...")
                while pause_event.is_set():
                    if cancel_event and cancel_event.is_set():
                        cb.on_log("WARNING", "Proses terjemahan dibatalkan saat dijeda.")
                        return True
                    time.sleep(0.1)
                cb.on_log("INFO", "Proses terjemahan dilanjutkan.")

            return False

        if not input_path.is_file():
            cb.on_log("ERROR", f"File input tidak ditemukan: {input_path}")
            return 1

        # Key manager & translator initialization
        key_manager = None
        if config.provider == "gemini":
            if not config.api_keys:
                cb.on_log("ERROR", "Tidak ditemukan Gemini API key! Pastikan GEMINI_API_KEY disetel.")
                return 1
            cb.on_log("INFO", f"Provider: Gemini API | Kunci aktif: {config.masked_keys_summary()}")
            key_manager = KeyManager(
                api_keys=config.api_keys,
                default_cooldown=config.key_cooldown_seconds,
                strategy=config.rotate_strategy,
            )
            translator = GeminiTranslator(config, key_manager=key_manager, glossary=glossary)
        else:
            cb.on_log("INFO", f"Provider: Ollama Lokal | Model: {config.model} | URL: {config.ollama_base_url}")
            translator = OllamaTranslator(config, glossary=glossary)
            if not translator.check_connection():
                cb.on_log("ERROR", f"Tidak dapat terhubung ke Ollama di {config.ollama_base_url}.")
                return 1

        # Parse EPUB
        cb.on_log("INFO", f"Membaca file EPUB sumber: {input_path.name}")
        epub_parser = EPUBParser(input_path)
        book = epub_parser.parse()
        cb.on_log("INFO", f"Buku: '{book.title}' | Total Bab: {len(book.spine)}")

        target_spine = parse_chapter_filter(chapter_filter, book.spine)
        cb.on_log("INFO", f"Bab yang akan diproses: {len(target_spine)} dari {len(book.spine)} bab")

        # Segmentation
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
        if total_segments_count == 0:
            cb.on_log("WARNING", "Tidak ditemukan segmen teks yang dapat diterjemahkan pada bab terpilih.")
            return 1

        cb.on_start(len(target_spine), total_chars_count, total_segments_count, target_spine)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Checkpoint init
        epub_hash = CheckpointManager.compute_file_hash(input_path)
        glossary_hash = glossary.hash if glossary else "none"
        checkpoint = CheckpointManager(
            epub_hash=epub_hash,
            model=config.model,
            glossary_hash=glossary_hash,
            checkpoint_dir=config.checkpoint_dir,
        )

        start_time = time.time()
        modified_files: Dict[str, bytes] = {}
        completed_chapters = 0
        failed_chapters = 0

        for ch_idx, spine_item in enumerate(target_spine, 1):
            if _check_interruption():
                return 3

            zip_path = spine_item.manifest_item.full_zip_path
            segments = chapter_segments[zip_path]
            tree = chapter_trees[zip_path]

            ch_title = f"Bab {spine_item.index} ({posixpath.basename(zip_path)})"
            cb.on_log("INFO", f"[{ch_idx}/{len(target_spine)}] Memproses {ch_title} ({len(segments)} segmen)...")

            checkpoint.register_chapter(
                href=zip_path,
                title=f"Spine {spine_item.index}",
                total_segments=len(segments),
            )

            batches = translator.create_batches(segments)
            cb.on_chapter_start(ch_idx, ch_title, len(batches))

            chapter_translations: Dict[str, str] = {}
            chapter_has_failure = False

            for b_idx, batch in enumerate(batches, 1):
                if _check_interruption():
                    return 3

                batch_id = f"b{b_idx:03d}"
                item_ids = [s.id for s in batch]
                batch_src_hash = CheckpointManager.compute_content_hash("".join(s.inner_html for s in batch))

                # Check resume
                if (resume or retry_failed) and checkpoint.is_batch_completed(zip_path, batch_id, batch_src_hash):
                    cached = checkpoint.get_batch_translations(zip_path, batch_id)
                    if cached:
                        chapter_translations.update(cached)
                        cb.on_log("DEBUG", f"  Batch {batch_id}/{len(batches)} diambil dari checkpoint.")
                        cb.on_batch_complete(ch_idx, b_idx, len(batches), len(batch), is_cache=True)
                        continue

                cb.on_log("INFO", f"  Menerjemahkan Batch {batch_id}/{len(batches)} ({len(batch)} segmen)...")

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
                    cb.on_batch_complete(ch_idx, b_idx, len(batches), len(batch), is_cache=False)
                    time.sleep(0.5)
                except GeminiDailyQuotaExhaustedError as e:
                    cb.on_log("ERROR", f"  Batas kuota Gemini API tercapai pada batch {batch_id}: {e}")
                    checkpoint.record_batch_failure(
                        href=zip_path,
                        batch_id=batch_id,
                        item_ids=item_ids,
                        source_hash=batch_src_hash,
                        error_msg=str(e),
                    )
                    cb.on_quota_warning(e, checkpoint)
                    return 2
                except Exception as e:
                    cb.on_log("ERROR", f"  Gagal menerjemahkan batch {batch_id}: {e}")
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
                cb.on_chapter_failed(ch_idx, ch_title, "Kegagalan pada salah satu batch")
                continue

            # Apply translations
            translated_xhtml_bytes = mapper.apply_translations(tree, segments, chapter_translations)
            modified_files[zip_path] = translated_xhtml_bytes
            checkpoint.mark_chapter_completed(zip_path)
            completed_chapters += 1
            cb.on_chapter_complete(ch_idx, ch_title)

        # Build output EPUB
        report = None
        if output_path and modified_files:
            if _check_interruption():
                return 3
            cb.on_log("INFO", f"Menyusun file EPUB hasil ke: {output_path.name}")
            EPUBBuilder.build(
                source_epub=input_path,
                output_epub=output_path,
                book=book,
                modified_files=modified_files,
                target_lang=config.target_lang,
            )

            # Validate
            cb.on_log("INFO", "Menjalankan validasi EPUB...")
            val = EPUBValidator(output_path)
            report = val.validate()

        elapsed = time.time() - start_time
        cb.on_complete(output_path, elapsed, report)
        return 0 if failed_chapters == 0 else 2

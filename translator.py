"""Gemini API translation engine with key rotation and fallback.

Uses the official google-genai SDK, Pydantic structured output, prompt
engineering for natural Indonesian novel translation, automatic API key
rotation (round-robin and quota limit fallback), and exponential backoff.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from config import Config, mask_key
from glossary import Glossary
from text_mapper import TranslatableSegment

logger = logging.getLogger(__name__)


class SegmentTranslation(BaseModel):
    """Structured translation unit for an individual segment."""

    id: str = Field(description="Segment identifier matching the source request exactly.")
    text: str = Field(description="Translated natural Indonesian text with inline tags preserved.")


class TranslationBatchResponse(BaseModel):
    """Structured response container for batch translation."""

    translations: List[SegmentTranslation] = Field(
        description="List of translated segments matching all requested segment IDs."
    )


@dataclass
class KeyRecord:
    """Tracks state and cooldown for a single API key."""

    key: str
    cooldown_until: float = 0.0
    failed_attempts: int = 0
    success_count: int = 0

    @property
    def is_available(self) -> bool:
        return time.time() >= self.cooldown_until


class KeyManager:
    """Manages rotation, quota cooldowns, and fallback across multiple Gemini API keys."""

    def __init__(
        self,
        api_keys: List[str],
        default_cooldown: float = 60.0,
        strategy: str = "round_robin",
    ) -> None:
        if not api_keys:
            self.records: List[KeyRecord] = []
        else:
            self.records = [KeyRecord(key=k) for k in api_keys]
        self.default_cooldown = default_cooldown
        self.strategy = strategy
        self._current_idx: int = 0

    def has_keys(self) -> bool:
        return len(self.records) > 0

    def get_active_key(self) -> str:
        """Return the next available healthy key, waiting if all are on cooldown."""
        if not self.records:
            raise ValueError(
                "Tidak ada Gemini API Key yang dikonfigurasi! "
                "Set environment variable GEMINI_API_KEY / GEMINI_API_KEYS atau gunakan opsi --api-keys."
            )

        n = len(self.records)
        now = time.time()

        # Check for available key starting from current index
        for i in range(n):
            idx = (self._current_idx + i) % n
            rec = self.records[idx]
            if rec.is_available:
                if self.strategy == "round_robin":
                    self._current_idx = (idx + 1) % n
                else:
                    self._current_idx = idx
                return rec.key

        # If all keys are in cooldown, find the one that expires earliest
        earliest_rec = min(self.records, key=lambda r: r.cooldown_until)
        wait_seconds = max(0.5, earliest_rec.cooldown_until - now)
        logger.warning(
            "Semua %d API key sedang cooldown/rate limited. Menunggu %.1f detik sampai key %s aktif kembali...",
            n,
            wait_seconds,
            mask_key(earliest_rec.key),
        )
        time.sleep(wait_seconds + 0.5)
        return earliest_rec.key

    def mark_rate_limited(self, key: str, cooldown_seconds: Optional[float] = None) -> None:
        """Mark an API key as rate-limited (HTTP 429) to trigger fallback."""
        cd = cooldown_seconds or self.default_cooldown
        for rec in self.records:
            if rec.key == key:
                rec.cooldown_until = time.time() + cd
                rec.failed_attempts += 1
                logger.warning(
                    "API Key %s mencapai limit kuota (429). Cooldown selama %.0f detik. Beralih ke fallback key.",
                    mask_key(key),
                    cd,
                )
                break

    def mark_success(self, key: str) -> None:
        """Mark key request success and clear failure counter."""
        for rec in self.records:
            if rec.key == key:
                rec.failed_attempts = 0
                rec.success_count += 1
                break

    def get_status_summary(self) -> str:
        """Return human-readable summary of key statuses."""
        if not self.records:
            return "No keys configured"
        items = []
        now = time.time()
        for rec in self.records:
            masked = mask_key(rec.key)
            if rec.is_available:
                items.append(f"{masked}(ready, ok:{rec.success_count})")
            else:
                remaining = int(rec.cooldown_until - now)
                items.append(f"{masked}(cooldown:{remaining}s)")
        return ", ".join(items)


class GeminiTranslator:
    """Translates text segments via Gemini API with structured outputs and resilience."""

    def __init__(
        self,
        config: Config,
        key_manager: Optional[KeyManager] = None,
        glossary: Optional[Glossary] = None,
    ) -> None:
        self.config = config
        self.key_manager = key_manager or KeyManager(
            config.api_keys,
            default_cooldown=config.key_cooldown_seconds,
            strategy=config.rotate_strategy,
        )
        self.glossary = glossary

    def build_system_instruction(self) -> str:
        """Construct the prompt instruction for literary novel translation."""
        glossary_part = self.glossary.format_for_prompt() if self.glossary else ""

        instruction = f"""Anda adalah penerjemah novel sastra dan fiksi profesional dari bahasa Inggris ({self.config.source_lang}) ke bahasa Indonesia ({self.config.target_lang}).

TUGAS DAN PRINSIP UTAMA:
1. Terjemahkan teks narasi dan dialog menjadi bahasa Indonesia yang luwes, alami, indah, dan mengalir seperti novel terbitan penerbit profesional (bukan terjemahan mesin harfiah).
2. Pertahankan emosi, suasana, ritme kalimat, humor, ketegangan, sudut pandang (POV), dan suara karakter sesuai intensi penulis asli.
3. HINDARI terjemahan kaku kata-demi-kata (translationese). Gunakan diksi bahasa Indonesia yang kaya dan idiomatik.
4. JANGAN meringkas, menghilangkan, menyingkat, mengarang, atau menambahkan isi cerita yang tidak ada di teks sumber.
5. PRESERVASI TAG INLINE HTML:
   - Teks sumber berisi tag inline seperti <em>, <i>, <strong>, <b>, <span>, atau <a href="...">.
   - Anda WAJIB mempertahankan tag-tag tersebut dan membungkusnya pada kata/frasa padanan terjemahan yang tepat di bahasa Indonesia.
   - Jangan mengubah atribut di dalam tag (misalnya href="..." atau class="...").
   - Jangan menambahkan tag baru di luar yang ada di sumber.
6. Kembalikan hasil dalam skema JSON terstruktur: setiap ID segmen harus diterjemahkan secara lengkap dan tidak boleh ada ID yang tertinggal atau kosong.
{glossary_part}"""
        return instruction.strip()

    def create_batches(
        self, segments: List[TranslatableSegment]
    ) -> List[List[TranslatableSegment]]:
        """Group segments into batches respecting paragraph count and character limits."""
        batches: List[List[TranslatableSegment]] = []
        current_batch: List[TranslatableSegment] = []
        current_chars = 0

        for seg in segments:
            seg_len = len(seg.inner_html)
            exceeds_count = len(current_batch) >= self.config.batch_size
            exceeds_chars = (current_chars + seg_len > self.config.max_batch_chars) and len(current_batch) > 0

            if exceeds_count or exceeds_chars:
                batches.append(current_batch)
                current_batch = [seg]
                current_chars = seg_len
            else:
                current_batch.append(seg)
                current_chars += seg_len

        if current_batch:
            batches.append(current_batch)

        return batches

    def translate_batch(
        self, batch: List[TranslatableSegment]
    ) -> Dict[str, str]:
        """Translate a single batch of segments with key rotation and retries."""
        if not batch:
            return {}

        expected_ids = {seg.id for seg in batch}

        # Prepare payload
        payload_items = [
            {"id": seg.id, "text": seg.inner_html}
            for seg in batch
        ]
        user_prompt = (
            "Terjemahkan segmen-segmen berikut ke dalam bahasa Indonesia sastra yang alami. "
            "Pertahankan tag inline HTML persis pada kata padanannya:\n\n"
            + json.dumps(payload_items, ensure_ascii=False, indent=2)
        )

        system_instruction = self.build_system_instruction()

        # Retry loop across available keys and attempts
        max_total_attempts = max(3, len(self.config.api_keys) * 2)
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt < max_total_attempts:
            attempt += 1
            active_key = self.key_manager.get_active_key()

            try:
                # Lazy import inside method to allow easy mock in tests
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=active_key)
                response = client.models.generate_content(
                    model=self.config.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.3,
                        response_mime_type="application/json",
                        response_schema=TranslationBatchResponse,
                    ),
                )

                # Parse and validate response
                result_text = response.text
                if not result_text:
                    raise ValueError("Empty response received from Gemini API")

                parsed_json = json.loads(result_text)
                translations_list = parsed_json.get("translations", [])

                result_map: Dict[str, str] = {}
                for item in translations_list:
                    seg_id = str(item.get("id", ""))
                    text_val = str(item.get("text", "")).strip()
                    if seg_id in expected_ids and text_val:
                        result_map[seg_id] = text_val

                # Validation: check all IDs were received
                missing_ids = expected_ids - set(result_map.keys())
                if missing_ids:
                    raise ValueError(f"Gemini API dropped {len(missing_ids)} segment(s): {list(missing_ids)[:5]}")

                # Success!
                self.key_manager.mark_success(active_key)
                return result_map

            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = (
                    "429" in err_str
                    or "quota" in err_str
                    or "resource_exhausted" in err_str
                    or "rate limit" in err_str
                )

                if is_rate_limit:
                    logger.warning("Key %s terkena rate limit: %s", mask_key(active_key), e)
                    self.key_manager.mark_rate_limited(active_key)
                else:
                    logger.warning("Percobaan %d gagal dengan key %s: %s", attempt, mask_key(active_key), e)
                    # Brief backoff for transient network issues
                    time.sleep(min(2.0 * attempt, 10.0))

                last_error = e

        raise RuntimeError(
            f"Gagal menerjemahkan batch setelah {attempt} percobaan. Error terakhir: {last_error}"
        )

    def calculate_dry_run_stats(
        self, segments: List[TranslatableSegment]
    ) -> Dict[str, Any]:
        """Calculate token and segment metrics for --dry-run without calling API."""
        batches = self.create_batches(segments)
        total_segments = len(segments)
        total_chars = sum(seg.char_count for seg in segments)
        total_words = sum(len(seg.plain_text.split()) for seg in segments)
        # Rough estimation: 1 word ~ 1.33 tokens
        est_tokens = int(total_words * 1.33)

        return {
            "total_segments": total_segments,
            "total_words": total_words,
            "total_chars": total_chars,
            "estimated_tokens": est_tokens,
            "total_batches": len(batches),
            "model": self.config.model,
            "api_keys_count": len(self.config.api_keys),
        }


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
    is_disabled: bool = False
    disable_reason: Optional[str] = None

    @property
    def is_available(self) -> bool:
        return not self.is_disabled and time.time() >= self.cooldown_until


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
        return any(not r.is_disabled for r in self.records)

    def get_active_key(self) -> str:
        """Return the next available healthy key, waiting if all are on cooldown."""
        active_records = [r for r in self.records if not r.is_disabled]
        if not active_records:
            raise ValueError(
                "Semua API Key Gemini tidak dapat digunakan (dinonaktifkan / 403 Permission Denied)! "
                "Periksa kunci API Anda di .env atau Google AI Studio."
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

        # If all non-disabled keys are in cooldown, find the one that expires earliest
        earliest_rec = min(active_records, key=lambda r: r.cooldown_until)
        wait_seconds = max(0.5, earliest_rec.cooldown_until - now)
        logger.warning(
            "Semua %d API key aktif sedang cooldown/rate limited. Menunggu %.1f detik sampai key %s aktif kembali...",
            len(active_records),
            wait_seconds,
            mask_key(earliest_rec.key),
        )
        time.sleep(wait_seconds + 0.5)
        return earliest_rec.key

    def mark_disabled(self, key: str, reason: str = "") -> None:
        """Permanently disable a key that returned 403 or invalid auth."""
        for rec in self.records:
            if rec.key == key:
                rec.is_disabled = True
                rec.disable_reason = reason
                logger.error(
                    "API Key %s dinonaktifkan (%s). Tidak akan digunakan lagi dalam sesi ini.",
                    mask_key(key),
                    reason,
                )
                break

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

                # Permissive safety settings for literary novel content
                safety_settings = [
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE,
                    ),
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE,
                    ),
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE,
                    ),
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE,
                    ),
                    types.SafetySetting(
                        category=types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
                        threshold=types.HarmBlockThreshold.BLOCK_NONE,
                    ),
                ]

                response = client.models.generate_content(
                    model=self.config.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.3,
                        response_mime_type="application/json",
                        response_schema=TranslationBatchResponse,
                        safety_settings=safety_settings,
                    ),
                )

                result_map: Dict[str, str] = {}

                # 1. Try parsed response directly from SDK
                if hasattr(response, "parsed") and response.parsed:
                    translations_list = getattr(response.parsed, "translations", [])
                    for item in translations_list:
                        seg_id = str(getattr(item, "id", ""))
                        text_val = str(getattr(item, "text", "")).strip()
                        if seg_id in expected_ids and text_val:
                            result_map[seg_id] = text_val

                # 2. Fallback to response.text if parsed is empty
                if len(result_map) < len(expected_ids):
                    result_text = response.text

                    # 3. If response.text is empty, inspect candidate parts
                    if not result_text and response.candidates:
                        c0 = response.candidates[0]
                        if c0.content and c0.content.parts:
                            parts_text = [
                                p.text for p in c0.content.parts
                                if getattr(p, "text", None)
                            ]
                            if parts_text:
                                result_text = "".join(parts_text)

                    if not result_text:
                        c_info = ""
                        if response.candidates:
                            c0 = response.candidates[0]
                            c_info = f" (finish_reason={c0.finish_reason}, safety={getattr(c0, 'safety_ratings', None)})"
                        raise ValueError(f"Empty response received from Gemini API{c_info}")

                    # Strip code fences if present
                    clean_text = result_text.strip()
                    if clean_text.startswith("```"):
                        import re
                        clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text)
                        clean_text = re.sub(r"\s*```$", "", clean_text)

                    parsed_json = json.loads(clean_text)
                    raw_list = parsed_json.get("translations", [])
                    for item in raw_list:
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
                is_perm_error = (
                    "403" in err_str
                    or "permission_denied" in err_str
                    or "denied access" in err_str
                    or "api_key_invalid" in err_str
                )
                is_rate_limit = (
                    "429" in err_str
                    or "quota" in err_str
                    or "resource_exhausted" in err_str
                    or "rate limit" in err_str
                    or "503" in err_str
                    or "unavailable" in err_str
                )

                if is_perm_error:
                    logger.error("Key %s ditolak aksesnya (403): %s", mask_key(active_key), e)
                    self.key_manager.mark_disabled(active_key, "403 PERMISSION_DENIED / Project Denied Access")
                elif is_rate_limit:
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


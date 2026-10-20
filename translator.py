"""Gemini API translation engine with key rotation and fallback.

Uses the official google-genai SDK, Pydantic structured output, prompt
engineering for natural Indonesian novel translation, automatic API key
rotation (round-robin and quota limit fallback), and exponential backoff.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from config import Config, mask_key
from glossary import Glossary
from text_mapper import TranslatableSegment

logger = logging.getLogger(__name__)


@dataclass
class GeminiQuotaDetails:
    """Structured representation of quota limit details extracted from Gemini API errors."""

    is_quota_error: bool = False
    limit_type: str = "UNKNOWN"  # "RPM", "TPM", "RPD", "ZERO_LIMIT", "UNKNOWN"
    quota_id: Optional[str] = None
    quota_metric: Optional[str] = None
    model: Optional[str] = None
    limit_value: Optional[str] = None
    retry_delay: Optional[float] = None
    reason: Optional[str] = None
    message: str = ""

    @property
    def is_daily_or_zero(self) -> bool:
        """True if the limit is a non-transient limit (daily RPD or limit: 0)."""
        return self.limit_type in ("RPD", "ZERO_LIMIT")


class GeminiDailyQuotaExhaustedError(Exception):
    """Raised when Gemini API daily quota (RPD) or zero quota (limit: 0) is encountered.

    Automatic retries must stop immediately when this occurs across all available keys.
    """

    def __init__(self, message: str, quota_details: Optional[GeminiQuotaDetails] = None) -> None:
        super().__init__(message)
        self.quota_details = quota_details


def extract_gemini_quota_details(
    error: Exception, default_model: Optional[str] = None
) -> GeminiQuotaDetails:
    """Extract quota failure details (quotaId, quotaMetric, model, retryDelay, limit_type).

    Parses both structured Google GenAI SDK ClientError / APIError payloads and
    textual representations.
    """
    err_str = str(error)
    code = getattr(error, "code", None)
    status = getattr(error, "status", None)

    is_429 = code == 429 or "429" in err_str
    is_resource_exhausted = (
        status == "RESOURCE_EXHAUSTED"
        or "resource_exhausted" in err_str.lower()
        or "quota" in err_str.lower()
        or "rate limit" in err_str.lower()
    )

    if not (is_429 or is_resource_exhausted):
        return GeminiQuotaDetails(is_quota_error=False, message=err_str)

    quota_id: Optional[str] = None
    quota_metric: Optional[str] = None
    model: Optional[str] = None
    limit_value: Optional[str] = None
    retry_delay: Optional[float] = None
    reason: Optional[str] = None

    # 1. Parse structured details if present on the exception object
    raw_details = getattr(error, "details", None)
    details_list: List[Dict[str, Any]] = []

    if isinstance(raw_details, dict):
        details_list = raw_details.get("error", {}).get("details", []) or raw_details.get("details", [])
    elif isinstance(raw_details, list):
        details_list = raw_details

    # If details_list is empty, try to extract json from err_str
    if not details_list:
        try:
            json_start = err_str.find("{")
            json_end = err_str.rfind("}")
            if json_start != -1 and json_end != -1 and json_end > json_start:
                cand = json.loads(err_str[json_start : json_end + 1])
                if isinstance(cand, dict):
                    details_list = cand.get("error", {}).get("details", []) or cand.get("details", [])
        except Exception:
            pass

    for item in details_list:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("@type", ""))

        if "ErrorInfo" in item_type or "reason" in item:
            reason = item.get("reason", reason)
            meta = item.get("metadata", {})
            if isinstance(meta, dict):
                quota_id = meta.get("quotaId") or quota_id
                quota_metric = meta.get("quotaMetric") or quota_metric
                model = meta.get("model") or model
                limit_value = meta.get("quotaLimit") or meta.get("quotaLimitValue") or limit_value

        if "RetryInfo" in item_type or "retryDelay" in item:
            raw_delay = item.get("retryDelay")
            if isinstance(raw_delay, (int, float)):
                retry_delay = float(raw_delay)
            elif isinstance(raw_delay, str):
                m = re.search(r"(\d+(?:\.\d+)?)", raw_delay)
                if m:
                    retry_delay = float(m.group(1))

        if "QuotaFailure" in item_type or "violations" in item:
            violations = item.get("violations", [])
            for v in violations:
                if isinstance(v, dict):
                    desc = v.get("description", "")
                    if not quota_metric:
                        m = re.search(r"quota metric ['\"]([^'\"]+)['\"]", desc)
                        if m:
                            quota_metric = m.group(1)
                    if not limit_value:
                        m = re.search(r"limit ['\"]?(\d+)['\"]?", desc)
                        if m:
                            limit_value = m.group(1)

    # 2. Check HTTP headers (Retry-After) if available
    response_obj = getattr(error, "response", None)
    if response_obj and hasattr(response_obj, "headers") and retry_delay is None:
        hdr = response_obj.headers.get("retry-after") or response_obj.headers.get("Retry-After")
        if hdr:
            try:
                retry_delay = float(hdr)
            except ValueError:
                pass

    # 3. Text fallback with regex
    if not quota_id:
        m = re.search(r"quotaId['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", err_str, re.IGNORECASE)
        if m:
            quota_id = m.group(1)

    if not quota_metric:
        m = re.search(r"quotaMetric['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", err_str, re.IGNORECASE)
        if m:
            quota_metric = m.group(1)

    if not limit_value:
        m = re.search(r"(?:limit|quotaLimit)['\"]?\s*[:=]?\s*['\"]?(\d+)['\"]?", err_str, re.IGNORECASE)
        if m:
            limit_value = m.group(1)

    if not model:
        m = re.search(r"models/([a-zA-Z0-9\.\-]+)", err_str, re.IGNORECASE)
        if m:
            model = m.group(1)
        else:
            m = re.search(r"\b(gemini-[a-zA-Z0-9\.\-]+)\b", err_str, re.IGNORECASE)
            if m:
                model = m.group(1)
            else:
                model = default_model

    if retry_delay is None:
        m = re.search(r"retry(?:delay)?\s*(?:after|in)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*s\b", err_str, re.IGNORECASE)
        if m:
            retry_delay = float(m.group(1))
        else:
            m = re.search(r"retry\s+after\s+(\d+(?:\.\d+)?)\s+seconds?", err_str, re.IGNORECASE)
            if m:
                retry_delay = float(m.group(1))

    # 4. Classify limit_type: ZERO_LIMIT, RPD, TPM, RPM, UNKNOWN
    combined_text = f"{err_str} {quota_id or ''} {quota_metric or ''}".lower()

    if limit_value == "0" or re.search(r"\blimit\s*[:=]?\s*['\"]?0['\"]?\b", combined_text):
        limit_type = "ZERO_LIMIT"
    elif any(k in combined_text for k in ["perday", "requestsperday", "per_day", "rpd", "daily", "per day"]):
        limit_type = "RPD"
    elif any(k in combined_text for k in ["tokensperminute", "input_tokens", "output_tokens", "tpm", "tokens per minute"]) or (
        "token" in combined_text and "minute" in combined_text
    ):
        limit_type = "TPM"
    elif any(k in combined_text for k in ["perminute", "requestsperminute", "per_minute", "rpm", "requests per minute"]) or (
        "request" in combined_text and "minute" in combined_text
    ):
        limit_type = "RPM"
    elif retry_delay is not None and retry_delay <= 120:
        limit_type = "RPM"
    else:
        limit_type = "UNKNOWN"

    return GeminiQuotaDetails(
        is_quota_error=True,
        limit_type=limit_type,
        quota_id=quota_id,
        quota_metric=quota_metric,
        model=model,
        limit_value=limit_value,
        retry_delay=retry_delay,
        reason=reason,
        message=getattr(error, "message", None) or err_str,
    )


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
    daily_exhausted: bool = False
    disable_reason: Optional[str] = None

    @property
    def is_available(self) -> bool:
        return (
            not self.is_disabled
            and not self.daily_exhausted
            and time.time() >= self.cooldown_until
        )


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

    def has_available_keys_today(self) -> bool:
        """Check if any keys are not permanently disabled and not daily exhausted."""
        return any(not r.is_disabled and not r.daily_exhausted for r in self.records)

    def get_active_key(self, max_wait: float = 300.0) -> str:
        """Return the next available healthy key, waiting if all are on temporary cooldown."""
        active_records = [r for r in self.records if not r.is_disabled and not r.daily_exhausted]
        if not active_records:
            daily_count = sum(1 for r in self.records if r.daily_exhausted)
            if daily_count > 0:
                raise GeminiDailyQuotaExhaustedError(
                    f"Semua ({len(self.records)}) API Key Gemini telah mencapai batas kuota harian (RPD) "
                    "atau limit 0. Translasi tidak dapat dilanjutkan hari ini."
                )
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
            if not rec.is_disabled and not rec.daily_exhausted and rec.is_available:
                if self.strategy == "round_robin":
                    self._current_idx = (idx + 1) % n
                else:
                    self._current_idx = idx
                return rec.key

        # If all non-disabled keys are in temporary cooldown, find the one that expires earliest
        earliest_rec = min(active_records, key=lambda r: r.cooldown_until)
        wait_seconds = max(0.1, earliest_rec.cooldown_until - now)
        if wait_seconds > max_wait:
            raise TimeoutError(
                f"Waktu tunggu cooldown kunci ({wait_seconds:.1f}s) melebihi batas maksimum ({max_wait}s)."
            )

        logger.warning(
            "Semua %d API key aktif sedang cooldown/rate limited (RPM/TPM). "
            "Menunggu %.1f detik sampai key %s aktif kembali...",
            len(active_records),
            wait_seconds,
            mask_key(earliest_rec.key),
        )
        time.sleep(wait_seconds + 0.2)
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

    def mark_daily_exhausted(
        self, key: str, quota_details: Optional[GeminiQuotaDetails] = None
    ) -> None:
        """Mark an API key as exhausted for the day (RPD or limit: 0)."""
        for rec in self.records:
            if rec.key == key:
                rec.daily_exhausted = True
                type_str = quota_details.limit_type if quota_details else "RPD"
                rec.disable_reason = f"Quota Exhausted: {type_str}"
                logger.error(
                    "API Key %s mencapai limit harian/kuota nol (%s). Dinonaktifkan untuk sesi ini.",
                    mask_key(key),
                    type_str,
                )
                break

    def mark_rate_limited(
        self,
        key: str,
        cooldown_seconds: Optional[float] = None,
        quota_details: Optional[GeminiQuotaDetails] = None,
    ) -> None:
        """Mark an API key as temporarily rate-limited (RPM/TPM) to trigger backoff/fallback."""
        cd = cooldown_seconds if cooldown_seconds is not None else self.default_cooldown
        for rec in self.records:
            if rec.key == key:
                rec.cooldown_until = time.time() + cd
                rec.failed_attempts += 1
                limit_info = f" ({quota_details.limit_type})" if quota_details else ""
                logger.warning(
                    "API Key %s terkena rate limit%s (429). Cooldown %.1f detik.",
                    mask_key(key),
                    limit_info,
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
            if rec.daily_exhausted:
                items.append(f"{masked}(daily_exhausted)")
            elif rec.is_disabled:
                items.append(f"{masked}(disabled)")
            elif rec.is_available:
                items.append(f"{masked}(ready, ok:{rec.success_count})")
            else:
                remaining = max(0, int(rec.cooldown_until - now))
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
        max_attempts = getattr(self.config, "max_retries", 5)
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt < max_attempts:
            attempt += 1
            active_key = self.key_manager.get_active_key()

            try:
                # Lazy import inside method to allow easy mock in tests
                from google import genai
                from google.genai import types

                timeout_ms = int(self.config.request_timeout * 1000)
                client = genai.Client(
                    api_key=active_key,
                    http_options=types.HttpOptions(timeout=timeout_ms),
                )

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
                        if hasattr(response, "prompt_feedback") and response.prompt_feedback:
                            pb = response.prompt_feedback
                            if getattr(pb, "block_reason", None):
                                c_info += f" [prompt_blocked={pb.block_reason}]"
                        if response.candidates:
                            c0 = response.candidates[0]
                            c_info += f" (finish_reason={c0.finish_reason}, safety={getattr(c0, 'safety_ratings', None)})"
                        raise ValueError(f"Empty response received from Gemini API{c_info}")

                    # Strip code fences if present
                    clean_text = result_text.strip()
                    if clean_text.startswith("```"):
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
                last_error = e
                err_str = str(e).lower()
                is_perm_error = (
                    "403" in err_str
                    or "permission_denied" in err_str
                    or "denied access" in err_str
                    or "api_key_invalid" in err_str
                )

                if is_perm_error:
                    logger.error("Key %s ditolak aksesnya (403): %s", mask_key(active_key), e)
                    self.key_manager.mark_disabled(active_key, "403 PERMISSION_DENIED")
                    continue

                # Check if this is a Gemini Quota / 429 error
                quota_details = extract_gemini_quota_details(e, default_model=self.config.model)

                if quota_details.is_quota_error:
                    logger.warning(
                        "Quota/Rate Limit terdeteksi pada key %s [Jenis: %s, Model: %s, QuotaId: %s, Metric: %s, RetryDelay: %s]",
                        mask_key(active_key),
                        quota_details.limit_type,
                        quota_details.model,
                        quota_details.quota_id,
                        quota_details.quota_metric,
                        f"{quota_details.retry_delay}s" if quota_details.retry_delay is not None else "None",
                    )

                    # RPD or ZERO_LIMIT: STOP endless retries!
                    if quota_details.is_daily_or_zero:
                        self.key_manager.mark_daily_exhausted(active_key, quota_details)
                        if not self.key_manager.has_available_keys_today():
                            raise GeminiDailyQuotaExhaustedError(
                                f"Batas kuota harian ({quota_details.limit_type}) atau kuota 0 tercapai pada model {quota_details.model}. "
                                f"Quota ID: {quota_details.quota_id or '-'}, Metric: {quota_details.quota_metric or '-'}. "
                                "Retry otomatis dihentikan agar tidak melebihi batas kuota. Simpan progres dan lanjutkan nanti.",
                                quota_details=quota_details,
                            )
                        # Other keys might still be available
                        continue

                    # Per-minute limits (RPM / TPM): exponential backoff with jitter and respect retryDelay
                    jitter = random.uniform(1.0, 3.0)
                    if quota_details.retry_delay is not None and quota_details.retry_delay > 0:
                        backoff = quota_details.retry_delay + jitter
                        logger.warning(
                            "Menghormati retryDelay dari Gemini API: %.1fs (+ jitter %.1fs = %.1fs)",
                            quota_details.retry_delay,
                            jitter,
                            backoff,
                        )
                    else:
                        # Exponential backoff with jitter
                        base_backoff = min(60.0, 5.0 * (2 ** (attempt - 1)))
                        backoff = base_backoff + random.uniform(0.5, 2.5)
                        logger.warning(
                            "Exponential backoff dengan jitter untuk %s: %.1fs (attempt %d/%d)",
                            quota_details.limit_type,
                            backoff,
                            attempt,
                            max_attempts,
                        )

                    self.key_manager.mark_rate_limited(
                        active_key, cooldown_seconds=backoff, quota_details=quota_details
                    )
                    continue

                # Check if error is Empty response, safety filter, or dropped segments
                is_throttle = "empty response" in err_str or "dropped" in err_str or "prompt_blocked" in err_str
                if is_throttle:
                    throttle_delay = min(25.0, 3.5 * attempt + random.uniform(1.0, 2.5))
                    logger.warning(
                        "Respons kosong/pembatasan dari Gemini API pada percobaan %d/%d dengan key %s. Cooldown %.1fs...",
                        attempt,
                        max_attempts,
                        mask_key(active_key),
                        throttle_delay,
                    )
                    time.sleep(throttle_delay)
                    continue

                # Network error or transient exception
                is_network = (
                    isinstance(e, (ConnectionError, TimeoutError, OSError))
                    or any(
                        w in err_str
                        for w in ["connect", "timeout", "timed out", "connection reset", "network", "remote protocol error"]
                    )
                )
                net_jitter = random.uniform(0.5, 1.5)
                net_delay = min(30.0, 2.0 * attempt) + net_jitter
                if is_network:
                    logger.warning(
                        "Network error pada percobaan %d/%d dengan key %s: %s. Backoff %.1fs...",
                        attempt,
                        max_attempts,
                        mask_key(active_key),
                        e,
                        net_delay,
                    )
                else:
                    logger.warning(
                        "Percobaan %d/%d gagal dengan key %s: %s. Backoff %.1fs...",
                        attempt,
                        max_attempts,
                        mask_key(active_key),
                        e,
                        net_delay,
                    )
                time.sleep(net_delay)

        # After all attempts exhausted:
        # If the failure is due to content safety filter or empty response:
        # Sub-divide the batch or gracefully preserve original text so novel translation never crashes!
        err_msg = str(last_error).lower()
        if "empty response" in err_msg or "blocked" in err_msg or "dropped" in err_msg:
            if len(batch) > 1:
                logger.warning(
                    "Batch (%d segmen) gagal respons Gemini (%s). Mencoba menerjemahkan per segmen secara individual...",
                    len(batch),
                    last_error,
                )
                sub_map: Dict[str, str] = {}
                for single_seg in batch:
                    try:
                        res = self.translate_batch([single_seg])
                        sub_map.update(res)
                    except Exception as sub_err:
                        logger.warning(
                            "Segmen %s tidak dapat diterjemahkan (%s). Mempertahankan teks asli agar buku tidak gagal.",
                            single_seg.id,
                            sub_err,
                        )
                        sub_map[single_seg.id] = single_seg.inner_html
                return sub_map

            # Single segment fallback
            logger.warning(
                "Segmen %s diblokir atau respons kosong (%s). Mempertahankan teks asli agar buku tidak gagal.",
                batch[0].id,
                last_error,
            )
            return {batch[0].id: batch[0].inner_html}

        raise RuntimeError(
            f"Gagal menerjemahkan batch setelah {attempt} percobaan (batas maksimum: {max_attempts}). Error terakhir: {last_error}"
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
        batches_count = len(batches)

        # Free Tier estimation
        min_minutes_rpm = round(batches_count / 15.0, 1)
        rpd_limit = 1500
        fits_daily = batches_count <= rpd_limit

        return {
            "total_segments": total_segments,
            "total_words": total_words,
            "total_chars": total_chars,
            "estimated_tokens": est_tokens,
            "total_batches": batches_count,
            "model": self.config.model,
            "api_keys_count": len(self.config.api_keys),
            "free_tier_rpm_min_minutes": min_minutes_rpm,
            "free_tier_rpd_fits": fits_daily,
            "free_tier_rpd_limit": rpd_limit,
        }


class OllamaTranslator:
    """Translates text segments using a local Ollama model (e.g. translategemma:4b)."""

    def __init__(
        self,
        config: Config,
        glossary: Optional[Glossary] = None,
    ) -> None:
        self.config = config
        self.glossary = glossary
        self.base_url = (config.ollama_base_url or "http://localhost:11434").rstrip("/")

    def check_connection(self) -> bool:
        """Verify that Ollama server is reachable and responsive."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/version", method="GET")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                code = getattr(resp, "status", None)
                if code is None and hasattr(resp, "getcode"):
                    code = resp.getcode()
                return code == 200
        except Exception:
            return False

    def build_system_instruction(self) -> str:
        """Build translation instructions for literary Indonesian translation."""
        glossary_part = self.glossary.format_for_prompt() if self.glossary else ""
        instruction = (
            f"You are a professional literary translator from English ({self.config.source_lang}) to Indonesian ({self.config.target_lang}).\n"
            "Your goal is to accurately convey the meaning of the source text while maintaining a natural, literary Indonesian tone.\n"
            "Preserve all segment tags like [segment_id] and preserve all inline HTML tags like <em>, <strong>, <i>, <b>, <span>, <a href=\"...\"> wrapping the corresponding translated Indonesian words.\n"
            "Translate line by line matching each segment tag."
        )
        if glossary_part:
            instruction += f"\n\n{glossary_part}"
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

    def _call_ollama(self, prompt: str, timeout: Optional[float] = None) -> str:
        """Execute a generate request to Ollama HTTP API."""
        import json
        import urllib.error
        import urllib.request

        url = f"{self.base_url}/api/generate"
        req_timeout = timeout or self.config.request_timeout

        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.95,
            },
        }

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                res_body = json.loads(resp.read().decode("utf-8"))
                return res_body.get("response", "").strip()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError(
                    f"Model '{self.config.model}' tidak ditemukan di Ollama ({self.base_url}). "
                    f"Jalankan 'ollama pull {self.config.model}' terlebih dahulu."
                ) from e
            raise RuntimeError(f"Ollama HTTP error {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Tidak dapat terhubung ke Ollama di {self.base_url}. "
                f"Pastikan Ollama sudah aktif ('ollama serve'). Error: {e.reason}"
            ) from e

    def _parse_segmented_response(self, text: str) -> Dict[str, str]:
        """Parse tagged segments from model output."""
        import re

        parts = re.split(r"\[([a-zA-Z0-9_\-]+)\]", text)
        result: Dict[str, str] = {}
        for i in range(1, len(parts), 2):
            tag = parts[i].strip()
            val = parts[i + 1].strip()
            if tag and val:
                result[tag] = val
        return result

    def _translate_single(self, seg: TranslatableSegment) -> str:
        """Fallback to translate a single segment if dropped from batch."""
        import re

        instruction = self.build_system_instruction()
        prompt = (
            f"{instruction}\n\n"
            f"Translate the following segment directly. Preserve inline HTML tags:\n"
            f"[{seg.id}] {seg.inner_html}"
        )
        resp_text = self._call_ollama(prompt, timeout=self.config.request_timeout)
        parsed = self._parse_segmented_response(resp_text)
        if seg.id in parsed and parsed[seg.id]:
            return parsed[seg.id]
        cleaned = re.sub(r"^\[.*?\]\s*", "", resp_text).strip()
        return cleaned or seg.inner_html

    def translate_batch(
        self, batch: List[TranslatableSegment]
    ) -> Dict[str, str]:
        """Translate a batch of segments using Ollama with automatic retries and fallback."""
        if not batch:
            return {}

        expected_ids = {seg.id for seg in batch}
        instruction = self.build_system_instruction()

        segment_lines = [f"[{seg.id}] {seg.inner_html}" for seg in batch]
        prompt = (
            f"{instruction}\n\n"
            f"Translate the following segments:\n"
            + "\n".join(segment_lines)
        )

        max_attempts = getattr(self.config, "max_retries", 3)
        attempt = 0
        last_error: Optional[Exception] = None

        while attempt < max_attempts:
            attempt += 1
            try:
                raw_response = self._call_ollama(prompt)
                result_map = self._parse_segmented_response(raw_response)

                missing_ids = expected_ids - set(result_map.keys())
                if missing_ids:
                    logger.warning(
                        "Batch kekurangan %d segmen (%s). Melakukan fallback translasi individual...",
                        len(missing_ids),
                        list(missing_ids),
                    )
                    id_to_seg = {s.id: s for s in batch}
                    for mid in missing_ids:
                        seg = id_to_seg[mid]
                        result_map[mid] = self._translate_single(seg)

                return result_map

            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if "tidak ditemukan" in err_str or "tidak dapat terhubung" in err_str:
                    raise

                wait_sec = min(20.0, 2.0 * attempt)
                logger.warning(
                    "Ollama request gagal pada percobaan %d/%d: %s. Menunggu %.1fs...",
                    attempt,
                    max_attempts,
                    e,
                    wait_sec,
                )
                time.sleep(wait_sec)

        raise RuntimeError(
            f"Gagal menerjemahkan batch melalui Ollama setelah {attempt} percobaan. Error terakhir: {last_error}"
        )

    def calculate_dry_run_stats(
        self, segments: List[TranslatableSegment]
    ) -> Dict[str, Any]:
        """Calculate token and segment metrics for --dry-run for local Ollama model."""
        batches = self.create_batches(segments)
        total_segments = len(segments)
        total_chars = sum(seg.char_count for seg in segments)
        total_words = sum(len(seg.plain_text.split()) for seg in segments)
        est_tokens = int(total_words * 1.33)
        batches_count = len(batches)

        est_seconds = batches_count * 7.0
        est_minutes = round(est_seconds / 60.0, 1)

        return {
            "total_segments": total_segments,
            "total_words": total_words,
            "total_chars": total_chars,
            "estimated_tokens": est_tokens,
            "total_batches": batches_count,
            "model": self.config.model,
            "provider": "ollama",
            "base_url": self.base_url,
            "estimated_local_minutes": est_minutes,
        }


def get_translator(
    config: Config,
    glossary: Optional[Glossary] = None,
    key_manager: Optional[KeyManager] = None,
):
    """Factory function returning OllamaTranslator or GeminiTranslator based on config."""
    if getattr(config, "provider", "ollama") == "gemini":
        return GeminiTranslator(config, key_manager=key_manager, glossary=glossary)
    return OllamaTranslator(config, glossary=glossary)


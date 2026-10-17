"""Tests for GeminiTranslator with mocked google-genai SDK."""

import json
from unittest.mock import MagicMock, patch
import pytest
from config import Config
from text_mapper import TranslatableSegment
from translator import GeminiTranslator, KeyManager


@pytest.fixture
def mock_segments():
    return [
        TranslatableSegment(
            id="s001",
            inner_html="The morning sun rose.",
            plain_text="The morning sun rose.",
            char_count=21,
            element=None,
        ),
        TranslatableSegment(
            id="s002",
            inner_html='"Hurry!" he <em>shouted</em>.',
            plain_text='"Hurry!" he shouted.',
            char_count=22,
            element=None,
        ),
    ]


def test_dry_run_stats(mock_segments):
    config = Config(model="gemini-3.5-flash", api_keys=["dummy_key"])
    translator = GeminiTranslator(config)

    stats = translator.calculate_dry_run_stats(mock_segments)
    assert stats["total_segments"] == 2
    assert stats["total_words"] == 7
    assert stats["total_batches"] == 1
    assert stats["model"] == "gemini-3.5-flash"


def test_translate_batch_success(mock_segments):
    config = Config(api_keys=["key1", "key2"])
    translator = GeminiTranslator(config)

    # Prepare mock response
    mock_payload = {
        "translations": [
            {"id": "s001", "text": "Matahari pagi terbit."},
            {"id": "s002", "text": '"Cepat!" ia <em>berteriak</em>.'},
        ]
    }
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(mock_payload)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_resp

    with patch("google.genai.Client", return_value=mock_client):
        result = translator.translate_batch(mock_segments)

    assert result["s001"] == "Matahari pagi terbit."
    assert result["s002"] == '"Cepat!" ia <em>berteriak</em>.'


def test_translate_batch_fallback_on_429(mock_segments):
    km = KeyManager(["keyA", "keyB"], strategy="round_robin")
    config = Config(api_keys=["keyA", "keyB"])
    translator = GeminiTranslator(config, key_manager=km)

    call_count = 0

    def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # KeyA hits 429
            raise Exception("HTTP 429: Resource has been exhausted (e.g. check quota).")
        # KeyB succeeds
        resp = MagicMock()
        resp.text = json.dumps(
            {
                "translations": [
                    {"id": "s001", "text": "Terjemahan A"},
                    {"id": "s002", "text": "Terjemahan B"},
                ]
            }
        )
        return resp

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate

    with patch("google.genai.Client", return_value=mock_client):
        result = translator.translate_batch(mock_segments)

    assert result["s001"] == "Terjemahan A"
    assert call_count == 2
    # Verify keyA is now on cooldown
    rec_a = next(r for r in km.records if r.key == "keyA")
    assert not rec_a.is_available


def test_extract_gemini_quota_details_rpm():
    from google.genai.errors import ClientError
    from translator import extract_gemini_quota_details

    err_payload = {
        "error": {
            "code": 429,
            "message": "Resource has been exhausted (e.g. check quota).",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "RATE_LIMIT_EXCEEDED",
                    "domain": "googleapis.com",
                    "metadata": {
                        "quotaId": "GenerateContentRequestsPerMinutePerProjectPerRegion",
                        "quotaMetric": "generativelanguage.googleapis.com/generate_content_requests",
                        "quotaLimit": "15",
                        "model": "gemini-2.5-flash",
                    },
                },
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "43s",
                },
            ],
        }
    }
    error = ClientError(429, err_payload)
    details = extract_gemini_quota_details(error)

    assert details.is_quota_error is True
    assert details.limit_type == "RPM"
    assert details.quota_id == "GenerateContentRequestsPerMinutePerProjectPerRegion"
    assert details.quota_metric == "generativelanguage.googleapis.com/generate_content_requests"
    assert details.model == "gemini-2.5-flash"
    assert details.retry_delay == 43.0
    assert details.limit_value == "15"
    assert details.is_daily_or_zero is False


def test_extract_gemini_quota_details_rpd():
    from google.genai.errors import ClientError
    from translator import extract_gemini_quota_details

    err_payload = {
        "error": {
            "code": 429,
            "message": "Quota exceeded for quota metric 'GenerateContentRequestsPerDayPerProjectPerRegion' and limit '1500'.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "QUOTA_EXCEEDED",
                    "metadata": {
                        "quotaId": "GenerateContentRequestsPerDayPerProjectPerRegion",
                        "quotaMetric": "generativelanguage.googleapis.com/generate_content_requests_per_day",
                        "quotaLimit": "1500",
                        "model": "gemini-2.5-flash",
                    },
                }
            ],
        }
    }
    error = ClientError(429, err_payload)
    details = extract_gemini_quota_details(error)

    assert details.is_quota_error is True
    assert details.limit_type == "RPD"
    assert details.is_daily_or_zero is True
    assert details.quota_id == "GenerateContentRequestsPerDayPerProjectPerRegion"
    assert details.limit_value == "1500"


def test_extract_gemini_quota_details_zero_limit():
    from google.genai.errors import ClientError
    from translator import extract_gemini_quota_details

    err_payload = {
        "error": {
            "code": 429,
            "message": "Quota exceeded with limit: 0",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "RATE_LIMIT_EXCEEDED",
                    "metadata": {
                        "quotaId": "GenerateContentRequestsPerMinutePerProjectPerRegion",
                        "quotaLimit": "0",
                        "model": "gemini-2.5-pro",
                    },
                }
            ],
        }
    }
    error = ClientError(429, err_payload)
    details = extract_gemini_quota_details(error)

    assert details.is_quota_error is True
    assert details.limit_type == "ZERO_LIMIT"
    assert details.is_daily_or_zero is True


def test_extract_gemini_quota_details_tpm():
    from google.genai.errors import ClientError
    from translator import extract_gemini_quota_details

    err_payload = {
        "error": {
            "code": 429,
            "message": "Resource has been exhausted.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "metadata": {
                        "quotaId": "GenerateContentInputTokensPerMinutePerProjectPerRegion",
                        "quotaMetric": "generativelanguage.googleapis.com/generate_content_input_tokens",
                        "model": "gemini-2.5-flash",
                    },
                },
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "20.5s",
                },
            ],
        }
    }
    error = ClientError(429, err_payload)
    details = extract_gemini_quota_details(error)

    assert details.is_quota_error is True
    assert details.limit_type == "TPM"
    assert details.retry_delay == 20.5
    assert details.is_daily_or_zero is False


def test_translate_batch_rpm_honors_retry_delay_and_succeeds(mock_segments):
    from google.genai.errors import ClientError

    config = Config(api_keys=["key1"], max_retries=3)
    translator = GeminiTranslator(config)

    rpm_err = ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "Resource has been exhausted.",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "metadata": {
                            "quotaId": "GenerateContentRequestsPerMinutePerProjectPerRegion",
                            "model": "gemini-2.5-flash",
                        },
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "5s",
                    },
                ],
            }
        },
    )

    success_resp = MagicMock()
    success_resp.text = json.dumps(
        {
            "translations": [
                {"id": "s001", "text": "Matahari terbit"},
                {"id": "s002", "text": "Cepat teriak"},
            ]
        }
    )

    call_count = 0

    def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise rpm_err
        return success_resp

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate

    with patch("google.genai.Client", return_value=mock_client), patch("time.sleep") as mock_sleep:
        res = translator.translate_batch(mock_segments)

    assert res["s001"] == "Matahari terbit"
    assert call_count == 2
    # Verify sleep was called honoring retryDelay (>= 5.0s)
    assert mock_sleep.called
    slept_time = mock_sleep.call_args[0][0]
    assert slept_time >= 5.0


def test_translate_batch_daily_quota_stops_immediately_without_infinite_retry(mock_segments):
    from google.genai.errors import ClientError
    from translator import GeminiDailyQuotaExhaustedError

    config = Config(api_keys=["key1"], max_retries=5)
    translator = GeminiTranslator(config)

    rpd_err = ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "Quota exceeded for quota metric 'GenerateContentRequestsPerDayPerProjectPerRegion'",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "QUOTA_EXCEEDED",
                        "metadata": {
                            "quotaId": "GenerateContentRequestsPerDayPerProjectPerRegion",
                            "quotaLimit": "1500",
                            "model": "gemini-2.5-flash",
                        },
                    }
                ],
            }
        },
    )

    call_count = 0

    def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise rpd_err

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate

    with patch("google.genai.Client", return_value=mock_client):
        with pytest.raises(GeminiDailyQuotaExhaustedError) as exc_info:
            translator.translate_batch(mock_segments)

    # Must stop immediately on 1st call without retrying up to max_retries!
    assert call_count == 1
    assert exc_info.value.quota_details.limit_type == "RPD"


def test_translate_batch_zero_limit_stops_immediately(mock_segments):
    from google.genai.errors import ClientError
    from translator import GeminiDailyQuotaExhaustedError

    config = Config(api_keys=["key1"], max_retries=5)
    translator = GeminiTranslator(config)

    zero_err = ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "Quota exceeded: limit 0",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "metadata": {
                            "quotaLimit": "0",
                            "model": "gemini-2.5-flash",
                        },
                    }
                ],
            }
        },
    )

    call_count = 0

    def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise zero_err

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate

    with patch("google.genai.Client", return_value=mock_client):
        with pytest.raises(GeminiDailyQuotaExhaustedError):
            translator.translate_batch(mock_segments)

    assert call_count == 1


def test_translate_batch_network_error_backoff_and_retry(mock_segments):
    config = Config(api_keys=["key1"], max_retries=3)
    translator = GeminiTranslator(config)

    call_count = 0

    def mock_generate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("Connection reset by peer")
        resp = MagicMock()
        resp.text = json.dumps(
            {
                "translations": [
                    {"id": "s001", "text": "Sukses 1"},
                    {"id": "s002", "text": "Sukses 2"},
                ]
            }
        )
        return resp

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate

    with patch("google.genai.Client", return_value=mock_client), patch("time.sleep") as mock_sleep:
        res = translator.translate_batch(mock_segments)

    assert res["s001"] == "Sukses 1"
    assert call_count == 2
    assert mock_sleep.called


def test_translate_batch_max_retries_exceeded(mock_segments):
    config = Config(api_keys=["key1"], max_retries=3)
    translator = GeminiTranslator(config)

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = ConnectionError("Network down")

    with patch("google.genai.Client", return_value=mock_client), patch("time.sleep"):
        with pytest.raises(RuntimeError) as exc_info:
            translator.translate_batch(mock_segments)

    assert "batas maksimum: 3" in str(exc_info.value)



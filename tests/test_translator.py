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
    config = Config(api_keys=["dummy_key"])
    translator = GeminiTranslator(config)

    stats = translator.calculate_dry_run_stats(mock_segments)
    assert stats["total_segments"] == 2
    assert stats["total_words"] == 7
    assert stats["total_batches"] == 1
    assert stats["model"] == "gemini-2.5-flash"


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

"""Unit tests for OllamaTranslator and get_translator factory."""

import json
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from config import Config
from glossary import Glossary
from text_mapper import TranslatableSegment
from translator import OllamaTranslator, GeminiTranslator, get_translator


@pytest.fixture
def sample_segments():
    return [
        TranslatableSegment(
            id="s001",
            inner_html="The morning sun rose slowly.",
            plain_text="The morning sun rose slowly.",
            char_count=28,
            element=None,
        ),
        TranslatableSegment(
            id="s002",
            inner_html='"Hurry up!" she <em>screamed</em>.',
            plain_text='"Hurry up!" she screamed.',
            char_count=29,
            element=None,
        ),
    ]


def test_ollama_system_instruction(tmp_path):
    # Test without glossary
    cfg = Config(source_lang="en", target_lang="id")
    translator = OllamaTranslator(cfg)
    instruction = translator.build_system_instruction()
    assert "English (en) to Indonesian (id)" in instruction
    assert "[segment_id]" in instruction
    assert "<em>" in instruction

    # Test with glossary
    glossary_file = tmp_path / "glossary.json"
    glossary_file.write_text(json.dumps({"Winterfell": "Winterfell"}), encoding="utf-8")
    gl = Glossary.load(glossary_file)
    translator_with_gl = OllamaTranslator(cfg, glossary=gl)
    inst_gl = translator_with_gl.build_system_instruction()
    assert "Winterfell" in inst_gl


def test_ollama_parse_segmented_response():
    cfg = Config()
    translator = OllamaTranslator(cfg)

    raw_output = """Here is the Indonesian translation:
[s001] Matahari pagi terbit perlahan.
Langit mulai membiru.
[s002] "Cepat!" dia <em>berteriak</em>.
"""
    parsed = translator._parse_segmented_response(raw_output)
    assert parsed["s001"] == "Matahari pagi terbit perlahan.\nLangit mulai membiru."
    assert parsed["s002"] == '"Cepat!" dia <em>berteriak</em>.'


def test_ollama_check_connection():
    cfg = Config(ollama_base_url="http://localhost:11434")
    translator = OllamaTranslator(cfg)

    # Success case
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.getcode.return_value = 200
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert translator.check_connection() is True

    # Failure case
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        assert translator.check_connection() is False


def test_ollama_translate_batch_success(sample_segments):
    cfg = Config()
    translator = OllamaTranslator(cfg)

    mock_resp_text = (
        "[s001] Matahari pagi terbit perlahan.\n"
        '[s002] "Cepat!" dia <em>berteriak</em>.'
    )

    with patch.object(translator, "_call_ollama", return_value=mock_resp_text):
        result = translator.translate_batch(sample_segments)

    assert result["s001"] == "Matahari pagi terbit perlahan."
    assert result["s002"] == '"Cepat!" dia <em>berteriak</em>.'


def test_ollama_translate_batch_fallback_for_missing_ids(sample_segments):
    cfg = Config()
    translator = OllamaTranslator(cfg)

    # First call returns only s001 (s002 dropped)
    batch_resp = "[s001] Matahari pagi terbit perlahan."
    single_resp = '[s002] "Cepat!" dia <em>berteriak</em>.'

    def mock_call(prompt, timeout=None):
        if "Translate the following segment directly" in prompt:
            return single_resp
        return batch_resp

    with patch.object(translator, "_call_ollama", side_effect=mock_call):
        result = translator.translate_batch(sample_segments)

    assert "s001" in result
    assert "s002" in result
    assert result["s002"] == '"Cepat!" dia <em>berteriak</em>.'


def test_ollama_connection_error_raises(sample_segments):
    cfg = Config(max_retries=1)
    translator = OllamaTranslator(cfg)

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        with pytest.raises(RuntimeError) as exc_info:
            translator.translate_batch(sample_segments)
        assert "Tidak dapat terhubung ke Ollama" in str(exc_info.value)


def test_ollama_dry_run_stats(sample_segments):
    cfg = Config(model="translategemma:4b")
    translator = OllamaTranslator(cfg)

    stats = translator.calculate_dry_run_stats(sample_segments)
    assert stats["total_segments"] == 2
    assert stats["total_words"] == 9
    assert stats["model"] == "translategemma:4b"
    assert stats["provider"] == "ollama"
    assert "estimated_local_minutes" in stats


def test_get_translator_factory():
    cfg_ollama = Config(provider="ollama")
    t_ollama = get_translator(cfg_ollama)
    assert isinstance(t_ollama, OllamaTranslator)

    cfg_gemini = Config(provider="gemini", api_keys=["key1"])
    t_gemini = get_translator(cfg_gemini)
    assert isinstance(t_gemini, GeminiTranslator)

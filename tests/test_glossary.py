"""Tests for glossary loading, hashing, and prompt formatting."""

import json
from pathlib import Path
import pytest
from glossary import Glossary


def test_glossary_loading_and_hashing(tmp_path: Path):
    glossary_data = {
        "terms": {
            "Wand": "Tongkat sihir",
            "Hogwarts": "Hogwarts"
        },
        "notes": "Pertahankan nada formal."
    }
    file_path = tmp_path / "glossary.json"
    file_path.write_text(json.dumps(glossary_data), encoding="utf-8")

    g = Glossary.load(file_path)
    assert len(g) == 2
    assert g.terms["Wand"] == "Tongkat sihir"
    assert "Hogwarts" in g.terms
    assert len(g.hash) == 16

    prompt_text = g.format_for_prompt()
    assert "Wand => Tongkat sihir" in prompt_text
    assert "Pertahankan nada formal." in prompt_text


def test_glossary_list_format(tmp_path: Path):
    list_data = [
        {"source": "London", "target": "London"},
        {"en": "train", "id": "kereta"}
    ]
    file_path = tmp_path / "glossary_list.json"
    file_path.write_text(json.dumps(list_data), encoding="utf-8")

    g = Glossary.load(file_path)
    assert len(g) == 2
    assert g.terms["London"] == "London"
    assert g.terms["train"] == "kereta"

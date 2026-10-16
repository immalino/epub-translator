"""Tests for configuration, multi-key parsing, masking, and key rotation."""

import time
import pytest
from config import Config, mask_key, parse_api_keys
from translator import KeyManager, KeyRecord


def test_mask_key():
    assert mask_key("") == "<empty>"
    assert mask_key("short") == "***"
    assert mask_key("AIzaSy1234567890Test") == "AIza...Test"


def test_parse_api_keys_combinations(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env_key1")
    monkeypatch.setenv("GEMINI_API_KEYS", "env_key2, env_key3")

    # CLI overrides
    keys = parse_api_keys(cli_keys=["cli_k1", "cli_k2,cli_k3"])
    assert keys == ["cli_k1", "cli_k2", "cli_k3", "env_key2", "env_key3", "env_key1"]


def test_key_manager_round_robin():
    km = KeyManager(["keyA", "keyB", "keyC"], strategy="round_robin")
    assert km.has_keys()

    k1 = km.get_active_key()
    k2 = km.get_active_key()
    k3 = km.get_active_key()
    k4 = km.get_active_key()

    assert [k1, k2, k3, k4] == ["keyA", "keyB", "keyC", "keyA"]


def test_key_manager_fallback_on_rate_limit():
    km = KeyManager(["key1", "key2"], default_cooldown=5.0, strategy="round_robin")

    # Key1 hits rate limit
    km.mark_rate_limited("key1", cooldown_seconds=10.0)

    # Next call should skip key1 and use key2
    active = km.get_active_key()
    assert active == "key2"

    # Status summary should show key1 in cooldown
    summary = km.get_status_summary()
    assert "cooldown" in summary
    assert "ready" in summary

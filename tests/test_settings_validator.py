"""Unit tests for Tab 4 (Settings) and Tab 5 (EPUB Validator)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from config import Config
from gui.main_window import MainWindow
from gui.tab_settings import TabSettings
from gui.tab_validator import TabValidator

# Ensure offscreen platform
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(scope="session")
def qapp():
    """Fixture ensuring a single QApplication instance exists for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_epub_path():
    """Path to sample EPUB fixture."""
    path = Path("tests/fixtures/sample_novel.epub")
    assert path.is_file(), f"Fixture not found at {path}"
    return path


@pytest.fixture
def parent_widget(qapp):
    """Parent container for child tab widgets to ensure clean C++ destruction."""
    parent = QWidget()
    yield parent
    parent.deleteLater()


@pytest.fixture
def tab_settings(parent_widget):
    """TabSettings fixture with parent hierarchy."""
    return TabSettings(parent=parent_widget)


@pytest.fixture
def tab_validator(parent_widget):
    """TabValidator fixture with parent hierarchy."""
    return TabValidator(parent=parent_widget)


# =============================================================================
# TabSettings Tests
# =============================================================================

def test_tab_settings_initialization(tab_settings):
    """Test TabSettings initialization and widget existence."""
    tab = tab_settings
    assert tab.radio_gemini.text().startswith("Google")
    assert tab.radio_ollama.text().startswith("Ollama")
    assert tab.table_keys.columnCount() == 3
    assert tab.combo_gemini_model.count() > 0
    assert tab.combo_rotation.count() > 0
    assert "localhost" in tab.input_ollama_url.text()
    assert tab.input_ollama_model.text() != ""
    assert tab.spin_batch_size.value() > 0
    assert tab.spin_timeout.value() > 0
    assert tab.spin_retries.value() > 0
    assert tab.spin_cooldown.value() > 0.0
    assert tab.btn_save.text() != ""


def test_tab_settings_provider_toggle(tab_settings):
    """Test switching between Gemini and Ollama providers."""
    tab = tab_settings

    # Switch to Ollama
    tab.radio_ollama.setChecked(True)
    assert tab.gemini_group.isEnabled() is False
    assert tab.ollama_group.isEnabled() is True
    assert tab.spin_batch_size.value() == 5

    # Switch back to Gemini
    tab.radio_gemini.setChecked(True)
    assert tab.gemini_group.isEnabled() is True
    assert tab.ollama_group.isEnabled() is False
    assert tab.spin_batch_size.value() == 20


def test_tab_settings_key_management(tab_settings):
    """Test adding, removing, masking, and extracting API keys."""
    tab = tab_settings
    tab.table_keys.setRowCount(0)
    assert len(tab.get_api_keys()) == 0

    # Add 2 keys
    tab.add_key_row("KEY_ALPHA_1234567890", status="Siap")
    tab.add_key_row("KEY_BETA_0987654321", status="Siap")

    assert tab.table_keys.rowCount() == 2
    keys = tab.get_api_keys()
    assert len(keys) == 2
    assert "KEY_ALPHA_1234567890" in keys
    assert "KEY_BETA_0987654321" in keys

    # Toggle masking
    tab._toggle_key_masking()
    # Masking hides full text in item display
    assert "..." in tab.table_keys.item(0, 1).text()
    # get_api_keys still retrieves original key
    assert "KEY_ALPHA_1234567890" in tab.get_api_keys()

    # Toggle unmasking
    tab._toggle_key_masking()
    assert tab.table_keys.item(0, 1).text() == "KEY_ALPHA_1234567890"

    # Remove selected row
    tab.table_keys.selectRow(0)
    tab._on_remove_key_clicked()
    assert tab.table_keys.rowCount() == 1
    assert "KEY_BETA_0987654321" in tab.get_api_keys()


def test_tab_settings_get_and_load_config(tab_settings):
    """Test get_config and load_config roundtrip."""
    tab = tab_settings

    custom_cfg = Config(
        provider="gemini",
        model="gemini-2.5-pro",
        api_keys=["CUSTOM_KEY_1", "CUSTOM_KEY_2"],
        batch_size=25,
        request_timeout=90.0,
        max_retries=7,
        key_cooldown_seconds=45.0,
        rotate_strategy="fallback_on_limit",
        output_dir=Path("custom_output"),
        checkpoint_dir=Path("custom_cache"),
    )

    tab.load_config(custom_cfg)

    # Check UI values
    assert tab.radio_gemini.isChecked()
    assert tab.combo_gemini_model.currentText() == "gemini-2.5-pro"
    assert tab.combo_rotation.currentData() == "fallback_on_limit"
    assert tab.spin_batch_size.value() == 25
    assert tab.spin_timeout.value() == 90
    assert tab.spin_retries.value() == 7
    assert tab.spin_cooldown.value() == 45.0
    assert tab.input_output_dir.text() == "custom_output"
    assert tab.input_cache_dir.text() == "custom_cache"

    # Call get_config and compare
    extracted_cfg = tab.get_config()
    assert extracted_cfg.provider == "gemini"
    assert extracted_cfg.model == "gemini-2.5-pro"
    assert extracted_cfg.batch_size == 25
    assert extracted_cfg.request_timeout == 90.0
    assert extracted_cfg.rotate_strategy == "fallback_on_limit"
    assert "CUSTOM_KEY_1" in extracted_cfg.api_keys


def test_tab_settings_save_settings_to_env(tab_settings, tmp_path):
    """Test saving settings to .env file."""
    tab = tab_settings
    tab.table_keys.setRowCount(0)
    tab.add_key_row("TEST_ENV_KEY_123")
    tab.combo_gemini_model.setEditText("gemini-2.5-flash")
    tab.spin_batch_size.setValue(18)

    env_file = tmp_path / "test.env"
    success = tab.save_settings(env_path=env_file, quiet=True)
    assert success is True
    assert env_file.is_file()

    content = env_file.read_text(encoding="utf-8")
    assert "TRANSLATION_PROVIDER=gemini" in content
    assert "TEST_ENV_KEY_123" in content
    assert "BATCH_SIZE=18" in content


def test_tab_settings_test_key_and_ollama_mocks(qapp):
    """Test testing Gemini key and Ollama connection with mocks."""
    # 1. Test Gemini Key with mock
    with patch("google.genai.Client") as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance

        # Success case
        ok, msg = TabSettings.test_gemini_key("VALID_KEY", "gemini-2.5-flash")
        assert ok is True
        assert msg == "OK"

        # Failure case (invalid key)
        mock_instance.models.get.side_effect = Exception("API_KEY_INVALID: 403 Forbidden")
        ok_fail, msg_fail = TabSettings.test_gemini_key("INVALID_KEY", "gemini-2.5-flash")
        assert ok_fail is False
        assert "Tidak Valid" in msg_fail

    # 2. Test Ollama with mock
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"version": "0.1.32"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        ok_ol, msg_ol = TabSettings.test_ollama("http://localhost:11434")
        assert ok_ol is True
        assert "v0.1.32" in msg_ol


# =============================================================================
# TabValidator Tests
# =============================================================================

def test_tab_validator_initialization(tab_validator):
    """Test TabValidator initialization and elements."""
    tab = tab_validator
    assert tab.input_epub_path is not None
    assert tab.btn_browse is not None
    assert tab.btn_use_latest is not None
    assert tab.btn_validate is not None
    assert tab.card_zip is not None
    assert tab.card_container is not None
    assert tab.card_opf is not None
    assert tab.card_xhtml is not None
    assert tab.card_calibre is not None
    assert tab.log_details is not None


def test_tab_validator_valid_epub(tab_validator, sample_epub_path):
    """Test validating sample novel fixture EPUB."""
    tab = tab_validator
    tab.set_epub_path(sample_epub_path)
    assert tab.input_epub_path.text() == str(sample_epub_path.resolve())

    report = tab.run_validation()
    assert report is not None
    assert report.is_valid is True

    # Visual elements update
    assert "VALID" in tab.banner_title.text()
    assert "✅" in tab.banner_icon.text()

    assert tab.card_zip.lbl_badge.text() == "✅"
    assert tab.card_container.lbl_badge.text() == "✅"
    assert tab.card_opf.lbl_badge.text() == "✅"
    assert tab.card_xhtml.lbl_badge.text() == "✅"

    # Log text contains passed checks
    log_text = tab.log_details.toPlainText()
    assert "VALID" in log_text
    assert "mimetype" in log_text


def test_tab_validator_corrupted_epub(tab_validator, tmp_path):
    """Test validating corrupted EPUB missing container.xml."""
    import zipfile

    corrupted_epub = tmp_path / "corrupted.epub"
    with zipfile.ZipFile(corrupted_epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("random.txt", "just plain text")

    tab = tab_validator
    report = tab.run_validation(epub_path=corrupted_epub)

    assert report is not None
    assert report.is_valid is False
    assert "TIDAK VALID" in tab.banner_title.text()
    assert "❌" in tab.banner_icon.text()
    assert tab.card_container.lbl_badge.text() == "❌"


# =============================================================================
# MainWindow Integration Tests
# =============================================================================

def test_main_window_settings_and_validator_tabs(qapp, sample_epub_path):
    """Test TabSettings and TabValidator presence and wiring in MainWindow."""
    window = MainWindow()

    # Tab 4 and 5 must be instances of TabSettings and TabValidator
    assert isinstance(window.tab_settings, TabSettings)
    assert isinstance(window.tab_validator, TabValidator)

    # Action Settings toolbar button switches tab to Tab 4
    window.action_settings.trigger()
    assert window.tab_widget.currentWidget() is window.tab_settings

    # Saving config in TabSettings updates status bar
    test_cfg = window.tab_settings.get_config()
    test_cfg.model = "gemini-2.5-pro"
    window.tab_settings.sig_config_saved.emit(test_cfg)
    assert "gemini-2.5-pro" in window.status_engine_label.text()

    # Translation completion flow prompts for validation
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        with patch.object(window.tab_validator, "run_validation") as mock_validate:
            window._on_translation_completed(
                output_path=str(sample_epub_path),
                elapsed=5.2,
                report=None,
            )
            assert window.tab_widget.currentWidget() is window.tab_validator
            mock_validate.assert_called_once()


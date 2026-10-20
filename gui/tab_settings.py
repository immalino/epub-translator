"""Tab 4: Engine Settings and API Key Configuration Widget.

Provides:
- Gemini API configuration:
  - Dynamic multi-key manager (add, remove, mask/unmask, test keys)
  - Gemini model selection dropdown with custom model support
  - Key rotation strategy selector (round_robin / fallback_on_limit)
- Local Ollama server configuration:
  - Base URL endpoint input and server ping test
  - Ollama model name input
- Advanced runtime parameters:
  - Batch size, request timeout, max retries, key cooldown
  - Default input, output, and checkpoint cache directory selectors
- Persistent synchronization to/from .env file
"""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import Config, mask_key
from translator import OllamaTranslator

logger = logging.getLogger("epub_translate.gui.tab_settings")


class TabSettings(QWidget):
    """Calibre-inspired Settings tab for LLM engine, API keys, and runtime tuning."""

    sig_config_saved = Signal(object)  # Emits Config object on save

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._keys_masked: bool = False
        self._setup_ui()
        self.load_config(Config.load())
        logger.info("TabSettings initialized successfully.")

    def _setup_ui(self) -> None:
        """Construct the settings interface."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("tabSettingsScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        content_widget = QWidget()
        content_widget.setObjectName("tabSettingsContent")
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(14)
        layout.setContentsMargins(14, 14, 14, 14)

        # ---------------------------------------------------------------------
        # 1. Provider Selection
        # ---------------------------------------------------------------------
        provider_group = QGroupBox("Mesin Terjemahan Aktif (Translation Provider)")
        p_layout = QHBoxLayout(provider_group)
        p_layout.setSpacing(20)

        self.radio_gemini = QRadioButton("Google Gemini API (Cloud / Rekomendasi)")
        self.radio_gemini.setChecked(True)
        self.radio_gemini.toggled.connect(self._on_provider_changed)
        p_layout.addWidget(self.radio_gemini)

        self.radio_ollama = QRadioButton("Ollama Local LLM (Privat / Tanpa Kuota)")
        self.radio_ollama.toggled.connect(self._on_provider_changed)
        p_layout.addWidget(self.radio_ollama)

        p_layout.addStretch()
        layout.addWidget(provider_group)

        # ---------------------------------------------------------------------
        # 2. Gemini Settings Panel
        # ---------------------------------------------------------------------
        self.gemini_group = QGroupBox("Konfigurasi Google Gemini API")
        g_layout = QVBoxLayout(self.gemini_group)
        g_layout.setSpacing(10)

        # Keys Action Bar
        keys_bar = QHBoxLayout()
        keys_bar.addWidget(QLabel("<b>Daftar API Keys (Multi-Key Support):</b>"))
        keys_bar.addStretch()

        self.btn_add_key = QPushButton("➕ Tambah Kunci")
        self.btn_add_key.clicked.connect(self._on_add_key_clicked)
        keys_bar.addWidget(self.btn_add_key)

        self.btn_paste_keys = QPushButton("📋 Tempel dari Clipboard")
        self.btn_paste_keys.setToolTip("Tempel satu atau banyak API Key dari clipboard (otomatis dipisah)")
        self.btn_paste_keys.clicked.connect(self.paste_keys_from_clipboard)
        keys_bar.addWidget(self.btn_paste_keys)

        self.btn_remove_key = QPushButton("➖ Hapus Terpilih")
        self.btn_remove_key.clicked.connect(self._on_remove_key_clicked)
        keys_bar.addWidget(self.btn_remove_key)

        self.btn_toggle_mask = QPushButton("👁️ Sensor")
        self.btn_toggle_mask.clicked.connect(self._toggle_key_masking)
        keys_bar.addWidget(self.btn_toggle_mask)

        self.btn_test_keys = QPushButton("🔍 Uji Kunci API")
        self.btn_test_keys.setStyleSheet("font-weight: 600; color: #0284c7;")
        self.btn_test_keys.setToolTip("Periksa validitas kunci ke server Google GenAI")
        self.btn_test_keys.clicked.connect(self.test_all_gemini_keys)
        keys_bar.addWidget(self.btn_test_keys)

        g_layout.addLayout(keys_bar)

        # API Keys Table
        self.table_keys = QTableWidget(0, 3)
        self.table_keys.setHorizontalHeaderLabels(["#", "API Key", "Status Validasi"])
        self.table_keys.setAlternatingRowColors(True)
        self.table_keys.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_keys.verticalHeader().setVisible(False)
        self.table_keys.setMinimumHeight(130)

        k_header = self.table_keys.horizontalHeader()
        k_header.setSectionResizeMode(0, QHeaderView.Fixed)
        k_header.setSectionResizeMode(1, QHeaderView.Stretch)
        k_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_keys.setColumnWidth(0, 45)

        g_layout.addWidget(self.table_keys)

        # Model & Rotation settings
        params_row = QHBoxLayout()
        params_row.setSpacing(16)

        # Model Dropdown
        m_col = QVBoxLayout()
        m_col.addWidget(QLabel("Model Gemini:"))
        self.combo_gemini_model = QComboBox()
        self.combo_gemini_model.setEditable(True)
        self.combo_gemini_model.addItems([
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-1.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
        ])
        m_col.addWidget(self.combo_gemini_model)
        params_row.addLayout(m_col, stretch=1)

        # Rotation Strategy
        rot_col = QVBoxLayout()
        rot_col.addWidget(QLabel("Strategi Rotasi Kunci:"))
        self.combo_rotation = QComboBox()
        self.combo_rotation.addItem("Round-Robin (Bergantian Tiap Batch)", "round_robin")
        self.combo_rotation.addItem("Fallback On Limit (Pindah Hanya Saat Limit)", "fallback_on_limit")
        rot_col.addWidget(self.combo_rotation)
        params_row.addLayout(rot_col, stretch=1)

        g_layout.addLayout(params_row)
        layout.addWidget(self.gemini_group)

        # ---------------------------------------------------------------------
        # 3. Ollama Settings Panel
        # ---------------------------------------------------------------------
        self.ollama_group = QGroupBox("Konfigurasi Ollama Local LLM")
        o_layout = QVBoxLayout(self.ollama_group)
        o_layout.setSpacing(10)

        o_row1 = QHBoxLayout()
        o_row1.setSpacing(12)

        # Base URL
        url_col = QVBoxLayout()
        url_col.addWidget(QLabel("Ollama Server URL:"))
        self.input_ollama_url = QLineEdit("http://localhost:11434")
        url_col.addWidget(self.input_ollama_url)
        o_row1.addLayout(url_col, stretch=2)

        # Check Ollama Button
        btn_col = QVBoxLayout()
        btn_col.addWidget(QLabel("Tes Koneksi:"))
        self.btn_check_ollama = QPushButton("🔌 Cek Status Ollama")
        self.btn_check_ollama.clicked.connect(self.test_ollama_connection)
        btn_col.addWidget(self.btn_check_ollama)
        o_row1.addLayout(btn_col, stretch=1)

        # Ollama Model
        model_col = QVBoxLayout()
        model_col.addWidget(QLabel("Nama Model Ollama:"))
        self.input_ollama_model = QLineEdit("translategemma:4b")
        model_col.addWidget(self.input_ollama_model)
        o_row1.addLayout(model_col, stretch=2)

        o_layout.addLayout(o_row1)

        self.lbl_ollama_status = QLabel("Status server belum diuji.")
        self.lbl_ollama_status.setStyleSheet("color: #64748b; font-size: 12px;")
        o_layout.addWidget(self.lbl_ollama_status)

        layout.addWidget(self.ollama_group)

        # ---------------------------------------------------------------------
        # 4. Advanced Tuning Parameters
        # ---------------------------------------------------------------------
        adv_group = QGroupBox("Parameter Lanjutan & Folder Kerja")
        adv_layout = QVBoxLayout(adv_group)
        adv_layout.setSpacing(10)

        spin_row = QHBoxLayout()
        spin_row.setSpacing(16)

        # Batch Size
        b_col = QVBoxLayout()
        b_col.addWidget(QLabel("Ukuran Batch (Segmen/Panggilan):"))
        self.spin_batch_size = QSpinBox()
        self.spin_batch_size.setRange(1, 100)
        self.spin_batch_size.setValue(20)
        b_col.addWidget(self.spin_batch_size)
        spin_row.addLayout(b_col)

        # Timeout
        t_col = QVBoxLayout()
        t_col.addWidget(QLabel("Timeout Request (Detik):"))
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(5, 600)
        self.spin_timeout.setValue(60)
        t_col.addWidget(self.spin_timeout)
        spin_row.addLayout(t_col)

        # Max Retries
        r_col = QVBoxLayout()
        r_col.addWidget(QLabel("Maksimum Percobaan Ulang:"))
        self.spin_retries = QSpinBox()
        self.spin_retries.setRange(1, 20)
        self.spin_retries.setValue(5)
        r_col.addWidget(self.spin_retries)
        spin_row.addLayout(r_col)

        # Key Cooldown
        c_col = QVBoxLayout()
        c_col.addWidget(QLabel("Cooldown Kunci Limit (Detik):"))
        self.spin_cooldown = QDoubleSpinBox()
        self.spin_cooldown.setRange(1.0, 300.0)
        self.spin_cooldown.setValue(60.0)
        c_col.addWidget(self.spin_cooldown)
        spin_row.addLayout(c_col)

        adv_layout.addLayout(spin_row)

        # Folder Paths
        paths_row = QHBoxLayout()
        paths_row.setSpacing(16)

        # Output folder
        out_col = QVBoxLayout()
        out_col.addWidget(QLabel("Folder Output Default:"))
        out_h = QHBoxLayout()
        self.input_output_dir = QLineEdit("output")
        out_h.addWidget(self.input_output_dir)
        btn_browse_out = QPushButton("Pilih...")
        btn_browse_out.clicked.connect(lambda: self._browse_dir(self.input_output_dir))
        out_h.addWidget(btn_browse_out)
        out_col.addLayout(out_h)
        paths_row.addLayout(out_col)

        # Checkpoint cache folder
        chk_col = QVBoxLayout()
        chk_col.addWidget(QLabel("Folder Cache Checkpoint:"))
        chk_h = QHBoxLayout()
        self.input_cache_dir = QLineEdit(".epub_translate_cache")
        chk_h.addWidget(self.input_cache_dir)
        btn_browse_chk = QPushButton("Pilih...")
        btn_browse_chk.clicked.connect(lambda: self._browse_dir(self.input_cache_dir))
        chk_h.addWidget(btn_browse_chk)
        chk_col.addLayout(chk_h)
        paths_row.addLayout(chk_col)

        adv_layout.addLayout(paths_row)
        layout.addWidget(adv_group)

        # ---------------------------------------------------------------------
        # 5. Bottom Action Buttons
        # ---------------------------------------------------------------------
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()

        self.btn_reload = QPushButton("Muat Ulang Pengaturan")
        self.btn_reload.clicked.connect(lambda: self.load_config(Config.load()))
        bottom_bar.addWidget(self.btn_reload)

        self.btn_save = QPushButton("💾 Simpan Pengaturan")
        self.btn_save.setStyleSheet(
            "QPushButton { background-color: #0284c7; color: white; font-weight: bold; "
            "padding: 8px 20px; border-radius: 6px; font-size: 13px; } "
            "QPushButton:hover { background-color: #0369a1; }"
        )
        self.btn_save.clicked.connect(self.save_settings)
        bottom_bar.addWidget(self.btn_save)

        layout.addLayout(bottom_bar)

        self.scroll_area.setWidget(content_widget)
        outer_layout.addWidget(self.scroll_area)

    # =========================================================================
    # Provider Toggling
    # =========================================================================

    def _on_provider_changed(self) -> None:
        """Visual cues based on selected provider."""
        is_gemini = self.radio_gemini.isChecked()
        self.gemini_group.setEnabled(is_gemini)
        self.ollama_group.setEnabled(not is_gemini)
        if is_gemini and self.spin_batch_size.value() == 5:
            self.spin_batch_size.setValue(20)
        elif not is_gemini and self.spin_batch_size.value() == 20:
            self.spin_batch_size.setValue(5)

    def _browse_dir(self, line_edit: QLineEdit) -> None:
        """Helper to browse directory and set text in line edit."""
        folder = QFileDialog.getExistingDirectory(self, "Pilih Folder", line_edit.text())
        if folder:
            line_edit.setText(folder)

    # =========================================================================
    # API Keys Management
    # =========================================================================

    def _on_add_key_clicked(self) -> None:
        """Add empty key row."""
        self.add_key_row("", status="Belum diuji")

    def add_key_row(self, key_text: str, status: str = "Siap") -> int:
        """Insert a key row into the keys table."""
        row = self.table_keys.rowCount()
        self.table_keys.insertRow(row)

        # Col 0: Index
        item_idx = QTableWidgetItem(str(row + 1))
        item_idx.setTextAlignment(Qt.AlignCenter)
        item_idx.setForeground(QColor("#475569"))
        item_idx.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table_keys.setItem(row, 0, item_idx)

        # Col 1: API Key input item
        item_key = QTableWidgetItem(key_text.strip())
        item_key.setData(Qt.UserRole, key_text.strip())
        item_key.setForeground(QColor("#0f172a"))
        item_key.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
        self.table_keys.setItem(row, 1, item_key)

        # Col 2: Status item
        item_st = QTableWidgetItem(status)
        item_st.setTextAlignment(Qt.AlignCenter)
        if any(w in status.lower() for w in ["aktif", "siap", "tersimpan", "ok"]):
            item_st.setForeground(QColor("#0284c7"))
        elif any(w in status.lower() for w in ["gagal", "tidak valid", "limit", "error"]):
            item_st.setForeground(QColor("#dc2626"))
        else:
            item_st.setForeground(QColor("#64748b"))
        item_st.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table_keys.setItem(row, 2, item_st)

        return row

    def _on_remove_key_clicked(self) -> None:
        """Remove selected key rows."""
        selected = sorted(
            list(set(idx.row() for idx in self.table_keys.selectedIndexes())),
            reverse=True,
        )
        for r in selected:
            self.table_keys.removeRow(r)

        # Re-number indices
        for r in range(self.table_keys.rowCount()):
            item = self.table_keys.item(r, 0)
            if item:
                item.setText(str(r + 1))

    def paste_keys_from_clipboard(self) -> int:
        """Paste API keys directly from system clipboard, splitting on newlines/commas/spaces."""
        clipboard = QApplication.clipboard()
        text = clipboard.text() if clipboard else ""
        if not text.strip():
            QMessageBox.information(self, "Clipboard Kosong", "Tidak ada teks API Key di clipboard.")
            return 0

        # Split on newline, comma, semicolon, space, or quotes
        import re
        tokens = [k.strip().strip("'\"`") for k in re.split(r"[\r\n,;\s]+", text) if k.strip()]
        existing = set(self.get_api_keys())
        added_count = 0

        for token in tokens:
            if token and token not in existing:
                self.add_key_row(token, status="Siap")
                existing.add(token)
                added_count += 1

        if added_count > 0:
            QMessageBox.information(
                self,
                "Kunci Ditambahkan",
                f"Berhasil menambahkan {added_count} API Key dari clipboard."
            )
        else:
            QMessageBox.information(
                self,
                "Informasi",
                "Semua API Key dari clipboard sudah ada di dalam tabel."
            )
        return added_count

    def _toggle_key_masking(self) -> None:
        """Toggle displaying full key or masked key summary in table."""
        self._keys_masked = not self._keys_masked
        for r in range(self.table_keys.rowCount()):
            item = self.table_keys.item(r, 1)
            if not item:
                continue
            orig = item.data(Qt.UserRole)
            if orig is None:
                orig = item.text().strip()
                item.setData(Qt.UserRole, orig)

            if self._keys_masked:
                item.setText(mask_key(orig) if orig else "")
            else:
                item.setText(orig)
            item.setForeground(QColor("#0f172a"))

    def get_api_keys(self) -> List[str]:
        """Extract clean list of API keys from the table."""
        keys = []
        for r in range(self.table_keys.rowCount()):
            item = self.table_keys.item(r, 1)
            if not item:
                continue
            orig = item.data(Qt.UserRole)
            if orig is not None and self._keys_masked:
                text = str(orig).strip()
            else:
                text = item.text().strip()
                if not self._keys_masked and text:
                    item.setData(Qt.UserRole, text)
            if text and text not in keys:
                keys.append(text)
        return keys

    # =========================================================================
    # Connection Tests
    # =========================================================================

    def test_all_gemini_keys(self) -> None:
        """Validate each configured Gemini key against Google GenAI SDK."""
        keys = self.get_api_keys()
        if not keys:
            QMessageBox.information(
                self, "Tidak Ada Kunci", "Silakan masukkan minimal satu API Key sebelum melakukan pengujian."
            )
            return

        model_name = self.combo_gemini_model.currentText().strip() or "gemini-2.5-flash"
        valid_count = 0

        for r in range(self.table_keys.rowCount()):
            item_key = self.table_keys.item(r, 1)
            item_st = self.table_keys.item(r, 2)
            if not item_key or not item_st:
                continue

            orig = item_key.data(Qt.UserRole)
            k = (orig if (self._keys_masked and orig) else item_key.text()).strip()
            if not k:
                item_st.setText("Kosong")
                continue

            item_st.setText("Menguji...")
            item_st.setForeground(QColor("#d97706"))
            ok, msg = self.test_gemini_key(k, model_name)
            if ok:
                item_st.setText("🟢 Aktif")
                item_st.setForeground(QColor("#16a34a"))
                valid_count += 1
            else:
                item_st.setText(f"🔴 {msg}")
                item_st.setForeground(QColor("#dc2626"))

        QMessageBox.information(
            self,
            "Hasil Uji Kunci API",
            f"Uji coba selesai.\n{valid_count} dari {len(keys)} kunci aktif dan siap digunakan.",
        )

    @staticmethod
    def test_gemini_key(key: str, model: str = "gemini-2.5-flash") -> Tuple[bool, str]:
        """Test a single Gemini API key."""
        clean_key = key.strip()
        if not clean_key:
            return False, "Kunci kosong"

        try:
            from google import genai

            client = genai.Client(api_key=clean_key)
            # Lightweight check: get model info
            client.models.get(model=model)
            return True, "OK"
        except Exception as exc:
            err_msg = str(exc)
            if "API_KEY_INVALID" in err_msg or "403" in err_msg or "INVALID_ARGUMENT" in err_msg:
                return False, "Kunci Tidak Valid"
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                return False, "Kuota Limit (429)"
            return False, err_msg[:30]

    def test_ollama_connection(self) -> None:
        """Test connectivity to local Ollama server."""
        url = self.input_ollama_url.text().strip() or "http://localhost:11434"
        self.lbl_ollama_status.setText("Menghubungi server Ollama...")

        ok, msg = self.test_ollama(url)
        if ok:
            self.lbl_ollama_status.setText(f"🟢 Terhubung: {msg}")
            self.lbl_ollama_status.setStyleSheet("color: #16a34a; font-weight: 500;")
        else:
            self.lbl_ollama_status.setText(f"🔴 Gagal: {msg}")
            self.lbl_ollama_status.setStyleSheet("color: #dc2626; font-weight: 500;")

    @staticmethod
    def test_ollama(url: str) -> Tuple[bool, str]:
        """Ping Ollama server endpoint."""
        clean_url = url.rstrip("/")
        try:
            req = urllib.request.Request(f"{clean_url}/api/version", method="GET")
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                import json

                data = json.loads(resp.read().decode("utf-8"))
                version = data.get("version", "Aktif")
                return True, f"Ollama v{version}"
        except Exception as e:
            return False, str(e)

    # =========================================================================
    # Config Loading & Saving
    # =========================================================================

    def load_config(self, config: Config) -> None:
        """Populate settings widgets from a Config instance."""
        # Provider
        if config.provider == "ollama":
            self.radio_ollama.setChecked(True)
        else:
            self.radio_gemini.setChecked(True)

        # Gemini Keys
        self.table_keys.setRowCount(0)
        for k in config.api_keys:
            self.add_key_row(k, status="Tersimpan")

        # Gemini Model
        idx = self.combo_gemini_model.findText(config.model)
        if idx >= 0:
            self.combo_gemini_model.setCurrentIndex(idx)
        else:
            self.combo_gemini_model.setEditText(config.model)

        # Rotation Strategy
        idx_rot = self.combo_rotation.findData(config.rotate_strategy)
        if idx_rot >= 0:
            self.combo_rotation.setCurrentIndex(idx_rot)

        # Ollama
        self.input_ollama_url.setText(config.ollama_base_url or "http://localhost:11434")
        if config.provider == "ollama":
            self.input_ollama_model.setText(config.model)

        # Advanced
        self.spin_batch_size.setValue(config.batch_size or 20)
        self.spin_timeout.setValue(int(config.request_timeout or 60))
        self.spin_retries.setValue(config.max_retries or 5)
        self.spin_cooldown.setValue(config.key_cooldown_seconds or 60.0)

        self.input_output_dir.setText(str(config.output_dir))
        self.input_cache_dir.setText(str(config.checkpoint_dir))

        self._on_provider_changed()

    def get_config(self) -> Config:
        """Assemble and return Config object from current GUI inputs."""
        provider = "ollama" if self.radio_ollama.isChecked() else "gemini"
        keys = self.get_api_keys()

        if provider == "gemini":
            model = self.combo_gemini_model.currentText().strip() or "gemini-2.5-flash"
        else:
            model = self.input_ollama_model.text().strip() or "translategemma:4b"

        rot_strategy = self.combo_rotation.currentData() or "round_robin"

        cfg = Config(
            provider=provider,
            model=model,
            api_keys=keys,
            ollama_base_url=self.input_ollama_url.text().strip() or "http://localhost:11434",
            batch_size=self.spin_batch_size.value(),
            request_timeout=float(self.spin_timeout.value()),
            max_retries=self.spin_retries.value(),
            key_cooldown_seconds=self.spin_cooldown.value(),
            rotate_strategy=rot_strategy,
            output_dir=Path(self.input_output_dir.text().strip() or "output"),
            checkpoint_dir=Path(self.input_cache_dir.text().strip() or ".epub_translate_cache"),
        )
        return cfg

    def save_settings(self, env_path: Path = Path(".env"), quiet: bool = False) -> bool:
        """Persist current settings directly to config.json, environment variables, and .env fallback."""
        cfg = self.get_config()

        # 1. Direct persistence to config.json
        json_path = env_path.parent / "config.json" if env_path.parent.is_dir() and env_path.name != ".env" else Path("config.json")
        try:
            cfg.save(json_path)
        except Exception as exc:
            logger.warning("Gagal menyimpan config.json: %s", exc)

        # 2. Update environment variables
        os.environ["TRANSLATION_PROVIDER"] = cfg.provider
        if cfg.provider == "gemini":
            os.environ["GEMINI_MODEL"] = cfg.model
            os.environ["GEMINI_API_KEYS"] = " ".join(cfg.api_keys)
            os.environ["GEMINI_API_KEY"] = " ".join(cfg.api_keys)
        else:
            os.environ["OLLAMA_MODEL"] = cfg.model

        os.environ["ROTATION_STRATEGY"] = cfg.rotate_strategy
        os.environ["OLLAMA_BASE_URL"] = cfg.ollama_base_url
        os.environ["BATCH_SIZE"] = str(cfg.batch_size)
        os.environ["REQUEST_TIMEOUT"] = str(cfg.request_timeout)
        os.environ["MAX_RETRIES"] = str(cfg.max_retries)
        os.environ["OUTPUT_DIR"] = str(cfg.output_dir)

        # 3. Write formatted .env for backward compatibility
        env_content = [
            "# =======================================================",
            "# EPUB TRANSLATOR CONFIGURATION (.env)",
            "# (Dihasilkan secara otomatis dari GUI Pengaturan)",
            "# =======================================================",
            "",
            f"TRANSLATION_PROVIDER={cfg.provider}",
            f"INPUT_DIR={cfg.input_dir}",
            f"OUTPUT_DIR={cfg.output_dir}",
            "",
            "# Parameter Inferensi / Batching",
            f"BATCH_SIZE={cfg.batch_size}",
            f"REQUEST_TIMEOUT={cfg.request_timeout}",
            f"MAX_RETRIES={cfg.max_retries}",
            "",
            "# Konfigurasi Google Gemini API",
            f"GEMINI_API_KEY={' '.join(cfg.api_keys)}",
            f"GEMINI_MODEL={self.combo_gemini_model.currentText().strip() or 'gemini-2.5-flash'}",
            f"ROTATION_STRATEGY={cfg.rotate_strategy}",
            "",
            "# Konfigurasi Model Lokal Ollama",
            f"OLLAMA_BASE_URL={cfg.ollama_base_url}",
            f"OLLAMA_MODEL={self.input_ollama_model.text().strip() or 'translategemma:4b'}",
            "",
        ]

        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("\n".join(env_content))

            logger.info("Configuration successfully written to %s and %s", env_path, json_path)
            self.sig_config_saved.emit(cfg)

            if not quiet:
                QMessageBox.information(
                    self,
                    "Pengaturan Berhasil Disimpan",
                    "Pengaturan berhasil disimpan dan langsung diterapkan!\n"
                    "Anda tidak perlu lagi mengedit file .env secara manual.",
                )
            return True
        except Exception as exc:
            logger.exception("Gagal menyimpan konfigurasi: %s", exc)
            if not quiet:
                QMessageBox.critical(self, "Gagal Menyimpan", f"Gagal menyimpan konfigurasi:\n{exc}")
            return False

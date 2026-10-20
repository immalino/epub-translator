# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for EPUB Translator Desktop Application (Calibre Edition)."""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Base directory
BASE_DIR = Path.cwd()

# Hidden imports for third-party libraries and dynamic modules
hidden_imports = [
    # Google GenAI SDK
    "google.genai",
    "google.genai.types",
    "google.genai.errors",
    "google.genai._api_client",
    # XML and EPUB Parsing
    "lxml",
    "lxml.etree",
    "lxml._elementpath",
    # Data Validation & Typing
    "pydantic",
    "pydantic.deprecated",
    "certifi",
    "charset_normalizer",
    # PySide6 GUI Components
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
    # Environment & Utilities
    "dotenv",
    "urllib3",
]

# Collect any additional package data if necessary
datas = []

# Exclude unnecessary heavyweight modules to keep executable compact
excludes = [
    "tkinter",
    "matplotlib",
    "scipy",
    "numpy",
    "IPython",
    "notebook",
    "pytest",
    "unittest",
]

# Check for application icon
icon_path = str(BASE_DIR / "app_icon.ico") if (BASE_DIR / "app_icon.ico").exists() else None

a = Analysis(
    ["desktop_app.py"],
    pathex=[str(BASE_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EPUBTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Windowed GUI application (no CMD black window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EPUBTranslator",
)

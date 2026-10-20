"""Calibre-inspired Icon and Asset Management for EPUB Translator GUI.

Provides QIcon generators using clean, scalable SVGs rendered via QSvgRenderer
or QPainter, ensuring crisp display across different display scalings.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

logger = logging.getLogger("epub_translate.gui.assets")

# SVG Templates (24x24 viewBox, modern stroke-based / filled design)
SVG_ICONS: Dict[str, str] = {
    # Open EPUB / Library Book
    "open_epub": """
    <svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
        <line x1="9" y1="7" x2="15" y2="7"/>
        <line x1="9" y1="11" x2="13" y2="11"/>
    </svg>
    """,
    # Start / Play
    "start": """
    <svg viewBox="0 0 24 24" fill="{color}" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="5 3 19 12 5 21 5 3"/>
    </svg>
    """,
    # Pause
    "pause": """
    <svg viewBox="0 0 24 24" fill="{color}" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <rect x="6" y="4" width="4" height="16" rx="1"/>
        <rect x="14" y="4" width="4" height="16" rx="1"/>
    </svg>
    """,
    # Stop
    "stop": """
    <svg viewBox="0 0 24 24" fill="{color}" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <rect x="4" y="4" width="16" height="16" rx="2"/>
    </svg>
    """,
    # Dry Run / Estimate / Calculator & Inspect
    "dry_run": """
    <svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"/>
        <line x1="21" y1="21" x2="16.65" y2="16.65"/>
        <line x1="11" y1="8" x2="11" y2="14"/>
        <line x1="8" y1="11" x2="14" y2="11"/>
    </svg>
    """,
    # Glossary / Vocabulary Dictionary
    "glossary": """
    <svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
        <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
        <line x1="6" y1="8" x2="8" y2="8"/>
        <line x1="16" y1="8" x2="18" y2="8"/>
        <line x1="6" y1="12" x2="8" y2="12"/>
    </svg>
    """,
    # Bilingual Editor (Side-by-side pages)
    "editor": """
    <svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2"/>
        <line x1="12" y1="3" x2="12" y2="21"/>
        <line x1="7" y1="8" x2="8" y2="8"/>
        <line x1="16" y1="8" x2="17" y2="8"/>
        <line x1="6" y1="13" x2="9" y2="13"/>
        <line x1="15" y1="13" x2="18" y2="13"/>
    </svg>
    """,
    # Settings / Preferences (Gear)
    "settings": """
    <svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>
    """,
    # Validate / EPUB Compliance Check
    "validate": """
    <svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        <polyline points="9 12 11 14 15 10"/>
    </svg>
    """,
    # Output Folder
    "folder_output": """
    <svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
        <polyline points="12 11 15 14 12 17"/>
        <line x1="9" y1="14" x2="15" y2="14"/>
    </svg>
    """,
}

# Calibre Color Palette
DEFAULT_ICON_COLORS: Dict[str, str] = {
    "open_epub": "#2b5797",     # Calibre Library Blue
    "start": "#107c41",         # Calibre Play Green
    "pause": "#d83b01",         # Orange/Amber
    "stop": "#d13438",          # Calibre Red
    "dry_run": "#008272",       # Calibre Teal / Estimate
    "glossary": "#4f46e5",      # Indigo
    "editor": "#7c3aed",        # Purple
    "settings": "#5c5c5c",      # Slate Grey
    "validate": "#0e7a0d",      # Deep Green
    "folder_output": "#b45309", # Warm Folder Amber
}


def create_svg_icon(svg_xml: str, sizes: tuple[int, ...] = (16, 24, 32, 48, 64)) -> QIcon:
    """Render an SVG XML string into a multi-resolution QIcon."""
    icon = QIcon()
    byte_array = QByteArray(svg_xml.strip().encode("utf-8"))
    renderer = QSvgRenderer(byte_array)

    if not renderer.isValid():
        logger.warning("Failed to parse SVG for icon creation.")
        return icon

    for sz in sizes:
        pixmap = QPixmap(sz, sz)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        renderer.render(painter, QRectF(0, 0, sz, sz))
        painter.end()

        icon.addPixmap(pixmap)

    return icon


def get_icon(name: str, color: Optional[str] = None) -> QIcon:
    """Retrieve or generate a QIcon by action name with optional custom color."""
    template = SVG_ICONS.get(name)
    if not template:
        # Fallback empty icon
        logger.warning("Icon '%s' not found in assets, returning blank icon.", name)
        return QIcon()

    chosen_color = color or DEFAULT_ICON_COLORS.get(name, "#333333")
    svg_str = template.format(color=chosen_color)
    return create_svg_icon(svg_str)


# Explicit icon getters for clear autocompletion and safety
def get_open_epub_icon() -> QIcon:
    """Icon for Open EPUB action."""
    return get_icon("open_epub")


def get_start_icon() -> QIcon:
    """Icon for Start Translation action."""
    return get_icon("start")


def get_pause_icon() -> QIcon:
    """Icon for Pause / Resume action."""
    return get_icon("pause")


def get_stop_icon() -> QIcon:
    """Icon for Stop / Cancel action."""
    return get_icon("stop")


def get_dry_run_icon() -> QIcon:
    """Icon for Dry Run / Cost & Quota Estimation action."""
    return get_icon("dry_run")


def get_glossary_icon() -> QIcon:
    """Icon for Glossary Manager tab."""
    return get_icon("glossary")


def get_editor_icon() -> QIcon:
    """Icon for Bilingual Editor tab."""
    return get_icon("editor")


def get_settings_icon() -> QIcon:
    """Icon for Machine & API Settings tab."""
    return get_icon("settings")


def get_validate_icon() -> QIcon:
    """Icon for EPUB Validation tab."""
    return get_icon("validate")


def get_output_folder_icon() -> QIcon:
    """Icon for Open Output Folder action."""
    return get_icon("folder_output")


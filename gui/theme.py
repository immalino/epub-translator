"""Calibre-inspired Modern Stylesheet and Typography Configuration.

Provides a clean, functional desktop styling inspired by modern Calibre e-book manager:
- High-contrast, clean QTabWidget tabs
- Polished, neatly striped QTableWidget
- Smooth, high-contrast modern progress bars
- Subtle, clean QStatusBar with status badges
- Native OS font selection (Segoe UI, Ubuntu, Inter, DejaVu Sans)
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

logger = logging.getLogger("epub_translate.gui.theme")

# Calibre Modern QSS Stylesheet
CALIBRE_QSS = """
/* ==========================================================================
   Base Window & Surfaces
   ========================================================================== */
QMainWindow, QDialog {
    background-color: #f8fafc;
    color: #0f172a;
}

/* Default label & text colors */
QLabel {
    color: #1e293b;
    background-color: transparent;
}

/* ==========================================================================
   Calibre Top Action Toolbar
   ========================================================================== */
QToolBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e2e8f0;
    padding: 6px 10px;
    spacing: 8px;
}

QToolBar::separator {
    width: 1px;
    background-color: #e2e8f0;
    margin: 4px 6px;
}

QToolButton {
    background-color: transparent;
    color: #334155;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 500;
    font-size: 11px;
    min-width: 64px;
}

QToolButton:hover {
    background-color: #f1f5f9;
    color: #0284c7;
    border: 1px solid #cbd5e1;
}

QToolButton:pressed {
    background-color: #e2e8f0;
    border: 1px solid #94a3b8;
}

QToolButton:disabled {
    color: #cbd5e1;
}

/* ==========================================================================
   QTabWidget (Modern Calibre Navigation Tabs)
   ========================================================================== */
QTabWidget::pane {
    border: 1px solid #e2e8f0;
    background-color: #ffffff;
    top: -1px;
    border-radius: 6px;
}

QTabBar::tab {
    background: #f1f5f9;
    color: #64748b;
    border: 1px solid #e2e8f0;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 9px 20px;
    margin-right: 4px;
    font-weight: 600;
    font-size: 12px;
}

QTabBar::tab:hover {
    background: #ffffff;
    color: #0f172a;
}

QTabBar::tab:selected {
    background: #ffffff;
    color: #0284c7;
    border-top: 3px solid #0284c7;
    border-bottom: 1px solid #ffffff;
}

/* ==========================================================================
   QTableWidget & QTableView (Clean borders & alternating rows)
   ========================================================================== */
QTableWidget, QTableView {
    background-color: #ffffff;
    alternate-background-color: #fcfdfd;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    gridline-color: #f1f5f9;
    selection-background-color: #e0f2fe;
    selection-color: #0369a1;
}

QTableWidget::item {
    padding: 4px 6px;
    border: none;
}

QTableWidget::item:focus {
    background-color: #e0f2fe;
    color: #0369a1;
}

QHeaderView::section {
    background-color: #f8fafc;
    color: #475569;
    padding: 7px 10px;
    border: none;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
    font-weight: 600;
    font-size: 12px;
}

QHeaderView::section:hover {
    background-color: #f1f5f9;
    color: #0f172a;
}

/* ==========================================================================
   QProgressBar (Modern, high contrast gradient)
   ========================================================================== */
QProgressBar {
    background-color: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    text-align: center;
    color: #0f172a;
    font-weight: 600;
    font-size: 11px;
    min-height: 18px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #38bdf8);
    border-radius: 5px;
}

QProgressBar#chapterProgress::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #34d399);
    border-radius: 5px;
}

/* ==========================================================================
   Buttons (Standard UI Buttons)
   ========================================================================== */
QPushButton {
    background-color: #ffffff;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
    font-size: 12px;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #f8fafc;
    border-color: #94a3b8;
    color: #0f172a;
}

QPushButton:pressed {
    background-color: #f1f5f9;
    border-color: #64748b;
}

QPushButton:disabled {
    background-color: #f8fafc;
    color: #cbd5e1;
    border-color: #e2e8f0;
}

QPushButton#primaryButton {
    background-color: #0284c7;
    color: #ffffff;
    border: 1px solid #0369a1;
    font-weight: 600;
}

QPushButton#primaryButton:hover {
    background-color: #0369a1;
}

QPushButton#primaryButton:pressed {
    background-color: #075985;
}

/* ==========================================================================
   Input Controls: QLineEdit, QComboBox, QSpinBox, QPlainTextEdit
   ========================================================================== */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px 8px;
    color: #0f172a;
    min-height: 22px;
    font-size: 12px;
}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1.5px solid #0284c7;
    background-color: #ffffff;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QPlainTextEdit, QTextEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    color: #0f172a;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    font-size: 12px;
    padding: 6px;
}

/* ==========================================================================
   QGroupBox (Modern Card style)
   ========================================================================== */
QGroupBox {
    font-weight: 600;
    font-size: 13px;
    color: #0f172a;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    background-color: #ffffff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    background-color: #ffffff;
    color: #0f172a;
}

/* ==========================================================================
   QRadioButton & QCheckBox
   ========================================================================== */
QRadioButton, QCheckBox {
    color: #1e293b;
    font-size: 12px;
    spacing: 6px;
    background-color: transparent;
}

QRadioButton::indicator, QCheckBox::indicator {
    width: 16px;
    height: 16px;
}

/* ==========================================================================
   QStatusBar
   ========================================================================== */
QStatusBar {
    background-color: #ffffff;
    border-top: 1px solid #e2e8f0;
    color: #64748b;
    padding: 3px 10px;
}

QStatusBar QLabel {
    color: #475569;
    font-size: 12px;
}

/* ==========================================================================
   QScrollArea
   ========================================================================== */
QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

/* ==========================================================================
   QScrollBar (Sleek modern scrollbar)
   ========================================================================== */
QScrollBar:vertical {
    background: #f8fafc;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #cbd5e1;
    min-height: 24px;
    border-radius: 5px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background: #f8fafc;
    height: 10px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #cbd5e1;
    min-width: 24px;
    border-radius: 5px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background: #94a3b8;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
"""


def apply_calibre_theme(app: QApplication) -> None:
    """Apply the Calibre stylesheet and clean typography settings to the QApplication."""
    if not app:
        logger.warning("apply_calibre_theme called without QApplication instance.")
        return

    # Select the cleanest available system sans-serif font
    preferred_fonts = [
        "Segoe UI",
        "Ubuntu",
        "Inter",
        "Roboto",
        "DejaVu Sans",
        "Helvetica Neue",
        "Arial",
    ]
    available = set(QFontDatabase.families())
    chosen_family = None
    for cand in preferred_fonts:
        if cand in available:
            chosen_family = cand
            break

    if chosen_family:
        default_font = QFont(chosen_family)
    else:
        default_font = QFont()
        default_font.setStyleHint(QFont.SansSerif)

    default_font.setPointSize(10)
    app.setFont(default_font)

    # Apply stylesheet
    app.setStyleSheet(CALIBRE_QSS)
    logger.info("Calibre modern theme successfully applied to QApplication.")

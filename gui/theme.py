"""Calibre-inspired Modern Stylesheet and Theme Configuration.

Provides a clean, functional desktop styling inspired by Calibre e-book manager:
- Prominent toolbar with generous button targets and clear icon/text layout
- High-contrast, clean QTabWidget tabs
- Polished, neatly striped QTableWidget
- Smooth, high-contrast modern progress bars
- Subtle, clean QStatusBar with status badges
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

logger = logging.getLogger("epub_translate.gui.theme")

# Calibre Modern QSS Stylesheet
CALIBRE_QSS = """
/* ==========================================================================
   Base Window & Font
   ========================================================================== */
QWidget {
    background-color: #f8fafc;
    color: #1e293b;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    selection-background-color: #2b5797;
    selection-color: #ffffff;
}

QMainWindow {
    background-color: #f1f5f9;
}

/* ==========================================================================
   Calibre Top Action Toolbar
   ========================================================================== */
QToolBar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #f1f5f9);
    border-bottom: 1px solid #cbd5e1;
    padding: 6px 10px;
    spacing: 6px;
}

QToolBar::separator {
    width: 1px;
    background-color: #cbd5e1;
    margin: 4px 8px;
}

QToolButton {
    background-color: transparent;
    color: #1e293b;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 10px;
    font-weight: 500;
    min-width: 68px;
}

QToolButton:hover {
    background-color: #e2e8f0;
    border: 1px solid #cbd5e1;
}

QToolButton:pressed {
    background-color: #cbd5e1;
    border: 1px solid #94a3b8;
}

QToolButton:disabled {
    color: #94a3b8;
}

/* ==========================================================================
   QTabWidget (Calibre Navigation Tabs)
   ========================================================================== */
QTabWidget::pane {
    border: 1px solid #cbd5e1;
    background-color: #ffffff;
    top: -1px;
    border-radius: 4px;
}

QTabBar::tab {
    background: #e2e8f0;
    color: #475569;
    border: 1px solid #cbd5e1;
    border-bottom-color: #cbd5e1;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 18px;
    margin-right: 3px;
    font-weight: 600;
}

QTabBar::tab:hover {
    background: #f1f5f9;
    color: #0f172a;
}

QTabBar::tab:selected {
    background: #ffffff;
    color: #2b5797;
    border-bottom: 2px solid #2b5797;
    border-top: 2px solid #2b5797;
}

/* ==========================================================================
   QTableWidget & QTableView (Neat, clean borders & alternating rows)
   ========================================================================== */
QTableWidget, QTableView {
    background-color: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    gridline-color: #e2e8f0;
    selection-background-color: #e0f2fe;
    selection-color: #0369a1;
}

QHeaderView::section {
    background-color: #f1f5f9;
    color: #334155;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #cbd5e1;
    border-bottom: 1px solid #cbd5e1;
    font-weight: 600;
}

QHeaderView::section:hover {
    background-color: #e2e8f0;
}

/* ==========================================================================
   QProgressBar (Modern, high contrast)
   ========================================================================== */
QProgressBar {
    background-color: #e2e8f0;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    text-align: center;
    color: #0f172a;
    font-weight: 600;
    min-height: 20px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0ea5e9);
    border-radius: 5px;
}

/* Secondary / Chapter progress bar variant via object name */
QProgressBar#chapterProgress::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #34d399);
}

/* ==========================================================================
   Buttons (Standard UI Buttons)
   ========================================================================== */
QPushButton {
    background-color: #ffffff;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    padding: 6px 14px;
    font-weight: 500;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
    color: #0f172a;
}

QPushButton:pressed {
    background-color: #e2e8f0;
}

QPushButton:disabled {
    background-color: #f8fafc;
    color: #94a3b8;
    border-color: #e2e8f0;
}

QPushButton#primaryButton {
    background-color: #2b5797;
    color: #ffffff;
    border: 1px solid #1e3e6b;
    font-weight: 600;
}

QPushButton#primaryButton:hover {
    background-color: #1e3e6b;
}

QPushButton#primaryButton:pressed {
    background-color: #162d4e;
}

/* ==========================================================================
   Input Controls: QLineEdit, QComboBox, QSpinBox, QPlainTextEdit
   ========================================================================== */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    padding: 5px 8px;
    color: #0f172a;
    min-height: 22px;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #2b5797;
    background-color: #ffffff;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

QPlainTextEdit, QTextEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    color: #0f172a;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    font-size: 12px;
}

/* ==========================================================================
   QGroupBox
   ========================================================================== */
QGroupBox {
    font-weight: 600;
    color: #1e293b;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    margin-top: 12px;
    padding: 14px 10px 10px 10px;
    background-color: #ffffff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
    background-color: #ffffff;
}

/* ==========================================================================
   QStatusBar
   ========================================================================== */
QStatusBar {
    background-color: #f1f5f9;
    border-top: 1px solid #cbd5e1;
    color: #475569;
    padding: 2px 8px;
}

QStatusBar QLabel {
    color: #475569;
}

/* ==========================================================================
   QScrollBar
   ========================================================================== */
QScrollBar:vertical {
    background: #f1f5f9;
    width: 12px;
    margin: 0px;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background: #cbd5e1;
    min-height: 24px;
    border-radius: 6px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background: #f1f5f9;
    height: 12px;
    margin: 0px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal {
    background: #cbd5e1;
    min-width: 24px;
    border-radius: 6px;
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
    """Apply the Calibre stylesheet and typography settings to the QApplication."""
    if not app:
        logger.warning("apply_calibre_theme called without QApplication instance.")
        return

    # Set default clean system font
    default_font = QFont("-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif")
    default_font.setPointSize(10)
    app.setFont(default_font)

    # Apply stylesheet
    app.setStyleSheet(CALIBRE_QSS)
    logger.info("Calibre theme successfully applied to QApplication.")


#!/usr/bin/env python3
"""Desktop Application Entry Point for EPUB Translator (Calibre Edition)."""

from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from gui.theme import apply_calibre_theme


def main() -> None:
    """Initialize QApplication, configure Calibre theme, and execute event loop."""
    app = QApplication(sys.argv)
    app.setApplicationName("EPUB Translator")
    app.setOrganizationName("EPUBTranslator")

    # Apply Calibre visual theme
    apply_calibre_theme(app)

    # Initialize and show main window
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
"""Desktop Build and Automation Script for EPUB Translator (Windows / Linux).

Automates:
- Generation of app_icon.ico from Calibre SVG vector assets
- PyInstaller dependency check and packaging execution
- Output validation in dist/EPUBTranslator/
- Supports --dry-run for CI/CD checks without compiling
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def generate_icon(output_path: Path = Path("app_icon.ico")) -> bool:
    """Generate high-resolution application icon from built-in SVG assets."""
    if output_path.exists():
        print(f"[OK] App icon already exists: {output_path.name}")
        return True

    print(f"[*] Generating {output_path.name} from SVG vector assets...")
    try:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtCore import QByteArray, QRectF, Qt
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtWidgets import QApplication

        from gui.assets import SVG_ICONS

        app = QApplication.instance() or QApplication([])

        # Use Calibre Library blue book SVG
        svg_xml = SVG_ICONS.get("open_epub", "").format(color="#2b5797")
        renderer = QSvgRenderer(QByteArray(svg_xml.strip().encode("utf-8")))

        if not renderer.isValid():
            print("[WARN] Invalid SVG data, skipping icon generation.")
            return False

        # Render 128x128 icon with padding
        pixmap = QPixmap(128, 128)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        renderer.render(painter, QRectF(8, 8, 112, 112))
        painter.end()

        success = pixmap.save(str(output_path), "ICO")
        if success:
            print(f"[OK] Successfully generated {output_path.name} ({output_path.stat().st_size} bytes)")
            return True
        else:
            print(f"[WARN] Failed to save {output_path.name}")
            return False

    except Exception as exc:
        print(f"[WARN] Could not generate icon automatically: {exc}")
        return False


def run_checks(spec_file: Path) -> bool:
    """Perform pre-build dependency and file verification."""
    print("\n" + "=" * 60)
    print("PRE-BUILD VERIFICATION CHECKS")
    print("=" * 60)

    # 1. Entry point check
    entry_point = Path("desktop_app.py")
    if not entry_point.is_file():
        print(f"[FAIL] Missing entry point: {entry_point}")
        return False
    print(f"[PASS] Entry point found: {entry_point}")

    # 2. Spec file check
    if not spec_file.is_file():
        print(f"[FAIL] Missing PyInstaller spec: {spec_file}")
        return False
    print(f"[PASS] Spec file found: {spec_file}")

    # 3. Required packages check
    required_modules = [
        "PySide6",
        "google.genai",
        "lxml",
        "pydantic",
        "dotenv",
    ]
    missing = []
    for mod in required_modules:
        try:
            __import__(mod)
            print(f"[PASS] Dependency available: {mod}")
        except ImportError:
            missing.append(mod)
            print(f"[FAIL] Missing dependency: {mod}")

    if missing:
        print(f"\n[FAIL] Please install missing dependencies: {', '.join(missing)}")
        return False

    # 4. PyInstaller check
    try:
        import PyInstaller
        print(f"[PASS] PyInstaller available (v{PyInstaller.__version__})")
    except ImportError:
        print("[FAIL] PyInstaller not installed in current environment.")
        return False

    # 5. Icon check / generation
    generate_icon()

    print("=" * 60)
    print("[PASS] All pre-build checks passed successfully!")
    print("=" * 60 + "\n")
    return True


def build_executable(spec_file: Path, clean: bool = True) -> int:
    """Execute PyInstaller build using spec file."""
    cmd = [sys.executable, "-m", "PyInstaller"]
    if clean:
        cmd.append("--clean")
    cmd.append(str(spec_file))

    print(f"[*] Executing build command: {' '.join(cmd)}")
    result = subprocess.run(cmd)

    if result.returncode == 0:
        dist_dir = Path("dist") / "EPUBTranslator"
        print("\n" + "=" * 60)
        print("BUILD SUCCESSFUL!")
        print("=" * 60)
        print(f"Output directory: {dist_dir.resolve()}")

        exe_ext = ".exe" if sys.platform == "win32" else ""
        target_bin = dist_dir / f"EPUBTranslator{exe_ext}"
        if target_bin.exists():
            print(f"Application executable: {target_bin}")
        print("=" * 60 + "\n")
    else:
        print(f"\n[FAIL] Build process exited with error code {result.returncode}")

    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="Build EPUB Translator desktop executable.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate environment and spec file without compiling executable.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip PyInstaller clean cache flag.",
    )
    parser.add_argument(
        "--spec",
        type=str,
        default="EPUBTranslator.spec",
        help="PyInstaller spec file to use (default: EPUBTranslator.spec)",
    )

    args = parser.parse_args()
    spec_path = Path(args.spec)

    # 1. Run environment checks
    checks_passed = run_checks(spec_path)
    if not checks_passed:
        sys.exit(1)

    # 2. Dry run exit
    if args.dry_run:
        print("[INFO] Dry run requested. Exiting without compilation.")
        sys.exit(0)

    # 3. Build executable
    return_code = build_executable(spec_path, clean=not args.no_clean)
    sys.exit(return_code)


if __name__ == "__main__":
    main()


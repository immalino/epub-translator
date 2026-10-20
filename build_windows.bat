@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   EPUB Translator - Windows Desktop Executable Builder
echo ============================================================
echo.

:: 1. Check Python installation
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python tidak ditemukan di PATH sistem!
    echo Silakan install Python 3.10+ dari https://www.python.org/
    echo Pastikan opsi "Add Python to PATH" dicentang saat instalasi.
    pause
    exit /b 1
)

python -c "import sys; print(f'Menggunakan Python: {sys.version}')"
echo.

:: 2. Check / Create Virtual Environment
if not exist ".venv" (
    echo [*] Membuat virtual environment baru (.venv)...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Gagal membuat virtual environment!
        pause
        exit /b 1
    )
)

:: 3. Activate Virtual Environment
echo [*] Mengaktifkan virtual environment...
call .venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [ERROR] Gagal mengaktifkan .venv!
    pause
    exit /b 1
)

:: 4. Install / Update Dependencies
echo [*] Memeriksa dan menginstal dependensi dari requirements.txt...
pip install --upgrade pip
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Gagal menginstal dependensi requirements.txt!
    pause
    exit /b 1
)

:: 5. Execute Desktop Build
echo.
echo [*] Memulai proses kompilasi standalone executable...
python build_desktop.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Proses build PyInstaller gagal!
    pause
    exit /b %errorlevel%
)

echo.
echo ============================================================
echo   BUILD SELESAI DENGAN SUKSES!
echo ============================================================
echo Aplikasi standalone siap dijalankan di:
echo dist\EPUBTranslator\EPUBTranslator.exe
echo.
pause


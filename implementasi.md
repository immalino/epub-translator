# Panduan Implementasi Bertahap: Desktop Windows EPUB Translator (Calibre UI)

Dokumen ini membagi pengerjaan aplikasi desktop **EPUB Translator** menjadi **6 Sesi Terfokus**. 
Setiap sesi dirancang mandiri, memiliki langkah teknis yang jelas, kriteria pengujian yang dapat diverifikasi langsung, serta **Template Prompt Siap Pakai** yang dapat langsung Anda kirim ke AI (bahkan untuk model AI yang lebih ringan/murah) untuk memulai sesi tersebut.

---

## 🗺️ Peta Jalan Sesi (Roadmap)

| Sesi | Fokus Utama | Output / Hasil |
| :--- | :--- | :--- |
| **Sesi 1** | Pondasi Threading & Runner Core | `requirements.txt`, jeda/batal di `runner.py`, `gui/worker.py` |
| **Sesi 2** | Tema Calibre & Kerangka Window Utama | `gui/theme.py`, `gui/assets.py`, `gui/main_window.py`, `desktop_app.py` |
| **Sesi 3** | Tab 1: Penerjemahan & Monitor Tugas | `gui/tab_translate.py` (Cover, Tabel Bab, Dual Progress, Live Log) |
| **Sesi 4** | Tab 2 & Tab 3: Editor Bilingual & Glosarium | `gui/tab_bilingual.py` (Advanced Mode) & `gui/tab_glossary.py` |
| **Sesi 5** | Tab 4 & Tab 5: Pengaturan Mesin & Validasi | `gui/tab_settings.py` (Multi-Key, Ollama) & `gui/tab_validator.py` |
| **Sesi 6** | Packaging Windows Executable (.exe) & Installer | `EPUBTranslator.spec`, `build_desktop.py`, `build_windows.bat`, Inno Setup |

---

## 📌 SESI 1: Pondasi Threading Core & Controller Interupsi

### 1. Tujuan
Memastikan eksekusi terjemahan di `runner.py` dapat dijeda (*pause*), dilanjutkan (*resume*), dan dibatalkan (*cancel*) secara aman tanpa merusak checkpoint disk, serta membuat `TranslationWorker` berbasis `QThread` yang memancarkan sinyal (*Qt Signals*) ke GUI.

### 2. File yang Dikerjakan
- **[MODIFY] `requirements.txt`**: Tambahkan `PySide6-Essentials>=6.7.0` dan `pyinstaller>=6.5.0`.
- **[MODIFY] `runner.py`**:
  - Tambahkan parameter opsional pada `run_translation`: `pause_event=None`, `cancel_event=None`.
  - Di dalam perulangan batch (`for b_idx, batch in enumerate(batches, 1):`):
    - Jika `cancel_event` diset: simpan log, keluar dengan return code khusus, dan jangan rusak checkpoint.
    - Jika `pause_event` dalam keadaan jeda: tunggu hingga event dilanjutkan (*wait*).
- **[NEW] `gui/__init__.py`**: File init kosong untuk package `gui`.
- **[NEW] `gui/worker.py`**:
  - Kelas `QtTranslationCallback(TranslationCallback)`: Meneruskan callback runner ke sinyal Qt:
    - `sig_log = Signal(str, str)` (level, pesan)
    - `sig_overall_progress = Signal(float, str)` (persentase 0.0-1.0, teks)
    - `sig_batch_progress = Signal(float, str)` (persentase 0.0-1.0, teks)
    - `sig_chapter_status = Signal(int, str)` (indeks bab, status)
    - `sig_quota_warning = Signal(str)` (pesan peringatan limit)
    - `sig_completed = Signal(str, float, object)` (output_path, elapsed_time, report)
    - `sig_error = Signal(str)` (pesan error)
  - Kelas `TranslationWorker(QThread)`:
    - Memiliki method: `start_translation(...)`, `pause()`, `resume()`, `cancel()`.
    - Menjalankan `TranslationRunner.run_translation()` di method `run()` menggunakan `threading.Event`.
- **[NEW] `tests/test_worker_runner.py`**: Pengujian unit untuk verifikasi sinyal worker dan pause/cancel.

### 3. Perintah Verifikasi
```bash
.venv/bin/pip install PySide6-Essentials pyinstaller
.venv/bin/pytest tests/test_worker_runner.py -v
```

---

### 📋 PROMPT UNTUK MEMULAI SESI 1
*(Salin teks di bawah ini dan kirimkan ke AI)*

```text
Halo! Kita akan mengerjakan SESI 1 dari implementasi aplikasi desktop EPUB Translator: "Pondasi Threading Core & Controller Interupsi".

Tugas utama di sesi ini:
1. Perbarui requirements.txt dengan menambahkan:
   PySide6-Essentials>=6.7.0
   pyinstaller>=6.5.0
   dan pastikan dependensi ini terpasang di .venv.

2. Modifikasi runner.py:
   - Tambahkan dukungan cooperative pause dan cancellation pada fungsi TranslationRunner.run_translation.
   - Gunakan parameter opsional pause_event (threading.Event) dan cancel_event (threading.Event).
   - Pastikan di setiap iterasi batch terdapat pemeriksaan jika cancel_event.is_set(), maka proses berhenti dengan rapi tanpa merusak checkpoint disk.
   - Jika pause_event diset jeda, thread menunggu secara aman hingga resumed.

3. Buat folder `gui/` dengan file `gui/__init__.py`.

4. Buat file `gui/worker.py`:
   - Buat kelas QtTranslationCallback yang mewarisi TranslationCallback dan memancarkan sinyal PySide6.QtCore.Signal untuk: log, overall_progress, batch_progress, chapter_status, quota_warning, completed, dan error.
   - Buat kelas TranslationWorker yang mewarisi QThread dengan method: pause(), resume(), cancel(), dan is_paused().

5. Buat file pengujian `tests/test_worker_runner.py` untuk menguji bahwa worker dapat memancarkan sinyal, serta fungsi pause dan cancel berjalan dengan benar. Jalankan pytest untuk memastikan semuanya hijau (passed).

Kerjakan langkah-langkah di atas dengan teliti dan laporkan hasilnya setelah diverifikasi.
```

---

## 📌 SESI 2: Tema Khas Calibre, Aset Ikon, & Kerangka Window Utama

### 1. Tujuan
Membuat antarmuka dasar aplikasi desktop yang bergaya **plugin Calibre**: tema visual QSS yang rapi, aset ikon terintegrasi, toolbar aksi atas dengan tombol ikonik Calibre, tab-widget utama, dan status bar. Aplikasi dapat langsung dibuka dan dijalankan via `python desktop_app.py`.

### 2. File yang Dikerjakan
- **[NEW] `gui/theme.py`**:
  - Palet warna Calibre: Background abu-abu lembut (`#f5f5f7` / `#ffffff`), border abu-abu rapi (`#d0d0d5`), tombol dengan hover halus, header tabel bergaya modern, progress bar dengan border bulat dan warna progres biru segar (`#2a75d3`).
  - Fungsi `apply_calibre_theme(app: QApplication)`.
- **[NEW] `gui/assets.py`**:
  - Menyediakan ikon-ikon aplikasi dalam bentuk SVG/QIcon bawaan (tanpa perlu aset gambar eksternal yang rawan hilang):
    - `icon_open()`, `icon_start()`, `icon_pause()`, `icon_stop()`, `icon_dry_run()`, `icon_book()`, `icon_settings()`, `icon_dictionary()`, `icon_preview()`, `icon_check()`, `icon_folder()`.
- **[NEW] `gui/main_window.py`**:
  - Kelas `MainWindow(QMainWindow)`:
    - **Toolbar Aksi Calibre (Atas)**: Tombol-tombol berikon besar khas Calibre:
      - 📂 *Buka EPUB* (`Ctrl+O`)
      - ▶️ *Mulai Terjemahkan* (`F5`)
      - ⏸️ *Jeda / Lanjut*
      - ⏹️ *Stop / Batal*
      - 🔍 *Estimasi (Dry Run)*
      - 📁 *Buka Folder Output*
    - **QTabWidget Utama**:
      - Tab 1: Penerjemahan & Monitor
      - Tab 2: Editor Bilingual (Advanced Mode)
      - Tab 3: Glosarium Istilah
      - Tab 4: Pengaturan Mesin & API
      - Tab 5: Validasi EPUB
    - **Status Bar (Bawah)**: Status mesin aktif, jumlah kunci API yang siap, indikator checkpoint.
- **[NEW] `desktop_app.py`**:
  - File entry point utama untuk menjalankan desktop app:
    ```python
    import sys
    from PySide6.QtWidgets import QApplication
    from gui.theme import apply_calibre_theme
    from gui.main_window import MainWindow

    def main():
        app = QApplication(sys.argv)
        apply_calibre_theme(app)
        window = MainWindow()
        window.show()
        sys.exit(app.exec())

    if __name__ == "__main__":
        main()
    ```

### 3. Perintah Verifikasi
```bash
.venv/bin/python -c "from gui.main_window import MainWindow; from PySide6.QtWidgets import QApplication; import sys; app = QApplication(sys.argv); w = MainWindow(); print('Window title:', w.windowTitle())"
```

---

### 📋 PROMPT UNTUK MEMULAI SESI 2
*(Salin teks di bawah ini dan kirimkan ke AI)*

```text
Halo! Kita akan mengerjakan SESI 2 dari implementasi aplikasi desktop EPUB Translator: "Tema Khas Calibre, Aset Ikon, & Kerangka Window Utama".

Prasyarat: Sesi 1 telah selesai.

Tugas utama di sesi ini:
1. Buat file `gui/assets.py`:
   - Sediakan fungsi pembuat QIcon (menggunakan SVG strings atau QPainter) untuk aksi: Buka EPUB, Mulai, Jeda, Stop, Dry Run, Glosarium, Editor Bilingual, Pengaturan, Validasi, dan Folder Output.

2. Buat file `gui/theme.py`:
   - Tulis stylesheet Qt (QSS) dengan tema bersih ala Calibre: toolbar dengan tombol jelas (teks di bawah ikon atau di samping), QTabWidget dengan tab yang tegas, QTableWidget bergaris rapi, QProgressBar modern dengan warna kontras, dan status bar yang bersih.
   - Buat fungsi apply_calibre_theme(app).

3. Buat file `gui/main_window.py`:
   - Buat kelas MainWindow(QMainWindow).
   - Pasang Toolbar Aksi di bagian atas bergaya plugin Calibre: Buka EPUB, Mulai Terjemahkan, Jeda/Lanjut, Stop, Estimasi (Dry Run), dan Buka Folder Hasil.
   - Pasang QTabWidget di area sentral yang menampung 5 tab (buat placeholder widget terlebih dahulu untuk tab-tab tersebut).
   - Pasang QStatusBar di bagian bawah untuk menampilkan status koneksi dan ringkasan ringkas.
   - Tangani event closeEvent agar meminta konfirmasi jika worker sedang bekerja.

4. Buat entry point `desktop_app.py` yang menginisialisasi QApplication, menerapkan tema Calibre, menampilkan MainWindow, dan menjalankan event loop.

5. Verifikasi bahwa MainWindow dapat diinstansiasi tanpa error melalui skrip pengujian atau baris perintah Python.

Laporkan jika struktur jendela utama dan tema Calibre telah berhasil terpasang.
```

---

## 📌 SESI 3: Tab 1 - Penerjemahan & Monitor Tugas (Calibre Main View)

### 1. Tujuan
Membangun antarmuka utama penerjemahan di mana pengguna dapat membuka file EPUB, melihat cover & metadata buku, memilih bab mana saja yang ingin diterjemahkan via tabel checklist, memantau kemajuan terjemahan dengan dual progress bar, serta melihat log langsung.

### 2. File yang Dikerjakan
- **[NEW] `gui/tab_translate.py`**:
  - Kelas `TabTranslate(QWidget)` yang terdiri dari 3 panel:
    1. **Panel Kiri (Informasi Buku & Opsi Cepat)**:
       - Cover preview thumbnail (menggunakan `QLabel` + `QPixmap` dari `cover_bytes`).
       - Info judul, pengarang, bahasa asli, jumlah bab, estimasi kata.
       - Pilihan Bahasa Target (default: `id` / Bahasa Indonesia).
       - Pilihan Gaya Bahasa (Sastra Alami, Formal, Santai).
       - Pilihan Mesin (Google Gemini / Ollama Lokal).
    2. **Panel Kanan (Tabel Bab / Spine Table)**:
       - `QTableWidget` dengan kolom:
         - `[x]` Checkbox (Pilih)
         - No. Bab
         - Nama File XHTML / Spine
         - Jumlah Paragraf / Segmen
         - Jumlah Karakter
         - Status (*Menunggu*, *Memproses*, *Selesai*, *Gagal*) dengan warna badge.
       - Tombol aksi: "Pilih Semua", "Batalkan Semua", "Pilih Bab Gagal".
    3. **Panel Bawah (Monitor Progres & Konsol Log)**:
       - Progres Buku Keseluruhan (`QProgressBar`, 0-100%).
       - Progres Bab yang Sedang Berjalan (`QProgressBar`, 0-100%).
       - Label status (Kecepatan, Waktu Berjalan, Sisa Waktu).
       - Live Log Console (`QPlainTextEdit` read-only) dengan auto-scroll ke baris terbaru, tombol "Salin Log" dan "Bersihkan Log".
- **[MODIFY] `gui/main_window.py`**:
  - Pasang `TabTranslate` ke Tab ke-1.
  - Hubungkan tombol Toolbar atas (Buka EPUB, Mulai, Jeda, Stop, Dry Run) ke slot pada `TabTranslate` dan `TranslationWorker`.
  - Hubungkan sinyal dari `TranslationWorker` ke progress bar, tabel bab, dan log console.
- **[NEW] `tests/test_tab_translate.py`**: Pengujian pemuatan EPUB ke tabel bab dan update status.

### 3. Perintah Verifikasi
```bash
.venv/bin/pytest tests/test_tab_translate.py -v
```

---

### 📋 PROMPT UNTUK MEMULAI SESI 3
*(Salin teks di bawah ini dan kirimkan ke AI)*

```text
Halo! Kita akan mengerjakan SESI 3 dari implementasi aplikasi desktop EPUB Translator: "Tab 1 - Penerjemahan & Monitor Tugas".

Prasyarat: Sesi 1 dan Sesi 2 telah selesai.

Tugas utama di sesi ini:
1. Buat file `gui/tab_translate.py` dengan kelas TabTranslate(QWidget):
   - Integrasikan fungsi TranslationRunner.inspect_epub() ketika file EPUB dipilih.
   - Tampilkan thumbnail cover buku, judul, pengarang, dan ringkasan kata pada panel info buku.
   - Buat tabel bab (QTableWidget) dengan checkbox per baris, nomor bab, path spine, jumlah segmen, jumlah karakter, dan status. Sediakan tombol "Pilih Semua" dan "Batalkan Semua".
   - Sediakan tombol "Estimasi Biaya & Kuota (Dry Run)" yang menampilkan dialog detail perkiraan token, jumlah panggilan API, dan estimasi waktu dari TranslationRunner.get_dry_run_stats().
   - Sediakan Dual Progress Bar: satu untuk progres keseluruhan buku, satu untuk progres batch bab aktif.
   - Sediakan konsol log real-time (QPlainTextEdit) dengan auto-scroll dan tombol salin log.

2. Hubungkan TabTranslate dan tombol Toolbar di `gui/main_window.py`:
   - Tombol "Buka EPUB" membuka QFileDialog (filter *.epub) lalu memanggil inspeksi buku.
   - Tombol "Mulai Terjemahkan" memeriksa bab yang dicentang, menginisialisasi TranslationWorker, dan memulai proses penerjemahan.
   - Tombol "Jeda / Lanjut" memicu worker.pause() atau worker.resume().
   - Tombol "Stop / Batal" memicu worker.cancel().
   - Hubungkan seluruh sinyal worker (sig_log, sig_overall_progress, sig_batch_progress, sig_chapter_status, sig_completed, sig_error) untuk memperbarui progress bar, status tabel bab, dan log secara real-time.

3. Buat file pengujian `tests/test_tab_translate.py` untuk menguji pemuatan fixture `tests/fixtures/sample_novel.epub` ke dalam tabel bab TabTranslate dan respon sinyal worker.

Pastikan seluruh pengujian pytest berhasil dan antarmuka Tab 1 berfungsi mulus.
```

---

## 📌 SESI 4: Tab 2 & Tab 3 - Editor Bilingual (Advanced Mode) & Glosarium

### 1. Tujuan
- Membangun **Tab 2 (Editor Bilingual / Advanced Mode Calibre)**: Menampilkan teks asli dan teks terjemahan berdampingan per bab, memungkinkan koreksi langsung teks terjemahan dan menyimpannya ke checkpoint cache.
- Membangun **Tab 3 (Editor Glosarium)**: Tabel visual istilah istilah khusus/karakter novel, fitur tambah/hapus istilah, pencarian, dan impor/ekspor file JSON glosarium.

### 2. File yang Dikerjakan
- **[NEW] `gui/tab_bilingual.py`**:
  - Dropdown pemilih bab dari buku yang dimuat.
  - Tabel 2 Kolom (`QTableWidget`):
    - Kolom Kiri: Teks Asli Bahasa Inggris (Read-only).
    - Kolom Kanan: Teks Terjemahan Bahasa Indonesia (Editable langsung oleh pengguna).
  - Kolom Filter & Pencarian: Mencari kata tertentu di dalam segmen bab.
  - Tombol "Simpan Perubahan ke Cache": Memperbarui hasil edit ke `CheckpointManager` sehingga saat build EPUB, editan manual pengguna akan masuk ke file EPUB akhir.
- **[NEW] `gui/tab_glossary.py`**:
  - Tabel Glosarium (`QTableWidget`):
    - Kolom: Istilah Sumber, Padanan Terjemahan, Catatan / Konteks, Peka Huruf Besar (Checkbox).
  - Tombol Aksi:
    - ➕ Tambah Istilah
    - ➖ Hapus Istilah Terpilih
    - 📂 Impor Glosarium dari File JSON
    - 💾 Simpan / Ekspor Glosarium ke JSON
  - Bar pencarian istilah cepat.
  - Sinkronisasi dengan objek `Glossary` di backend.
- **[MODIFY] `gui/main_window.py`**:
  - Sematkan `TabBilingual` pada Tab ke-2 dan `TabGlossary` pada Tab ke-3.
  - Bila file EPUB dibuka di Tab 1, otomatis perbarui daftar bab di Tab 2.
- **[NEW] `tests/test_bilingual_glossary.py`**: Pengujian unit untuk fungsi load segmen bilingual dan manipulasi glosarium.

### 3. Perintah Verifikasi
```bash
.venv/bin/pytest tests/test_bilingual_glossary.py -v
```

---

### 📋 PROMPT UNTUK MEMULAI SESI 4
*(Salin teks di bawah ini dan kirimkan ke AI)*

```text
Halo! Kita akan mengerjakan SESI 4 dari implementasi aplikasi desktop EPUB Translator: "Tab 2 (Editor Bilingual) & Tab 3 (Glosarium)".

Prasyarat: Sesi 1, 2, dan 3 telah selesai.

Tugas utama di sesi ini:
1. Buat file `gui/tab_bilingual.py` (Advanced Mode Calibre):
   - Buat kelas TabBilingual(QWidget).
   - Sediakan QComboBox untuk memilih bab dari buku yang sedang dibuka.
   - Gunakan TranslationRunner.get_bilingual_preview() untuk mengambil pasangan segmen asli dan terjemahan.
   - Tampilkan pada tabel side-by-side: kolom 1 ID/Index, kolom 2 Teks Asli (read-only), kolom 3 Teks Terjemahan (editable).
   - Sediakan kolom pencarian teks untuk memfilter baris segmen tertentu.
   - Sediakan tombol "Simpan Perubahan ke Cache" untuk memperbarui terjemahan di CheckpointManager.

2. Buat file `gui/tab_glossary.py`:
   - Buat kelas TabGlossary(QWidget).
   - Buat tabel manajemen istilah glosarium: Kolom Istilah Sumber, Terjemahan, Catatan Konteks, dan Peka Huruf Besar (Case-sensitive).
   - Sediakan tombol Tambah Baris, Hapus Baris, tombol Impor JSON (membaca format JSON glosarium), dan tombol Ekspor JSON.
   - Sediakan method get_glossary() yang mengembalikan objek Glossary untuk digunakan oleh runner.

3. Pasang kedua tab ini ke dalam `gui/main_window.py`:
   - Tab 2: TabBilingual.
   - Tab 3: TabGlossary.
   - Saat buku baru dibuka di TabTranslate, kirimkan informasi buku ke TabBilingual agar daftar bab sinkron.
   - Saat tombol "Mulai Terjemahkan" diklik, operkan objek Glossary dari TabGlossary ke runner.

4. Buat file pengujian `tests/test_bilingual_glossary.py` untuk memvalidasi operasi tabel bilingual dan impor/ekspor glosarium.

Pastikan semua pengujian lulus dan laporkan hasilnya.
```

---

## 📌 SESI 5: Tab 4 & Tab 5 - Pengaturan Mesin & Validasi EPUB

### 1. Tujuan
- Membangun **Tab 4 (Pengaturan Mesin & Kunci API)**: Memasukkan dan mengelola multi Gemini API Key, uji validitas kunci langsung ke server Google GenAI SDK, pengaturan rotasi kunci, konfigurasi server Ollama lokal, dan parameter batch/timeout.
- Membangun **Tab 5 (Validasi EPUB)**: Menjalankan validasi struktur file EPUB hasil terjemahan (validasi ZIP, OPF, XML) dan Calibre CLI `ebook-validate` jika tersedia di sistem.

### 2. File yang Dikerjakan
- **[NEW] `gui/tab_settings.py`**:
  - Panel Gemini API:
    - Input daftar API Key (bisa input banyak kunci, dengan tombol "Tambah Kunci", "Hapus Kunci", dan opsi sembunyikan/sensor bintang).
    - Tombol "Tes Koneksi Kunci API" (menguji apakah kunci aktif menggunakan `google-genai` SDK).
    - Pilihan Model Gemini (`gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-1.5-flash`, `gemini-3.5-flash-lite`, Custom).
    - Pilihan Strategi Rotasi (`round_robin` / `fallback_on_limit`).
  - Panel Ollama Lokal:
    - Input Endpoint URL (default: `http://localhost:11434`).
    - Tombol "Cek Status Ollama" (menguji ketersediaan server).
    - Input nama model Ollama (default: `translategemma:4b`).
  - Panel Parameter Terjemahan:
    - Batch size (jumlah segmen per request).
    - Timeout (detik), Max Retries, Request Delay.
    - Lokasi folder output default & folder checkpoint cache.
  - Tombol "Simpan Pengaturan ke .env".
- **[NEW] `gui/tab_validator.py`**:
  - Pemilih file EPUB yang ingin divalidasi.
  - Tombol "Jalankan Validasi".
  - Tampilan hasil validasi terstruktur (Status MIME, OPF, Link, XML, ebook-validate Calibre) dengan icon centang hijau atau silang merah.
- **[MODIFY] `gui/main_window.py`**:
  - Sematkan `TabSettings` pada Tab ke-4 dan `TabValidator` pada Tab ke-5.
  - Tombol "Buka Pengaturan" di Toolbar membuka Tab ke-4.
  - Setelah terjemahan selesai di Tab 1, otomatis beri opsi validasi langsung ke Tab 5.
- **[NEW] `tests/test_settings_validator.py`**: Pengujian unit untuk parsing konfigurasi dan validasi tampilan.

### 3. Perintah Verifikasi
```bash
.venv/bin/pytest tests/test_settings_validator.py -v
```

---

### 📋 PROMPT UNTUK MEMULAI SESI 5
*(Salin teks di bawah ini dan kirimkan ke AI)*

```text
Halo! Kita akan mengerjakan SESI 5 dari implementasi aplikasi desktop EPUB Translator: "Tab 4 (Pengaturan Mesin & Kunci API) & Tab 5 (Validasi EPUB)".

Prasyarat: Sesi 1 sampai Sesi 4 telah selesai.

Tugas utama di sesi ini:
1. Buat file `gui/tab_settings.py`:
   - Buat kelas TabSettings(QWidget).
   - Pengaturan Gemini: Daftar API Key yang dapat ditambah/dihapus secara dinamis, tombol "Uji Kunci API" ke server Google GenAI SDK, dropdown pilihan model Gemini, dan strategi rotasi kunci.
   - Pengaturan Ollama: Input URL endpoint Ollama, tombol uji koneksi ke server lokal, dan input nama model.
   - Parameter Lanjutan: Spinbox batch size, timeout request, max retries, delay antar request, dan folder output default.
   - Tombol "Simpan Pengaturan" yang menyinkronkan data ke objek Config dan menyimpan ke file `.env`.

2. Buat file `gui/tab_validator.py`:
   - Buat kelas TabValidator(QWidget).
   - Sediakan tombol untuk memilih file EPUB atau gunakan otomatis file EPUB hasil terjemahan terakhir.
   - Jalankan EPUBValidator(epub_path).validate() dan tampilkan status struktur dokumen (Mimetype, container XML, OPF package, XHTML parsing, dan Calibre ebook-validate jika terpasang) dalam bentuk kartu laporan berstatus hijau/merah.

3. Pasang kedua tab ini ke dalam `gui/main_window.py`:
   - Tab 4: TabSettings.
   - Tab 5: TabValidator.
   - Integrasikan Config dari TabSettings agar digunakan sebagai konfigurasi aktif saat proses terjemahan di Tab 1 dijalankan.

4. Buat file pengujian `tests/test_settings_validator.py` untuk menguji penyimpanan konfigurasi dan rendering hasil validasi.

Pastikan seluruh test suite pytest (termasuk tes lama dan baru) berjalan 100% hijau.
```

---

## 📌 SESI 6: Packaging Windows Executable (.exe) & Installer

### 1. Tujuan
Menyusun seluruh skrip otomasi packaging untuk mendistribusikan aplikasi sebagai file executable Windows standalone (`EPUBTranslator.exe`) tanpa jendela hitam CMD console, membuat skrip installer Inno Setup, dan menyiapkan GitHub Actions workflow agar pengguna dapat mengompilasi `.exe` langsung dari GitHub.

### 2. File yang Dikerjakan
- **[NEW] `EPUBTranslator.spec`**:
  - File spesifikasi PyInstaller untuk Windows:
    - Mode `windowed` / `noconsole` (GUI murni tanpa layar hitam terminal).
    - Menangani hidden imports: `google.genai`, `lxml`, `pydantic`, `certifi`, `charset_normalizer`.
    - Bundling data pendukung, icon aplikasi, dan lisensi.
- **[NEW] `build_desktop.py`**:
  - Skrip Python build otomatis:
    - Menghasilkan file ikon `.ico` dari generator ikon aset bawaan jika belum ada.
    - Menjalankan perintah PyInstaller dengan parameter lengkap.
    - Menguji integritas hasil build di folder `dist/EPUBTranslator/`.
- **[NEW] `build_windows.bat`**:
  - Skrip batch Windows satu klik (`double-click`):
    - Membuat virtual environment jika belum ada.
    - Memasang dependensi dari `requirements.txt`.
    - Menjalankan `python build_desktop.py`.
    - Menampilkan notifikasi sukses saat file `.exe` selesai dibuat.
- **[NEW] `installer.iss`**:
  - Skrip Inno Setup compiler untuk menghasilkan file instalasi Windows `EPUBTranslator-Setup.exe` lengkap dengan pembuatan shortcut di Desktop, Start Menu, dan uninstaller bersih.
- **[NEW] `.github/workflows/build-windows.yml`**:
  - GitHub Actions Workflow di environment `windows-latest` yang otomatis melakukan kompilasi executable Windows dan mengunggah artifact atau release setiap kali push tag baru.
- **[MODIFY] `README.md`**:
  - Tambahkan dokumentasi cara menjalankan Desktop App via Python dan cara mem-build file `.exe` untuk Windows.

### 3. Perintah Verifikasi
```bash
.venv/bin/python build_desktop.py --dry-run
.venv/bin/pytest tests/ -v
```

---

### 📋 PROMPT UNTUK MEMULAI SESI 6
*(Salin teks di bawah ini dan kirimkan ke AI)*

```text
Halo! Kita akan mengerjakan SESI 6 dari implementasi aplikasi desktop EPUB Translator: "Packaging Windows Executable (.exe) & Installer".

Prasyarat: Sesi 1 sampai Sesi 5 telah selesai dan seluruh fitur GUI telah berfungsi.

Tugas utama di sesi ini:
1. Buat file `EPUBTranslator.spec`:
   - Konfigurasikan PyInstaller spec file untuk platform Windows.
   - Atur console=False (noconsole) agar tidak memunculkan jendela CMD hitam.
   - Sertakan hidden imports penting seperti `google.genai`, `lxml`, `lxml.etree`, `pydantic`, `certifi`, `charset_normalizer`, `PySide6`.
   - Konfigurasikan penamaan output sebagai `EPUBTranslator.exe`.

2. Buat skrip Python otomasi `build_desktop.py`:
   - Skrip ini otomatis mengecek dependensi PyInstaller, menghasilkan file `app_icon.ico` dari generator aset bawaan, lalu menjalankan PyInstaller menggunakan file spec.
   - Sediakan argumen `--dry-run` untuk memverifikasi kesiapan spec dan konfigurasi tanpa harus melakukan kompilasi penuh.

3. Buat skrip batch Windows satu-klik `build_windows.bat`:
   - Skrip praktis bagi pengguna Windows: memeriksa Python, mengaktifkan venv, menginstal dependensi, dan menjalankan build.

4. Buat skrip Inno Setup `installer.iss`:
   - Siapkan konfigurasi Inno Setup untuk membuat wizard instalasi `EPUBTranslator-Setup.exe` dengan icon, shortcut Desktop, dan Start Menu.

5. Buat GitHub Actions workflow `.github/workflows/build-windows.yml`:
   - Menjalankan build di runner `windows-latest`, mengompilasi `EPUBTranslator.exe`, dan mempublikasikannya sebagai build artifact/release.

6. Perbarui `README.md` dengan instruksi menjalankan aplikasi desktop (`python desktop_app.py`) dan panduan membuat file `.exe` Windows.

Jalankan pengujian seluruh test suite untuk memastikan semua fungsi tetap bekerja sempurna.
```

---

## 🚀 Ringkasan Cara Penggunaan
Ketika Anda ingin memulai pengerjaan:
1. Mulai dari **Sesi 1**. Salin blok prompt yang ada pada bagian `PROMPT UNTUK MEMULAI SESI 1`.
2. Kirimkan prompt tersebut ke AI.
3. Setelah Sesi 1 selesai dan diverifikasi, lanjutkan ke **Sesi 2** dengan menyalin prompt Sesi 2, begitu seterusnya hingga **Sesi 6**.


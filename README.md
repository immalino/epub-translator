# EPUB Translator (Calibre + Google Gemini API)

Aplikasi Command-Line Interface (CLI) Python berstandar penerbitan untuk menerjemahkan buku digital EPUB dari bahasa Inggris ke bahasa Indonesia menggunakan official SDK `google-genai`.

Dirancang khusus untuk menghasilkan terjemahan sastra/novel yang mengalir alami (*natural & literary Indonesian*), menjaga 100% integritas struktur dokumen EPUB, mendukung rotasi multi-API key dengan fallback otomatis jika kuota limit, tahan gangguan jaringan berkat sistem checkpoint & resume, serta kompatibel penuh dengan perangkat e-reader seperti **XTEINK X4 Pro** yang menjalankan **CrossInk** atau **CrossPoint**.

---

## 🌟 Fitur Utama

- **Penerjemahan Gaya Novel Sastra Alami**: Menggunakan prompt penerjemah sastra profesional untuk menghindari terjemahan kaku kata-demi-kata (*translationese*). Menjaga ritme dialog, emosi, dan sudut pandang karakter.
- **Preservasi Format Inline HTML Terstruktur**: Menjaga tag `<em>`, `<strong>`, `<a>`, `<span>`, `<i>`, `<b>`, serta atribut aslinya (`href`, `class`) membungkus kata padanan di bahasa Indonesia secara presisi menggunakan parser `lxml`.
- **Rotasi Multi API Key & Fallback Kuota (429)**:
  - Dukungan memasukkan banyak API key sekaligus via file `.env` atau opsi `--api-keys`.
  - Rotasi round-robin untuk mendistribusikan beban kuota.
  - Jika salah satu kunci terkena rate limit (HTTP 429), aplikasi otomatis menandai kunci tersebut dalam masa *cooldown* dan seketika beralih ke kunci cadangan (*fallback*).
- **Proteksi Struktur EPUB Standar**:
  - `mimetype` selalu berada di offset 0 arsip ZIP tanpa kompresi (`ZIP_STORED`), sesuai spesifikasi IDPF/W3C.
  - Memperbarui `<dc:language>id</dc:language>` tanpa mengubah identitas unik dokumen.
  - Menjaga stylesheet asli, cover, gambar, hyperlink internal, dan urutan bacaan spine.
- **Tahan Gangguan (Resilient Checkpoint & Recovery)**:
  - Menyimpan progres per batch terjemahan secara berkala menggunakan hash konten sumber.
  - Flag `--resume` untuk melanjutkan proses yang terhenti tanpa membayar ulang token API untuk bab yang sudah selesai.
  - Flag `--retry-failed` untuk mencoba ulang hanya batch yang gagal.
- **Validasi Ganda (Built-in + Calibre)**:
  - Built-in validator memeriksa validitas arsip ZIP, struktur OPF, integritas link, dan sintaks XML/XHTML.
  - Terintegrasi otomatis dengan Calibre CLI (`ebook-validate`) jika terpasang di sistem host.
- **Kompatibilitas XTEINK X4 Pro**:
  - Tanpa JavaScript, font eksternal, atau dependensi jaringan yang dapat membebani engine e-ink CrossInk / CrossPoint.
  - Struktur navigasi bab (NCX & Nav XHTML) tersinkronisasi.
- **Estimasi Biaya (--dry-run)**:
  - Memperkirakan total kata, karakter, token teks, dan jumlah panggilan API sebelum eksekusi sungguhan.

---

## 📁 Struktur Proyek

```text
epub-translator/
├── epub_translate.py      # Entry point CLI utama
├── config.py              # Konfigurasi, parsing multi API key, dan masking
├── translator.py          # Integrasi Gemini API, KeyManager, prompt novel, dan retries
├── text_mapper.py         # Parser XHTML lxml, preservasi inline markup & rekonsiliasi DOM
├── epub_parser.py         # Pembaca container.xml, OPF package, spine, dan EPUB builder
├── glossary.py            # Pengelola glosarium istilah & nama karakter
├── checkpoint.py          # Sistem checkpoint, caching status, dan resume berbasis hash
├── validator.py           # Validasi integritas EPUB built-in & Calibre ebook-validate
├── requirements.txt       # Daftar dependensi Python
├── pytest.ini             # Konfigurasi pytest
├── .env.example           # Contoh template konfigurasi environment
└── tests/                 # Test suite otomatis komprehensif
    ├── create_fixture.py  # Generator EPUB fixture uji coba
    ├── fixtures/          # File EPUB sampel & contoh glosarium
    ├── test_config.py
    ├── test_glossary.py
    ├── test_checkpoint.py
    ├── test_text_mapper.py
    ├── test_epub_parser.py
    ├── test_translator.py
    ├── test_validator.py
    └── test_integration.py
```

---

## 🚀 Instalasi & Persiapan

### 1. Kebutuhan Sistem
- Python 3.11 atau lebih baru (direkomendasikan Python 3.12+)
- Calibre CLI (opsional, untuk validasi tambahan via `ebook-validate`)

### 2. Pasang Dependensi
Buat virtual environment dan pasang dependensi:
```bash
# Menggunakan venv standar
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Atau menggunakan uv (sangat cepat)
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 3. Konfigurasi API Key Gemini
Salin file `.env.example` menjadi `.env`:
```bash
cp .env.example .env
```
Buka `.env` dan masukkan API key Anda. Anda dapat memasukkan **satu kunci** atau **beberapa kunci sekaligus**:
```dotenv
# Contoh satu kunci:
GEMINI_API_KEY=AIzaSyD-YourMainKeyHere

# Atau beberapa kunci untuk rotasi & fallback otomatis (dipisahkan koma atau spasi):
GEMINI_API_KEYS="AIzaSyKey1, AIzaSyKey2, AIzaSyKey3"

# Model Gemini (default: gemini-2.5-flash)
GEMINI_MODEL=gemini-2.5-flash
```

> **Catatan Keamanan**: API key Anda tidak akan pernah ditampilkan secara lengkap di terminal atau file log. Aplikasi menerapkan fungsi *masking* otomatis (misal: `AIza...4xK9`).

---

## 📖 Panduan Penggunaan CLI

### 1. Terjemahkan Seluruh Buku
```bash
python epub_translate.py input_novel.epub -o novel_terjemahan_id.epub
```

### 2. Estimasi Biaya & Token Terlebih Dahulu (--dry-run)
Gunakan `--dry-run` untuk melihat statistik kata, token, dan jumlah batch tanpa menggunakan kuota API:
```bash
python epub_translate.py input_novel.epub --dry-run
```

### 3. Terjemahkan Bab Tertentu Saja
Gunakan `--chapter` untuk menghemat kuota atau menguji bab tertentu:
```bash
# Bab 1 saja
python epub_translate.py input_novel.epub -o output.epub --chapter 1

# Rentang Bab 1 sampai 3
python epub_translate.py input_novel.epub -o output.epub --chapter 1-3

# Beberapa bab tertentu
python epub_translate.py input_novel.epub -o output.epub --chapter 1,3,5

# Berdasarkan nama file di dalam EPUB
python epub_translate.py input_novel.epub -o output.epub --chapter chap01.xhtml
```

### 4. Menggunakan Glosarium Istilah & Nama Karakter
Buat file `glossary.json` (lihat contoh di `tests/fixtures/glossary.json`):
```json
{
  "terms": {
    "Mr. Thomas Finch": "Tuan Thomas Finch",
    "wooden chest": "peti kayu kuno",
    "Forgotten Kingdom": "Kerajaan yang Terlupakan"
  },
  "notes": "Gunakan gaya bahasa novel misteri klasik. Pertahankan sapaan 'Sir' sebagai 'Tuan'."
}
```
Jalankan perintah dengan opsi `--glossary`:
```bash
python epub_translate.py input_novel.epub -o output.epub --glossary glossary.json
```

### 5. Memberikan Multi API Key via CLI
Anda juga dapat meneruskan daftar API key langsung dari command line:
```bash
python epub_translate.py input.epub -o output.epub --api-keys AIzaSyKey1 AIzaSyKey2 AIzaSyKey3
```

### 6. Melanjutkan Proses yang Terhenti (--resume)
Jika laptop mati, koneksi terputus, atau proses dihentikan:
```bash
python epub_translate.py input_novel.epub -o output.epub --resume
```
Aplikasi akan mendeteksi checkpoint di `.epub_translate_cache/` dan langsung melanjutkan dari bab/batch terakhir yang belum selesai.

### 7. Mencoba Ulang Bagian yang Gagal (--retry-failed)
Jika ada batch yang mengalami error atau ditolak oleh filter API:
```bash
python epub_translate.py input_novel.epub -o output.epub --retry-failed
```

### 8. Menerjemahkan Metadata Buku
Untuk menerjemahkan judul buku dan deskripsi sinopsis pada file metadata OPF:
```bash
python epub_translate.py input_novel.epub -o output.epub --translate-metadata
```

### 9. Memvalidasi File EPUB
Jalankan validasi spesifikasi EPUB pada file hasil:
```bash
python epub_translate.py hasil_novel_id.epub --validate
```

---

## 📱 Panduan Kompatibilitas XTEINK X4 Pro (CrossInk / CrossPoint)

Perangkat e-ink XTEINK X4 Pro menggunakan layar monokrom hemat daya dengan engine rendering e-reader yang ringkas. Aplikasi ini menjamin kompatibilitas penuh dengan cara:

1. **Struktur Murni Tanpa Bloat**: Tidak menyisipkan JavaScript, analitik, atau stylesheet eksternal yang membebani memori e-reader.
2. **Preservasi Tipografi Asli**: Mempertahankan tag dialog miring (`<em>`), cetak tebal (`<strong>`), pemisah adegan (`* * *`), dan perataan paragraf yang nyaman dibaca pada layar Eink.
3. **Pemberian Karakter Sastra Bersih**: Tanda kutip ganda/tunggal sastra (`“...”`, `‘...’`) dan tanda pisah em-dash (`—`) diproses dengan pengkodean UTF-8 standar yang didukung font bawaan CrossInk.
4. **Navigasi Bab Utuh**: Sinkronisasi ganda pada TOC klasik (NCX) dan EPUB 3 Navigation Document agar tombol fisik lompat bab pada XTEINK berfungsi sempurna.

---

## 🧪 Pengujian Otomatis (Unit & Integration Tests)

Proyek ini dilengkapi test suite komprehensif menggunakan `pytest` dengan mock API resmi (sehingga pengujian dapat dijalankan kapan saja tanpa menggunakan kuota API nyata):

```bash
# Menjalankan seluruh 21 unit & integration tests
pytest -v
```

Hasil pengujian mencakup:
- Ekstraksi segmen dan preservasi tag inline HTML.
- Perbaikan otomatis entitas XML dan pemulihan tag tidak tertutup.
- Pembacaan OPF, manifest, filter bab, dan perakitan file ZIP standar.
- Rotasi multi API key, deteksi limit 429, dan fallback otomatis.
- Penyimpanan checkpoint, verifikasi hash SHA-256, dan resume batch.
- Validasi kepatuhan spesifikasi EPUB (mimetype, XML well-formedness, asset links).
- Pengujian pipeline *end-to-end* CLI pada fixture buku novel 3 bab.

---

## 🛠️ Troubleshooting & FAQ

- **Q: Apakah kuota gratis Gemini API (Free Tier) cukup untuk menerjemahkan satu novel?**
  - **A**: Free Tier memiliki batas RPM (Requests Per Minute) dan RPD (Requests Per Day). Fitur rotasi multi API key pada aplikasi ini memungkinkan Anda memasukkan beberapa key dari project Google Cloud berbeda untuk melipatgandakan batas RPM harian secara bergantian.
- **Q: Bagaimana jika Calibre belum terpasang di komputer saya?**
  - **A**: Tidak masalah! Aplikasi menyertakan Built-in EPUB Validator yang memverifikasi kepatuhan ZIP, spesifikasi `mimetype`, dan well-formedness dokumen XML/XHTML. Jika Anda memasang Calibre (`sudo apt install calibre`), aplikasi akan otomatis memanfaatkan `ebook-validate` untuk validasi tambahan.
- **Q: Apakah file EPUB asli saya aman?**
  - **A**: Ya, 100% aman. EPUB sumber hanya dibaca dalam mode *read-only*. Hasil terjemahan selalu disimpan pada file baru yang ditentukan melalui opsi `-o`.


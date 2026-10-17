"""Streamlit Web UI for EPUB Translator.

Features:
- Responsive web dashboard accessible from PC, smartphone, or tablet
- Drag & Drop EPUB file upload and auto-detection of books in input/ folder
- Visual metadata preview (Cover, Title, Author, Spine Chapters)
- Provider selection (Google Gemini multi-key rotation or Ollama Local)
- Interactive chapter selection (All or specific chapters)
- Dry Run quota & token estimation before translating
- Real-time dual progress bars (Total book & Current chapter batches)
- Live scrolling logs & quota limit alerts
- Bilingual side-by-side text preview per chapter (Source vs Translation)
- Visual Glossary editor (JSON download & terms management)
- Built-in & Calibre EPUB validation viewer
"""

from __future__ import annotations

import io
import json
import logging
import os
import posixpath
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
from PIL import Image

from config import Config
from glossary import Glossary
from checkpoint import CheckpointManager
from runner import TranslationRunner, TranslationCallback
from validator import EPUBValidator

# Page Configuration
st.set_page_config(
    page_title="EPUB Translator",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_lan_ip() -> str:
    """Get the primary local network IP for multi-device access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# Initialize Session State
if "logs" not in st.session_state:
    st.session_state.logs = []
if "current_epub" not in st.session_state:
    st.session_state.current_epub = None
if "epub_info" not in st.session_state:
    st.session_state.epub_info = None
if "last_output_epub" not in st.session_state:
    st.session_state.last_output_epub = None
if "dry_run_data" not in st.session_state:
    st.session_state.dry_run_data = None


# Custom Streamlit Callback
class StreamlitCallback(TranslationCallback):
    def __init__(self, overall_bar, overall_text, batch_bar, batch_text, log_area):
        self.overall_bar = overall_bar
        self.overall_text = overall_text
        self.batch_bar = batch_bar
        self.batch_text = batch_text
        self.log_area = log_area
        self.total_chapters = 1
        self.completed_chapters = 0

    def on_log(self, level: str, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"
        st.session_state.logs.append(log_line)
        if len(st.session_state.logs) > 300:
            st.session_state.logs = st.session_state.logs[-300:]
        self.log_area.text("\n".join(st.session_state.logs[-15:]))

    def on_start(self, total_chapters: int, total_chars: int, total_segments: int, target_spine: list) -> None:
        self.total_chapters = max(1, total_chapters)
        self.completed_chapters = 0
        self.overall_bar.progress(0.0)
        self.overall_text.write(f"📊 Total Bab: {self.total_chapters} bab | {total_segments:,} segmen | {total_chars:,} karakter")

    def on_chapter_start(self, chapter_idx: int, chapter_title: str, total_batches: int) -> None:
        self.batch_bar.progress(0.0)
        self.batch_text.write(f"📖 Sedang memproses {chapter_title} (Total {total_batches} batch)...")

    def on_batch_complete(self, chapter_idx: int, batch_idx: int, total_batches: int, translated_count: int, is_cache: bool = False) -> None:
        pct = min(1.0, float(batch_idx) / max(1, total_batches))
        self.batch_bar.progress(pct)
        status = " (dari cache)" if is_cache else ""
        self.batch_text.write(f"⚡ Batch {batch_idx}/{total_batches}{status} ({translated_count} segmen)")

    def on_chapter_complete(self, chapter_idx: int, chapter_title: str) -> None:
        self.completed_chapters += 1
        overall_pct = min(1.0, float(self.completed_chapters) / self.total_chapters)
        self.overall_bar.progress(overall_pct)
        self.overall_text.write(f"✅ Selesai: {self.completed_chapters}/{self.total_chapters} bab ({int(overall_pct*100)}%)")

    def on_chapter_failed(self, chapter_idx: int, chapter_title: str, error_message: str) -> None:
        self.on_log("ERROR", f"Bab {chapter_title} gagal: {error_message}")

    def on_quota_warning(self, error, checkpoint) -> None:
        self.on_log("ERROR", "Batas kuota Gemini harian tercapai! Progres tersimpan aman di disk.")


# ==========================================
# SIDEBAR: Configuration & Multi-Device Info
# ==========================================
with st.sidebar:
    st.title("⚙️ Pengaturan")

    # Multi-Device Network Access Card
    lan_ip = get_lan_ip()
    st.info(
        f"📱 **Akses Multi-Device (Wi-Fi)**\n\n"
        f"- **Localhost:** `http://localhost:8501`\n"
        f"- **HP/Tablet:** `http://{lan_ip}:8501`\n\n"
        f"*(Buka dari smartphone yang terhubung ke Wi-Fi yang sama)*"
    )

    st.subheader("🤖 Model & Provider")
    provider = st.radio(
        "Pilih Mesin Translasi:",
        ["gemini", "ollama"],
        index=0,
        format_func=lambda x: "✨ Google Gemini API" if x == "gemini" else "🦙 Ollama (Lokal)",
    )

    default_config = Config.from_env()

    if provider == "gemini":
        model_options = ["gemini-3.5-flash-lite", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro", "Custom"]
        selected_model = st.selectbox("Pilihan Model:", model_options, index=0)
        if selected_model == "Custom":
            model = st.text_input("Nama Model Gemini Kustom:", value="gemini-2.5-flash")
        else:
            model = selected_model

        st.caption(f"Kunci dari `.env`: {default_config.masked_keys_summary()}")
        extra_keys = st.text_area(
            "API Keys Tambahan (pisahkan koma jika banyak):",
            placeholder="AIzaSy..., AIzaSy...",
            help="Masukkan satu atau beberapa API key Gemini untuk rotasi otomatis & fallback jika limit.",
        )
        api_keys_list = [k.strip() for k in extra_keys.split(",") if k.strip()] if extra_keys else default_config.api_keys

        rotate_strategy = st.selectbox(
            "Strategi Rotasi Kunci:",
            ["round_robin", "fallback_on_limit"],
            format_func=lambda x: "Round Robin (Bagi Rata)" if x == "round_robin" else "Fallback Saat Limit (429)",
        )
        ollama_url = "http://localhost:11434"
    else:
        model = st.text_input("Nama Model Ollama:", value="translategemma:4b")
        ollama_url = st.text_input("Ollama Endpoint URL:", value="http://localhost:11434")
        api_keys_list = []
        rotate_strategy = "round_robin"

    st.subheader("🎨 Gaya Bahasa & Bahasa")
    col_l1, col_l2 = st.columns(2)
    with col_l1:
        source_lang = st.text_input("Bahasa Asli:", value="en")
    with col_l2:
        target_lang = st.text_input("Bahasa Target:", value="id")

    style_options = {
        "natural": "Sastra Alami (Natural Literary Novel)",
        "formal": "Formal / Baku",
        "casual": "Santai / Populer",
    }
    style = st.selectbox(
        "Gaya Terjemahan:",
        list(style_options.keys()),
        format_func=lambda x: style_options[x],
    )

    with st.expander("🛠️ Pengaturan Lanjutan"):
        batch_size = st.number_input(
            "Jumlah Paragraf per Batch:",
            min_value=1,
            max_value=50,
            value=10 if provider == "gemini" else 15,
        )
        max_retries = st.number_input("Maksimum Percobaan Retry:", min_value=1, max_value=10, value=5)
        timeout = st.number_input("Request Timeout (detik):", min_value=10.0, max_value=300.0, value=60.0)


# ==========================================
# MAIN CONTENT TABS
# ==========================================
tab_translate, tab_preview, tab_glossary, tab_validator = st.tabs([
    "📚 Penerjemahan & Progres",
    "👁️ Preview Bilingual Per Bab",
    "📖 Glosarium Istilah",
    "🛠️ Validasi EPUB",
])


# ------------------------------------------
# TAB 1: Translation & Progress
# ------------------------------------------
with tab_translate:
    st.header("Penerjemah Novel EPUB")
    st.write("Terjemahkan novel EPUB dengan gaya bahasa mengalir alami, menjaga 100% struktur dokumen, dan kompatibel untuk e-reader.")

    # EPUB Selection
    source_mode = st.radio(
        "Sumber Berkas EPUB:",
        ["Upload File EPUB Baru", "Pilih dari Folder input/"],
        horizontal=True,
    )

    selected_epub_path: Optional[Path] = None

    if source_mode == "Upload File EPUB Baru":
        uploaded_file = st.file_uploader("Unggah Berkas EPUB:", type=["epub"])
        if uploaded_file:
            save_path = INPUT_DIR / uploaded_file.name
            with open(save_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            selected_epub_path = save_path
    else:
        existing_epubs = sorted(list(INPUT_DIR.glob("*.epub")))
        if existing_epubs:
            choice = st.selectbox(
                "Pilih EPUB dari folder input/:",
                existing_epubs,
                format_func=lambda p: p.name,
            )
            selected_epub_path = choice
        else:
            st.warning("Folder `input/` belum berisi file `.epub`. Silakan letakkan file atau gunakan opsi upload.")

    # Fallback to session state if available
    if not selected_epub_path and st.session_state.get("current_epub"):
        if Path(st.session_state.current_epub).is_file():
            selected_epub_path = Path(st.session_state.current_epub)

    # Inspect and Display Book Info
    if selected_epub_path and selected_epub_path.is_file():
        st.session_state.current_epub = selected_epub_path
        try:
            info = TranslationRunner.inspect_epub(selected_epub_path)
            st.session_state.epub_info = info

            st.divider()
            c_cov, c_det = st.columns([1, 4])
            with c_cov:
                if info.get("cover_bytes"):
                    try:
                        img = Image.open(io.BytesIO(info["cover_bytes"]))
                        st.image(img, use_container_width=True, caption="Cover Buku")
                    except Exception:
                        st.info("📖 Tidak ada gambar cover")
                else:
                    st.info("📖 Tidak ada gambar cover")

            with c_det:
                st.subheader(info["title"] or selected_epub_path.stem)
                st.write(f"**Penulis / Creator:** {info.get('creator', 'Unknown')}")
                st.write(f"**Bahasa Asli:** `{info.get('language', 'en')}` | **Total Bab (Spine):** {info['spine_count']} bab")
                if info.get("description"):
                    with st.expander("Sinopsis / Deskripsi"):
                        st.write(info["description"])

            # Chapter Selection
            st.subheader("🎯 Pilih Bab yang Ingin Diterjemahkan")
            ch_mode = st.radio(
                "Lingkup Penerjemahan:",
                ["Seluruh Buku (Semua Bab)", "Pilih Bab Tertentu"],
                horizontal=True,
            )

            chapter_filter = None
            if ch_mode == "Pilih Bab Tertentu":
                ch_options = [
                    f"Bab {ch['index']} - {ch['href']} ({ch['segment_count']} segmen, ~{ch['char_count']} kar)"
                    for ch in info["chapters"]
                ]
                selected_chapters = st.multiselect(
                    "Centang bab yang akan diproses:",
                    options=range(1, len(info["chapters"]) + 1),
                    format_func=lambda i: ch_options[i - 1],
                    default=[1] if len(info["chapters"]) > 0 else [],
                )
                if selected_chapters:
                    chapter_filter = ",".join(str(idx) for idx in selected_chapters)
                else:
                    st.warning("Pilih setidaknya 1 bab untuk melanjutkan.")

            # Glossary selection
            st.subheader("📖 Glosarium (Opsional)")
            glossary_file = st.file_uploader("Unggah Glosarium JSON:", type=["json"], key="gl_upload")
            loaded_glossary = None
            if glossary_file:
                try:
                    gl_data = json.load(glossary_file)
                    loaded_glossary = Glossary.from_dict(gl_data)
                    st.success(f"Glosarium aktif: {len(loaded_glossary)} istilah")
                except Exception as e:
                    st.error(f"Format glosarium tidak valid: {e}")

            # Construct Config
            current_config = Config.from_env(
                provider=provider,
                ollama_base_url=ollama_url,
                api_keys=api_keys_list,
                model=model,
                batch_size=batch_size,
                source_lang=source_lang,
                target_lang=target_lang,
                style=style,
                rotate_strategy=rotate_strategy,
                max_retries=max_retries,
                request_timeout=timeout,
            )

            st.divider()

            # Action Buttons: Dry Run & Start Translation
            b_col1, b_col2, b_col3 = st.columns(3)
            with b_col1:
                dry_run_clicked = st.button("🔍 Hitung Estimasi (Dry Run)", use_container_width=True)
            with b_col2:
                translate_clicked = st.button("🚀 Mulai Terjemahkan", type="primary", use_container_width=True)
            with b_col3:
                resume_clicked = st.button("🔄 Lanjutkan (Resume Sesi)", use_container_width=True)

            # Dry Run execution
            if dry_run_clicked:
                with st.spinner("Menghitung estimasi token dan kuota..."):
                    stats = TranslationRunner.get_dry_run_stats(
                        selected_epub_path,
                        config=current_config,
                        chapter_filter=chapter_filter,
                        glossary=loaded_glossary,
                    )
                    st.session_state.dry_run_data = stats

            if st.session_state.dry_run_data:
                stats = st.session_state.dry_run_data
                st.info(f"📋 **Hasil Estimasi untuk {stats['target_chapters']} Bab Terpilih:**")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total Segmen", f"{stats['total_segments']:,}")
                m2.metric("Estimasi Kata", f"~{stats['approx_words']:,}")
                m3.metric("Estimasi Token", f"~{stats['approx_tokens']:,}")
                m4.metric("Total Batch API", f"{stats['batches_count']} batch")

                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"- **Batch Selesai di Cache:** `{stats['completed_batches']}` batch")
                    st.write(f"- **Batch yang Perlu Diproses:** `{stats['remaining_batches']}` batch")
                with c2:
                    if stats["provider"] == "gemini":
                        st.write(f"- **Estimasi Waktu (RPM ~15):** ~{stats['est_minutes']} menit")
                        if stats["rpd_sufficient"]:
                            st.success(f"✅ Kuota Harian (1.500 RPD) CUKUP ({stats['remaining_batches']}/1500)")
                        else:
                            st.warning(f"⚠️ Melebihi kuota 1 hari ({stats['remaining_batches']}/1500). Gunakan rotasi multi-key!")
                    else:
                        st.write(f"- **Estimasi Waktu CPU/GPU:** ~{stats['est_minutes']} menit")

            # Translation Execution
            if translate_clicked or resume_clicked:
                output_epub_name = f"{selected_epub_path.stem}_terjemahan_{target_lang}.epub"
                output_epub_path = OUTPUT_DIR / output_epub_name
                st.session_state.last_output_epub = output_epub_path

                st.subheader("⏳ Proses Penerjemahan Sedang Berjalan...")
                overall_bar = st.progress(0.0)
                overall_text = st.empty()
                batch_bar = st.progress(0.0)
                batch_text = st.empty()

                log_expander = st.expander("📜 Log Terminal Live", expanded=True)
                with log_expander:
                    log_area = st.empty()

                cb = StreamlitCallback(overall_bar, overall_text, batch_bar, batch_text, log_area)

                with st.spinner("Sedang menerjemahkan..."):
                    exit_code = TranslationRunner.run_translation(
                        input_path=selected_epub_path,
                        output_path=output_epub_path,
                        config=current_config,
                        chapter_filter=chapter_filter,
                        resume=True,
                        retry_failed=False,
                        glossary=loaded_glossary,
                        callback=cb,
                    )

                if exit_code == 0:
                    st.success(f"🎉 Penerjemahan selesai! Berkas disimpan ke `{output_epub_path}`")
                    with open(output_epub_path, "rb") as f:
                        epub_bytes = f.read()
                    st.download_button(
                        label="📥 Unduh File EPUB Hasil Terjemahan",
                        data=epub_bytes,
                        file_name=output_epub_name,
                        mime="application/epub+zip",
                        type="primary",
                        use_container_width=True,
                    )
                else:
                    st.error("Penerjemahan berhenti atau mengalami kendala. Periksa log terminal di atas.")

            # Show Download button if output file already exists
            elif st.session_state.last_output_epub and st.session_state.last_output_epub.is_file():
                st.divider()
                st.success(f"Berkas hasil terjemahan tersedia: `{st.session_state.last_output_epub.name}`")
                with open(st.session_state.last_output_epub, "rb") as f:
                    data = f.read()
                st.download_button(
                    label="📥 Unduh Berkas Terjemahan Terakhir",
                    data=data,
                    file_name=st.session_state.last_output_epub.name,
                    mime="application/epub+zip",
                    use_container_width=True,
                )

        except Exception as e:
            st.error(f"Gagal membaca berkas EPUB: {e}")


# ------------------------------------------
# TAB 2: Bilingual Side-by-Side Preview
# ------------------------------------------
with tab_preview:
    st.header("👁️ Preview Teks Bab (Bilingual)")
    st.write("Bandingkan teks asli (Bahasa Inggris) dengan hasil terjemahan (Bahasa Indonesia) per bab.")

    if st.session_state.current_epub and st.session_state.epub_info:
        info = st.session_state.epub_info
        epub_path = st.session_state.current_epub
        out_path = st.session_state.last_output_epub

        ch_list = info["chapters"]
        ch_idx = st.selectbox(
            "Pilih Bab untuk Dipratinjau:",
            range(len(ch_list)),
            format_func=lambda i: f"Bab {ch_list[i]['index']} ({ch_list[i]['href']}) - {ch_list[i]['segment_count']} segmen",
        )

        selected_zip_path = ch_list[ch_idx]["zip_path"]
        pairs = TranslationRunner.get_bilingual_preview(
            input_path=epub_path,
            chapter_zip_path=selected_zip_path,
            output_path=out_path,
            config=Config.from_env(),
        )

        translated_count = sum(1 for p in pairs if p["is_translated"])
        total_p = len(pairs)
        st.caption(f"Status Bab: {translated_count} dari {total_p} segmen sudah diterjemahkan.")

        st.divider()
        col_hdr1, col_hdr2 = st.columns(2)
        with col_hdr1:
            st.markdown("### 🇬🇧 Teks Asli (Sumber)")
        with col_hdr2:
            st.markdown("### 🇮🇩 Teks Terjemahan (Indonesia)")

        # Render each segment side-by-side
        for p in pairs:
            c_src, c_dst = st.columns(2)
            with c_src:
                st.markdown(
                    f"<div style='background-color:#f8f9fa; color:#212529; padding:12px; border-radius:8px; border-left:4px solid #007bff; margin-bottom:10px; font-size:15px; line-height:1.6;'>"
                    f"{p['source']}"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with c_dst:
                if p["translated"]:
                    st.markdown(
                        f"<div style='background-color:#f0fff4; color:#155724; padding:12px; border-radius:8px; border-left:4px solid #28a745; margin-bottom:10px; font-size:15px; line-height:1.6;'>"
                        f"{p['translated']}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<div style='background-color:#fff3cd; color:#856404; padding:12px; border-radius:8px; border-left:4px solid #ffc107; margin-bottom:10px; font-size:14px; font-style:italic;'>"
                        f"[Belum Diterjemahkan]"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
    else:
        st.info("Silakan unggah atau pilih file EPUB terlebih dahulu di Tab 1 (Penerjemahan & Progres).")


# ------------------------------------------
# TAB 3: Glossary Editor
# ------------------------------------------
with tab_glossary:
    st.header("📖 Glosarium Istilah & Nama Karakter")
    st.write("Pastikan konsistensi nama karakter, nama tempat, dan istilah khusus sepanjang buku.")

    gl_template = {
        "terms": {
            "Mr. Finch": "Tuan Finch",
            "ancient castle": "kastel kuno",
            "Forgotten Kingdom": "Kerajaan yang Terlupakan",
        },
        "notes": "Pertahankan sapaan 'Sir' sebagai 'Tuan'. Gunakan gaya bahasa novel sastra klasik.",
    }

    uploaded_gl = st.file_uploader("Muat File Glosarium (JSON):", type=["json"], key="tab_gl_upload")
    if uploaded_gl:
        try:
            gl_data = json.load(uploaded_gl)
        except Exception:
            gl_data = gl_template
    else:
        gl_data = gl_template

    terms_list = [{"Istilah Asli (Sumber)": k, "Padanan Terjemahan": v} for k, v in gl_data.get("terms", {}).items()]

    st.subheader("Daftar Istilah")
    edited_df = st.data_editor(
        terms_list,
        num_rows="dynamic",
        use_container_width=True,
        key="gl_table",
    )

    st.subheader("Catatan Konteks Gaya Bahasa")
    notes_text = st.text_area(
        "Instruksi Khusus untuk AI:",
        value=gl_data.get("notes", ""),
        help="Instruksi ini akan disisipkan ke sistem prompt agar AI memahami gaya bahasa novel Anda.",
    )

    new_terms = {row["Istilah Asli (Sumber)"]: row["Padanan Terjemahan"] for row in edited_df if row.get("Istilah Asli (Sumber)")}
    final_gl_json = json.dumps({"terms": new_terms, "notes": notes_text}, indent=2, ensure_ascii=False)

    st.download_button(
        label="💾 Unduh Glosarium (glossary.json)",
        data=final_gl_json,
        file_name="glossary.json",
        mime="application/json",
    )


# ------------------------------------------
# TAB 4: EPUB Validator
# ------------------------------------------
with tab_validator:
    st.header("🛠️ Validasi Standar EPUB")
    st.write("Periksa kepatuhan spesifikasi EPUB (struktur ZIP, manifest OPF, nav, XML well-formedness, dan Calibre ebook-validate).")

    val_target = st.file_uploader("Pilih Berkas EPUB untuk Divalidasi:", type=["epub"], key="val_upload")
    if val_target:
        temp_val_path = Path("/tmp") / val_target.name
        with open(temp_val_path, "wb") as f:
            f.write(val_target.getbuffer())

        with st.spinner("Memvalidasi file EPUB..."):
            val = EPUBValidator(temp_val_path)
            report = val.validate()

        if report.is_valid:
            st.success("✅ File EPUB 100% VALID sesuai spesifikasi IDPF/W3C!")
        else:
            st.error("❌ Ditemukan kesalahan validasi pada file EPUB.")

        st.subheader("Rincian Pemeriksaan")
        st.write(f"- **Mimetype di Offset 0 (ZIP_STORED):** {'✅ Lolos' if report.mimetype_valid else '❌ Gagal'}")
        st.write(f"- **Struktur OPF & Manifest:** {'✅ Lolos' if report.opf_valid else '❌ Gagal'}")
        st.write(f"- **Integritas Link Aset:** {'✅ Lolos' if report.links_valid else '❌ Gagal'}")
        st.write(f"- **Sintaks XML/XHTML:** {'✅ Lolos' if report.xml_well_formed else '❌ Gagal'}")
        if report.calibre_available:
            st.write(f"- **Calibre ebook-validate:** {'✅ Lolos' if report.calibre_passed else '❌ Ada Temuan'}")
        else:
            st.info("ℹ️ Calibre CLI tidak terdeteksi di sistem (pemeriksaan built-in tetap berjalan).")

        if report.errors:
            with st.expander("Daftar Kesalahan (Errors)", expanded=True):
                for err in report.errors:
                    st.error(f"- {err}")

        if report.warnings:
            with st.expander("Daftar Peringatan (Warnings)"):
                for warn in report.warnings:
                    st.warning(f"- {warn}")


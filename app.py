import streamlit as st
import requests
import time
from supabase import create_client, Client
import json

# ==========================================
# 1. INITIALIZATION & CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="VLM Evaluation Dashboard | IKR-CRM", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Memuat kredensial dari Streamlit Secrets
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    BACKEND_API_URL = st.secrets["BACKEND_API_URL"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Gagal memuat Streamlit Secrets. Pastikan Anda sudah mengonfigurasinya di dashboard Streamlit Cloud.")
    st.stop()

# Mapping tipe gambar dan deskripsinya berdasarkan aturan bisnis proyek
IMAGE_TYPE_MAPPING = {
    "FTTH (Fiber to the Home)": {
        "ikr_homepass": "Foto rumah pelanggan dari luar (fasad penuh)[cite: 85].",
        "ikr_modempass": "Foto bagian belakang/label modem ONT (Ekstraksi SN/MAC)[cite: 85].",
        "ikr_odppass": "Foto ODP tampak depan yang memperlihatkan kode ODP[cite: 85].",
        "ikr_speedtest": "Screenshot hasil speedtest dengan nama ISP terlihat[cite: 85].",
        "opm_redaman": "Foto display alat ukur Optical Power Meter (Kritis: >= -21 dBm)[cite: 85].",
        "ont_redaman": "Foto hasil pengukuran redaman optik langsung dari sistem perangkat[cite: 85]."
    },
    "FWA (Fixed Wireless Access)": {
        "receiver_link": "Foto penerima bersama paket atau produk yang diterima[cite: 85].",
        "modem_back_link": "Foto label package FWA untuk ekstraksi IMEI/ICCID[cite: 85].",
        "house_link": "Foto rumah FWA dari luar untuk identifikasi lokasi gedung[cite: 85]."
    }
}

# ==========================================
# 2. UI SIDEBAR: CONFIGURATION
# ==========================================
st.sidebar.image("https://supabase.com/common/assets/images/design-system/supabase-logo-icon.png", width=60)
st.sidebar.title("VLM Evaluation Panel")
st.sidebar.markdown("---")

st.sidebar.subheader("1. Pilih Model VLM")
selected_model = st.sidebar.radio(
    "Model yang aktif di GPU A30:",
    ("Qwen2.5-VL-7B-Instruct", "InternVL3-8B"),
    help="Backend akan melakukan swap VRAM otomatis jika Anda mengganti model[cite: 29, 46, 96]."
)

st.sidebar.subheader("2. Kategori Teknologi")
tech_category = st.sidebar.selectbox("Pilih Teknologi:", list(IMAGE_TYPE_MAPPING.keys()))

st.sidebar.subheader("3. Tipe Gambar Validasi")
available_types = IMAGE_TYPE_MAPPING[tech_category]
selected_type = st.sidebar.selectbox(
    "Pilih Image Type:", 
    list(available_types.keys()),
    format_func=lambda x: f"{x}"
)

# Tampilkan deskripsi aturan bisnis di sidebar
st.sidebar.info(f"**Deskripsi Tipe:** {available_types[selected_type]}")

# ==========================================
# 3. MAIN CONTENT AREA
# ==========================================
st.header("📸 Pipeline Validasi Otomatis Gambar")
st.markdown("Unggah foto lapangan untuk membandingkan performa ekstraksi terstruktur model VLM lokal.")

# Layout kolom untuk upload dan preview
col_upload, col_result = st.columns([1, 1])

with col_upload:
    st.subheader("Input Aset Gambar")
    uploaded_file = st.file_uploader(
        "Seret dan lepas file gambar ke sini...", 
        type=["jpg", "jpeg", "png"],
        help="Gambar akan diunggah otomatis ke Supabase Storage Bucket."
    )
    
    if uploaded_file:
        st.image(uploaded_file, caption="Pratinjau Gambar Utama", use_container_width=True)

with col_result:
    st.subheader("Output Hasil Analisis VLM")
    
    if not uploaded_file:
        st.warning("Silakan unggah gambar di sebelah kiri untuk memulai pengujian.")
    else:
        # Tombol Eksekusi
        if st.button("🚀 Jalankan Ekstraksi & Validasi", type="primary", use_container_width=True):
            
            with st.status("Menjalankan pipeline validasi...", expanded=True) as status:
                
                # --- LANGKAH 1: Unggah ke Supabase Storage ---
                status.write("📤 Mengunggah gambar ke Supabase Storage...")
                file_bytes = uploaded_file.getvalue()
                # Berikan nama unik menggunakan timestamp agar tidak menimpa file lama
                unique_filename = f"{int(time.time())}_{uploaded_file.name}"
                
                try:
                    supabase.storage.from_("vlm-eval-images").upload(unique_filename, file_bytes)
                    public_url = supabase.storage.from_("vlm-eval-images").get_public_url(unique_filename)
                except Exception as storage_err:
                    status.update(label="Gagal mengunggah gambar ke Storage!", state="error")
                    st.error(f"Detail Error Storage: {storage_err}")
                    st.stop()
                
                # --- LANGKAH 2: Kirim Payload ke FastAPI Server GPU ---
                status.write(f"🤖 Mengirim perintah ke Server GPU A30 ({selected_model})...")
                start_time = time.time()
                
                payload = {
                    "image_url": public_url,
                    "image_type": selected_type,
                    "model_name": selected_model
                }
                
                try:
                    # Timeout disetel agak panjang (150 detik) jika terjadi pemuatan model pertama kali ke VRAM
                    response = requests.post(BACKEND_API_URL, json=payload, timeout=150)
                    response.raise_for_status()
                    
                    backend_response = response.json()
                    execution_time = round(time.time() - start_time, 2)
                    
                    # --- LANGKAH 3: Simpan Data Log ke Postgres ---
                    status.write("💾 Mencatat log evaluasi ke database Supabase...")
                    
                    # Coba parsing output teks dari model menjadi objek JSON murni jika memungkinkan
                    try:
                        raw_txt = backend_response.get("raw_output", "{}")
                        # Bersihkan markdown formatting ```json ... ``` jika model mengembalikannya
                        if "```json" in raw_txt:
                            raw_txt = raw_txt.split("```json")[1].split("```")[0].strip()
                        elif "```" in raw_txt:
                            raw_txt = raw_txt.split("```")[1].split("```")[0].strip()
                        
                        parsed_json = json.loads(raw_txt)
                    except Exception:
                        # Jika gagal parsing, simpan string mentah di dalam objek JSON
                        parsed_json = {"error_parsing_string": backend_response.get("raw_output")}
                    
                    supabase.table("evaluation_logs").insert({
                        "image_url": public_url,
                        "image_type": selected_type,
                        "model_used": selected_model,
                        "execution_time_seconds": execution_time,
                        "extracted_data": parsed_json
                    }).execute()
                    
                    # Pembaruan Status Sukses
                    status.update(label=f"Selesai diproses dalam {execution_time} detik!", state="complete", expanded=False)
                    
                    # Tampilkan metrik kecepatan eksekusi
                    st.metric(label="Waktu Inferensi", value=f"{execution_time} Detik")
                    
                    st.success(f"Analisis sukses menggunakan {selected_model}:")
                    st.json(parsed_json)
                    
                except requests.exceptions.RequestException as api_err:
                    status.update(label="Gagal terhubung dengan Server GPU!", state="error")
                    st.error(f"Gagal memproses gambar. Pastikan Cloudflare Tunnel Anda aktif di server. \n\n**Detail Error:** {api_err}")
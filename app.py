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

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    # Load 2 URL Tunnel Cloudflare yang berbeda
    BACKEND_API_URL_QWEN = st.secrets["BACKEND_API_URL_QWEN"]
    BACKEND_API_URL_INTERN = st.secrets["BACKEND_API_URL_INTERN"]
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"Gagal memuat Streamlit Secrets. Pastikan nama variabel benar. Error: {e}")
    st.stop()

IMAGE_TYPE_MAPPING = {
    "FTTH (Fiber to the Home)": {
        "ikr_homepass": "Foto rumah pelanggan dari luar (fasad penuh).",
        "ikr_modempass": "Foto bagian belakang/label modem ONT (Ekstraksi SN/MAC).",
        "ikr_odppass": "Foto ODP tampak depan yang memperlihatkan kode ODP.",
        "ikr_speedtest": "Screenshot hasil speedtest dengan nama ISP terlihat.",
        "opm_redaman": "Foto display alat ukur Optical Power Meter (Kritis: >= -21 dBm).",
        "ont_redaman": "Foto hasil pengukuran redaman optik langsung dari sistem perangkat."
    },
    "FWA (Fixed Wireless Access)": {
        "receiver_link": "Foto penerima bersama paket atau produk yang diterima.",
        "modem_back_link": "Foto label package FWA untuk ekstraksi IMEI/ICCID.",
        "house_link": "Foto rumah FWA dari luar untuk identifikasi lokasi gedung."
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
    ("Qwen2.5-VL-7B-Instruct", "InternVL3-8B")
)

st.sidebar.subheader("2. Kategori Teknologi")
tech_category = st.sidebar.selectbox("Pilih Teknologi:", list(IMAGE_TYPE_MAPPING.keys()))

st.sidebar.subheader("3. Tipe Gambar Validasi")
available_types = IMAGE_TYPE_MAPPING[tech_category]
selected_type = st.sidebar.selectbox(
    "Pilih Image Type:", 
    list(available_types.keys())
)

st.sidebar.info(f"**Deskripsi:** {available_types[selected_type]}")

# ==========================================
# 3. MAIN CONTENT AREA (TABS)
# ==========================================
st.header("📸 Pipeline Validasi Otomatis Gambar")

tab_validate, tab_history = st.tabs(["🔍 Validasi Baru", "📜 Riwayat Pengecekan"])

# ------------------------------------------
# TAB 1: VALIDASI BARU
# ------------------------------------------
with tab_validate:
    st.markdown("Unggah foto lapangan untuk membandingkan performa ekstraksi terstruktur model VLM lokal.")
    col_upload, col_result = st.columns([1, 1])
    
    with col_upload:
        st.subheader("Input Aset Gambar")
        uploaded_file = st.file_uploader("Seret dan lepas file gambar ke sini...", type=["jpg", "jpeg", "png", "webp"])
        
        if uploaded_file:
            st.image(uploaded_file, caption="Pratinjau Gambar Utama", use_container_width=True)
            
    with col_result:
        st.subheader("Output Hasil Analisis VLM")
        
        if not uploaded_file:
            st.warning("Silakan unggah gambar di sebelah kiri untuk memulai pengujian.")
        else:
            if st.button("🚀 Jalankan Ekstraksi & Validasi", type="primary", use_container_width=True):
                with st.status("Menjalankan pipeline validasi...", expanded=True) as status:
                    
                    # 1. Upload ke Supabase
                    status.write("📤 Mengunggah gambar...")
                    file_bytes = uploaded_file.getvalue()
                    unique_filename = f"{int(time.time())}_{uploaded_file.name}"
                    
                    try:
                        supabase.storage.from_("vlm-eval-images").upload(unique_filename, file_bytes)
                        public_url = supabase.storage.from_("vlm-eval-images").get_public_url(unique_filename)
                    except Exception as err:
                        status.update(label="Gagal mengunggah gambar!", state="error")
                        st.error(err)
                        st.stop()
                    
                    # 2. Hit Backend API (ROUTER CERDAS)
                    status.write(f"🤖 Mengirim ke Orkestrator ({selected_model})...")
                    start_time = time.time()
                    payload = {"image_url": public_url, "image_type": selected_type, "model_name": selected_model}
                    
                    if "Qwen" in selected_model:
                        target_url = st.secrets.get("BACKEND_API_URL_QWEN", BACKEND_API_URL_QWEN)
                    else:
                        target_url = st.secrets.get("BACKEND_API_URL_INTERN", BACKEND_API_URL_INTERN)
                    
                    try:
                        response = requests.post(target_url, json=payload, timeout=150)
                        
                        # Tangkap Error Backend (OOM/Typo di Server GPU)
                        if response.status_code == 500:
                            err_data = response.json()
                            status.update(label="Terjadi Error di Server GPU!", state="error")
                            st.error("💥 Backend Error Traceback:")
                            st.code(err_data.get("traceback", "No traceback provided."))
                            st.stop()
                            
                        response.raise_for_status()
                        backend_response = response.json()
                        
                        # INI DIA VARIABEL YANG HILANG TADI:
                        execution_time = round(time.time() - start_time, 2)
                        
                        # 3. Parsing JSON & Save to DB
                        status.write("💾 Menyimpan ke database...")
                        try:
                            raw_txt = backend_response.get("raw_output", "{}")
                            if "```json" in raw_txt:
                                raw_txt = raw_txt.split("```json")[1].split("```")[0].strip()
                            elif "```" in raw_txt:
                                raw_txt = raw_txt.split("```")[1].split("```")[0].strip()
                            parsed_json = json.loads(raw_txt)
                        except Exception:
                            parsed_json = {"error_parsing_string": backend_response.get("raw_output")}
                        
                        supabase.table("evaluation_logs").insert({
                            "image_url": public_url,
                            "image_type": selected_type,
                            "model_used": selected_model,
                            "execution_time_seconds": execution_time,
                            "extracted_data": parsed_json
                        }).execute()
                        
                        status.update(label=f"Selesai dalam {execution_time} detik!", state="complete", expanded=False)
                        
                        st.metric(label="Waktu Inferensi + Loading Model", value=f"{execution_time} Detik")
                        st.success("Tersimpan di Riwayat Pengecekan!")
                        st.json(parsed_json)
                        
                    except Exception as e:
                        status.update(label="Gagal terhubung dengan Server!", state="error")
                        st.error(f"Error: {e}")

# ------------------------------------------
# TAB 2: RIWAYAT PENGECEKAN
# ------------------------------------------
with tab_history:
    st.markdown("Menampilkan **10 hasil validasi terakhir** yang tersimpan di database.")
    
    col_refresh, _ = st.columns([1, 4])
    with col_refresh:
        st.button("🔄 Segarkan Data")
        
    try:
        response = supabase.table("evaluation_logs").select("*").order("created_at", desc=True).limit(10).execute()
        logs = response.data
        
        if not logs:
            st.info("Belum ada data riwayat pengecekan.")
        else:
            for idx, log in enumerate(logs):
                waktu_eksekusi = log.get('created_at', '')[:19].replace('T', ' ')
                label_expander = f"[{waktu_eksekusi}] {log['image_type']} - {log['model_used']}"
                
                with st.expander(label_expander, expanded=(idx==0)):
                    col_img, col_data = st.columns([1, 2])
                    
                    with col_img:
                        st.image(log['image_url'], use_container_width=True)
                        st.caption(f"⏱️ Waktu Inferensi: **{log['execution_time_seconds']} dtk**")
                        
                    with col_data:
                        st.json(log['extracted_data'])
                        
    except Exception as e:
        st.error(f"Gagal mengambil data dari database: {e}")
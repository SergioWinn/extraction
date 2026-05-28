import streamlit as st
import requests
import time
from supabase import create_client, Client

# ==========================================
# 1. KONFIGURASI SECRETS
# ==========================================
# Mengambil kredensial dari pengaturan Secrets di Streamlit Cloud
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
BACKEND_API_URL = st.secrets["BACKEND_API_URL"]

# Inisialisasi Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. UI: SIDEBAR PENGATURAN
# ==========================================
st.set_page_config(page_title="VLM Validator IKR-CRM", layout="wide")
st.title("🔍 Evaluasi VLM Lokal - IKR & FWA")

with st.sidebar:
    st.header("⚙️ Konfigurasi Pengujian")
    selected_model = st.selectbox(
        "Pilih Model VLM:",
        ("Qwen2.5-VL-7B-Instruct", "InternVL3-8B", "Llama-3.2-Vision-11B", "Qwen2.5-VL-3B-Instruct")
    )
    image_type = st.selectbox(
        "Tipe Gambar (Rule Inventory):",
        ("ikr_modempass", "ikr_homepass", "ikr_odppass", "ikr_speedtest", "opm_redaman", "receiver_link")
    )

# ==========================================
# 3. UI: MAIN AREA (Upload & Proses)
# ==========================================
uploaded_file = st.file_uploader("Unggah Gambar Validasi (.jpg/.png)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    col1, col2 = st.columns(2)
    with col1:
        st.image(uploaded_file, caption="Preview Gambar", use_column_width=True)
        
    with col2:
        if st.button("🚀 Ekstrak & Validasi", type="primary", use_container_width=True):
            with st.status("Memproses alur kerja...", expanded=True) as status:
                
                # STEP 1: Upload ke Supabase
                st.write("📤 Mengunggah gambar ke Supabase...")
                file_bytes = uploaded_file.getvalue()
                file_name = f"{int(time.time())}_{uploaded_file.name}"
                
                supabase.storage.from_("vlm-eval-images").upload(file_name, file_bytes)
                public_url = supabase.storage.from_("vlm-eval-images").get_public_url(file_name)
                
                # STEP 2: Routing ke Backend
                st.write(f"🤖 Swap & Eksekusi model {selected_model} di Server GPU...")
                start_time = time.time()
                
                payload = {
                    "image_url": public_url,
                    "image_type": image_type,
                    "model_name": selected_model
                }
                
                try:
                    # Request ke server GPU Anda
                    response = requests.post(BACKEND_API_URL, json=payload, timeout=150)
                    response.raise_for_status() 
                    
                    result_json = response.json()
                    execution_time = round(time.time() - start_time, 2)
                    
                    # STEP 3: Simpan Hasil ke DB
                    st.write("💾 Menyimpan log JSON ke Database...")
                    supabase.table("evaluation_logs").insert({
                        "image_url": public_url,
                        "image_type": image_type,
                        "model_used": selected_model,
                        "execution_time_seconds": execution_time,
                        "extracted_data": result_json
                    }).execute()
                    
                    status.update(label=f"Selesai dalam {execution_time} detik!", state="complete", expanded=False)
                    
                    # Tampilkan Hasil
                    st.success("Validasi Sukses!")
                    st.json(result_json)
                    
                except requests.exceptions.RequestException as e:
                    status.update(label="Terjadi Kesalahan Koneksi!", state="error")
                    st.error(f"Gagal menghubungi server GPU: {e}")
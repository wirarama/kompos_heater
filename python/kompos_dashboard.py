"""
KomposIoT Dashboard - Streamlit
=================================================================
Visualisasi data sensor & pengaturan node IoT melalui server API PHP
(sumber data: file JSON di server, diakses via endpoint index.php &
settings.php).

Jalankan:
    pip install streamlit pandas plotly requests
    streamlit run kompos_dashboard.py

Author: Wirarama Wedashwara Wyrawan - Universitas Mataram
=================================================================
"""

import time
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# ============================= KONFIGURASI HALAMAN =============================
st.set_page_config(
    page_title="KomposIoT Dashboard",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

PRIMARY_COLOR = "#2E5C8A"
NAVY = "#1F3864"

st.markdown(
    f"""
    <style>
    .stMetric {{
        background-color: #F5F8FB;
        border: 1px solid #D6E1EC;
        border-radius: 10px;
        padding: 10px 14px;
    }}
    h1, h2, h3 {{ color: {NAVY}; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================= STATE DEFAULT =============================
if "api_base_url" not in st.session_state:
    st.session_state.api_base_url = "http://192.168.1.100/kompos_api"
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "refresh_counter" not in st.session_state:
    st.session_state.refresh_counter = 0

# ============================= FUNGSI KOMUNIKASI API =============================
def _headers():
    h = {}
    if st.session_state.api_key:
        h["X-API-Key"] = st.session_state.api_key
    return h


def api_get(path, params=None, timeout=8):
    url = f"{st.session_state.api_base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = requests.get(url, params=params or {}, headers=_headers(), timeout=timeout)
        r.raise_for_status()
        payload = r.json()
        if not payload.get("success", False):
            st.error(f"API error: {payload.get('message', 'unknown error')}")
            return None
        return payload.get("data")
    except requests.exceptions.RequestException as e:
        st.error(f"Gagal menghubungi server API: {e}")
        return None
    except ValueError:
        st.error("Respons server bukan JSON yang valid.")
        return None


def api_post(path, json_body, timeout=8):
    url = f"{st.session_state.api_base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = requests.post(url, json=json_body, headers=_headers(), timeout=timeout)
        payload = r.json()
        if not payload.get("success", False):
            st.error(f"API error: {payload.get('message', 'unknown error')}")
            return None
        return payload.get("data")
    except requests.exceptions.RequestException as e:
        st.error(f"Gagal menghubungi server API: {e}")
        return None
    except ValueError:
        st.error("Respons server bukan JSON yang valid.")
        return None


@st.cache_data(ttl=10, show_spinner=False)
def fetch_devices(base_url, cache_bust):
    data = api_get("index.php", {"action": "devices"})
    return data or []


@st.cache_data(ttl=10, show_spinner=False)
def fetch_range(base_url, device_id, start, end, cache_bust):
    params = {"action": "range", "start": start, "end": end}
    data = api_get("index.php", params)
    if not data:
        return pd.DataFrame()
    records = data.get("records", [])
    if device_id and device_id != "Semua Device":
        records = [r for r in records if r.get("device_id") == device_id]
    return records_to_df(records)


@st.cache_data(ttl=10, show_spinner=False)
def fetch_latest(base_url, device_id, limit, cache_bust):
    if device_id and device_id != "Semua Device":
        data = api_get("index.php", {"action": "device", "device_id": device_id, "limit": limit})
        records = data.get("records", []) if data else []
    else:
        data = api_get("index.php", {"action": "all", "limit": limit, "offset": 0})
        records = data.get("records", []) if data else []
    return records_to_df(records)


@st.cache_data(ttl=10, show_spinner=False)
def fetch_stats(base_url, device_id, start, end, cache_bust):
    params = {"action": "stats", "start": start, "end": end}
    if device_id and device_id != "Semua Device":
        params["device_id"] = device_id
    return api_get("index.php", params)


def records_to_df(records):
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")
    return df


def fetch_node_settings(device_id):
    return api_get("settings.php", {"device_id": device_id})


def push_node_settings(device_id, setpoint_low, setpoint_high, hysteresis, humidity_threshold):
    body = {
        "device_id": device_id,
        "setpoint_low": setpoint_low,
        "setpoint_high": setpoint_high,
        "hysteresis": hysteresis,
        "humidity_fan_threshold": humidity_threshold,
    }
    return api_post("settings.php", body)


# ============================= SIDEBAR =============================
with st.sidebar:
    st.markdown("## ⚙️ Koneksi Server")
    st.session_state.api_base_url = st.text_input(
        "URL Server API (folder api/)",
        value=st.session_state.api_base_url,
        help="Contoh: http://192.168.1.100/kompos_api",
    )
    st.session_state.api_key = st.text_input(
        "API Key (opsional)", value=st.session_state.api_key, type="password"
    )

    st.divider()

    devices = fetch_devices(st.session_state.api_base_url, st.session_state.refresh_counter)
    device_options = ["Semua Device"] + devices
    selected_device = st.selectbox("Pilih Device", device_options, index=0)

    st.divider()
    st.markdown("## 🕒 Rentang Waktu")
    quick_range = st.radio(
        "Rentang cepat",
        ["24 Jam Terakhir", "7 Hari Terakhir", "30 Hari Terakhir", "Kustom"],
        index=1,
    )

    today = datetime.now().date()
    if quick_range == "24 Jam Terakhir":
        start_date, end_date = today - timedelta(days=1), today
    elif quick_range == "7 Hari Terakhir":
        start_date, end_date = today - timedelta(days=7), today
    elif quick_range == "30 Hari Terakhir":
        start_date, end_date = today - timedelta(days=30), today
    else:
        col_a, col_b = st.columns(2)
        start_date = col_a.date_input("Dari", today - timedelta(days=7))
        end_date = col_b.date_input("Sampai", today)

    st.divider()
    refresh_col1, refresh_col2 = st.columns([1, 1])
    if refresh_col1.button("🔄 Refresh", use_container_width=True):
        st.session_state.refresh_counter += 1
        fetch_devices.clear()
        fetch_range.clear()
        fetch_latest.clear()
        fetch_stats.clear()
        st.rerun()

    auto_refresh = refresh_col2.toggle("Auto", value=False, help="Refresh otomatis tiap 30 detik")

st.title("🌱 KomposIoT Dashboard")
st.caption("Monitoring & kendali suhu kompos berbasis IoT — Universitas Mataram")

tab_visual, tab_settings, tab_raw = st.tabs(["📊 Visualisasi Data", "🛠️ Pengaturan Node", "📋 Data Mentah"])

# ============================= TAB 1: VISUALISASI =============================
with tab_visual:
    df = fetch_range(
        st.session_state.api_base_url,
        selected_device,
        start_date.isoformat(),
        end_date.isoformat(),
        st.session_state.refresh_counter,
    )

    latest_df = fetch_latest(st.session_state.api_base_url, selected_device, 1, st.session_state.refresh_counter)

    if latest_df.empty:
        st.warning("Belum ada data yang diterima dari node, atau server tidak terjangkau.")
    else:
        last = latest_df.iloc[-1]
        st.markdown(f"**Data terbaru:** {last['timestamp']} — device `{last['device_id']}`")

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("🌡️ Suhu Kompos", f"{last.get('compost_temp', 'N/A')} °C")
        m2.metric("🌤️ Suhu Udara (BMP280)", f"{last.get('bmp280_temp', 'N/A')} °C")
        m3.metric("💧 Kelembaban (AHT20)", f"{last.get('aht20_humidity', 'N/A')} %")
        m4.metric("🧭 Tekanan Udara", f"{last.get('bmp280_pressure', 'N/A')} hPa")
        heater_icon = {"heating": "🔥", "cooling": "❄️", "idle": "⏸️"}.get(last.get("heater_status"), "❔")
        m5.metric(f"{heater_icon} Pemanas/Pendingin", str(last.get("heater_status", "N/A")).capitalize(),
                   f"PWM {last.get('heater_pwm', 0)}")
        fan_icon = "🌀" if last.get("fan_status") == "on" else "⏹️"
        m6.metric(f"{fan_icon} Kipas", str(last.get("fan_status", "N/A")).capitalize(),
                   f"PWM {last.get('fan_pwm', 0)}")

    st.divider()

    if df.empty:
        st.info("Tidak ada data pada rentang waktu yang dipilih.")
    else:
        # ---- Grafik suhu kompos dengan zona setpoint ----
        st.subheader("Suhu Inti Kompos")
        fig_compost = go.Figure()
        fig_compost.add_trace(go.Scatter(
            x=df["timestamp"], y=df["compost_temp"], mode="lines",
            name="Suhu Kompos", line=dict(color=PRIMARY_COLOR, width=2),
        ))
        node_settings = fetch_node_settings(selected_device) if selected_device != "Semua Device" else None
        if node_settings:
            fig_compost.add_hline(y=node_settings.get("setpoint_low"), line_dash="dot",
                                    line_color="#4C9AFF", annotation_text="Setpoint Bawah")
            fig_compost.add_hline(y=node_settings.get("setpoint_high"), line_dash="dot",
                                    line_color="#E8590C", annotation_text="Setpoint Atas")
        fig_compost.update_layout(height=380, xaxis_title="Waktu", yaxis_title="°C",
                                    margin=dict(t=20, b=20))
        st.plotly_chart(fig_compost, use_container_width=True)

        # ---- Suhu udara vs kelembaban ----
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Suhu Udara Sekitar")
            fig_air = go.Figure()
            fig_air.add_trace(go.Scatter(x=df["timestamp"], y=df["bmp280_temp"], name="BMP280",
                                           line=dict(color="#2E5C8A")))
            fig_air.add_trace(go.Scatter(x=df["timestamp"], y=df["aht20_temp"], name="AHT20",
                                           line=dict(color="#8AA9C9")))
            fig_air.update_layout(height=320, xaxis_title="Waktu", yaxis_title="°C", margin=dict(t=20, b=20))
            st.plotly_chart(fig_air, use_container_width=True)

        with col2:
            st.subheader("Kelembaban & Tekanan Udara")
            fig_hum = go.Figure()
            fig_hum.add_trace(go.Scatter(x=df["timestamp"], y=df["aht20_humidity"], name="Kelembaban (%)",
                                           yaxis="y1", line=dict(color="#2E8B8B")))
            fig_hum.add_trace(go.Scatter(x=df["timestamp"], y=df["bmp280_pressure"], name="Tekanan (hPa)",
                                           yaxis="y2", line=dict(color="#B08A2E")))
            fig_hum.update_layout(
                height=320, xaxis_title="Waktu", margin=dict(t=20, b=20),
                yaxis=dict(title="Kelembaban (%)"),
                yaxis2=dict(title="Tekanan (hPa)", overlaying="y", side="right"),
                legend=dict(orientation="h", y=1.15),
            )
            st.plotly_chart(fig_hum, use_container_width=True)

        # ---- Status aktuator dari waktu ke waktu ----
        st.subheader("Aktivitas Aktuator (PWM)")
        df_plot = df.copy()
        df_plot["heater_pwm_signed"] = df_plot.apply(
            lambda r: r["heater_pwm"] if r["heater_status"] == "heating"
            else (-r["heater_pwm"] if r["heater_status"] == "cooling" else 0), axis=1)
        fig_act = go.Figure()
        fig_act.add_trace(go.Bar(x=df_plot["timestamp"], y=df_plot["heater_pwm_signed"],
                                   name="Pemanas(+)/Pendingin(-)", marker_color=PRIMARY_COLOR))
        fig_act.add_trace(go.Scatter(x=df_plot["timestamp"], y=df_plot["fan_pwm"],
                                       name="Kipas PWM", mode="lines", line=dict(color="#E8590C", width=2)))
        fig_act.update_layout(height=320, xaxis_title="Waktu", yaxis_title="PWM (0-255, +/-)",
                                margin=dict(t=20, b=20), legend=dict(orientation="h", y=1.15))
        st.plotly_chart(fig_act, use_container_width=True)

        # ---- Statistik ringkas ----
        st.subheader("Statistik Rentang Waktu Terpilih")
        stats = fetch_stats(
            st.session_state.api_base_url, selected_device,
            start_date.isoformat(), end_date.isoformat(), st.session_state.refresh_counter,
        )
        if stats:
            s1, s2, s3 = st.columns(3)
            ct = stats.get("compost_temp", {})
            s1.metric("Suhu Kompos (min/avg/max)",
                       f"{ct.get('min', '-')}° / {ct.get('avg', '-')}° / {ct.get('max', '-')}°")
            hs = stats.get("heater_summary", {})
            s2.metric("Heating / Cooling / Idle",
                       f"{hs.get('heating_count', 0)} / {hs.get('cooling_count', 0)} / {hs.get('idle_count', 0)}")
            fs = stats.get("fan_summary", {})
            s3.metric("Kipas On / Off", f"{fs.get('on_count', 0)} / {fs.get('off_count', 0)}")

# ============================= TAB 2: PENGATURAN NODE =============================
with tab_settings:
    st.subheader("Pengaturan Parameter Kontrol Node")

    if selected_device == "Semua Device":
        st.info("Pilih satu device di sidebar untuk mengatur parameter kontrolnya.")
    else:
        current = fetch_node_settings(selected_device) or {}
        st.caption(
            f"Pengaturan terakhir diperbarui: "
            f"{current.get('updated_at') or 'belum pernah diatur (menggunakan default firmware)'}"
        )

        with st.form("settings_form"):
            c1, c2 = st.columns(2)
            setpoint_low = c1.number_input(
                "Setpoint Bawah (°C) — di bawah ini pemanas aktif",
                min_value=0.0, max_value=100.0,
                value=float(current.get("setpoint_low", 45.0)), step=0.5,
            )
            setpoint_high = c2.number_input(
                "Setpoint Atas (°C) — di atas ini pendingin aktif",
                min_value=0.0, max_value=100.0,
                value=float(current.get("setpoint_high", 65.0)), step=0.5,
            )
            c3, c4 = st.columns(2)
            hysteresis = c3.number_input(
                "Hysteresis (°C)", min_value=0.0, max_value=20.0,
                value=float(current.get("hysteresis", 2.0)), step=0.5,
            )
            humidity_threshold = c4.number_input(
                "Ambang Kelembaban untuk Kipas (%)", min_value=0.0, max_value=100.0,
                value=float(current.get("humidity_fan_threshold", 85.0)), step=1.0,
            )

            submitted = st.form_submit_button("💾 Simpan Pengaturan", use_container_width=True)

            if submitted:
                if setpoint_low >= setpoint_high:
                    st.error("Setpoint bawah harus lebih kecil dari setpoint atas.")
                else:
                    result = push_node_settings(
                        selected_device, setpoint_low, setpoint_high, hysteresis, humidity_threshold
                    )
                    if result:
                        st.success(f"Pengaturan untuk {selected_device} berhasil disimpan di server.")
                        st.cache_data.clear()
                        st.rerun()

        st.markdown(
            """
            > ℹ️ Pengaturan disimpan di server (`api/data/device_settings.json`) melalui `settings.php`.
            > Firmware node perlu melakukan **polling** endpoint ini secara berkala
            > (`GET settings.php?device_id=...`) agar perubahan diterapkan ke perangkat.
            """
        )

# ============================= TAB 3: DATA MENTAH =============================
with tab_raw:
    st.subheader("Data Mentah")
    df_raw = fetch_range(
        st.session_state.api_base_url, selected_device,
        start_date.isoformat(), end_date.isoformat(), st.session_state.refresh_counter,
    )
    if df_raw.empty:
        st.info("Tidak ada data pada rentang waktu yang dipilih.")
    else:
        st.dataframe(df_raw, use_container_width=True, height=450)
        csv = df_raw.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Unduh CSV", data=csv,
            file_name=f"komposiot_{selected_device}_{start_date}_{end_date}.csv",
            mime="text/csv",
        )

# ============================= AUTO REFRESH =============================
if auto_refresh:
    time.sleep(30)
    st.session_state.refresh_counter += 1
    st.rerun()

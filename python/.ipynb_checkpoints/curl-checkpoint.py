import requests
import random
import time
from datetime import datetime, timezone

# --- KONFIGURASI ---
API_URL = "https://api.compostiq.win/records"
API_KEY = "4893ea612f90aad0cf011a01b20679c44e5cd1189039ab2aae0fb10220f06e5c"
INTERVAL_DETIK = 10 

# --- STATUS AWAL SENSOR ---
sensor_state = {
    "temperature": 40.0,       
    "moisture_percent": 55.0,  
    "o2_percent": 15.0,        
    "co2_percent": 6.0,       
    "nh3_ratio": 0.5           
}

def generate_sensor_data():
    global sensor_state
    
    # 1. Tentukan perubahan suhu sebagai "Driver" (Variabel Utama)
    # Suhu bisa naik atau turun maksimal 0.5 derajat per interval
    delta_temp = random.uniform(-0.5, 0.5)
    
    # 2. Hitung perubahan variabel lain berdasarkan korelasi dengan delta_temp
    # Rumus: (delta_temp * koefisien_korelasi) + noise_acak_kecil
    
    # Korelasi Positif (~0.78) dengan suhu
    delta_moisture = (delta_temp * 0.78) + random.uniform(-0.1, 0.1)
    
    # Korelasi Positif (~0.5) dengan suhu: Mikroba aktif -> CO2 naik
    delta_co2 = (delta_temp * 0.5) + random.uniform(-0.1, 0.1)
    
    # Korelasi Negatif (~ -0.5) dengan suhu: Mikroba aktif -> O2 tersedot/turun
    delta_o2 = (delta_temp * -0.5) + random.uniform(-0.1, 0.1)
    
    # Korelasi Positif (~0.05) dengan suhu: Suhu panas -> Amonia menguap
    delta_nh3 = (delta_temp * 0.05) + random.uniform(-0.01, 0.01)
    
    # 3. Terapkan perubahan ke state saat ini
    sensor_state["temperature"] += delta_temp
    sensor_state["moisture_percent"] += delta_moisture
    sensor_state["co2_percent"] += delta_co2
    sensor_state["o2_percent"] += delta_o2
    sensor_state["nh3_ratio"] += delta_nh3
    
    # 4. Batasi agar nilai tidak keluar batas logis jika script berjalan berhari-hari
    sensor_state["temperature"] = max(20.0, min(80.0, sensor_state["temperature"]))
    sensor_state["moisture_percent"] = max(10.0, min(90.0, sensor_state["moisture_percent"]))
    sensor_state["o2_percent"] = max(1.0, min(21.0, sensor_state["o2_percent"]))  # O2 maks di udara 21%
    sensor_state["co2_percent"] = max(0.0, min(20.0, sensor_state["co2_percent"]))
    sensor_state["nh3_ratio"] = max(0.0, min(2.0, sensor_state["nh3_ratio"]))

    # 5. Kembalikan data (Casting ke Integer untuk menghindari Error 500 dari API)
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "temperature": int(round(sensor_state["temperature"])),       
        "moisture_percent": int(round(sensor_state["moisture_percent"])),  
        "o2_percent": int(round(sensor_state["o2_percent"])),         
        "co2_percent": int(round(sensor_state["co2_percent"])),        
        "nh3_ratio": round(sensor_state["nh3_ratio"], 2)  
    }

def send_data_to_api():
    payload = [generate_sensor_data()]
    
    headers = {
        "Content-Type": "application/json",
        "x-key": API_KEY
    }
    
    try:
        response = requests.post(API_URL, headers=headers, json=payload)
        
        if response.status_code in (200, 201):
            data = payload[0]
            print(f"[{data['timestamp']}] Temp: {data['temperature']}C | Moist: {data['moisture_percent']}% | O2: {data['o2_percent']}% | CO2: {data['co2_percent']}%")
        else:
            print(f"[{payload[0]['timestamp']}] Gagal. Status: {response.status_code}, Pesan: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"Error koneksi: {e}")

if __name__ == "__main__":
    print(f"Memulai simulasi sensor berkorelasi setiap {INTERVAL_DETIK} detik.")
    print("Tekan Ctrl+C untuk menghentikan.\n")
    
    try:
        while True:
            send_data_to_api()
            time.sleep(INTERVAL_DETIK)
            
    except KeyboardInterrupt:
        print("\n\nScript dihentikan oleh pengguna.")
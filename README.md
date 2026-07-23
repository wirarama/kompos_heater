# KomposIoT — Firmware & API Server

Sistem kendali suhu kompos berbasis Wemos D1 R32 (ESP32) dengan penyimpanan data via file JSON.

## 1. Firmware (`firmware/KomposIoT_WemosD1R32.ino`)

### Wiring / Pinout

| Komponen         | Pin Fungsi | GPIO Wemos D1 R32 |
|-------------------|------------|--------------------|
| DS18B20 (data)     | OneWire    | GPIO4 (D2)          |
| BMP280 + AHT20     | SDA / SCL  | GPIO21 / GPIO22     |
| BTS7960 RPWM       | Heating    | GPIO25              |
| BTS7960 LPWM       | Cooling    | GPIO26              |
| BTS7960 R_EN       | Enable     | GPIO27              |
| BTS7960 L_EN       | Enable     | GPIO14              |
| L298N ENA (kipas)  | PWM speed  | GPIO32              |
| L298N IN1          | Arah       | GPIO33              |
| L298N IN2          | Arah       | GPIO13              |

Catatan:
- DS18B20 butuh resistor pull-up 4.7kΩ antara pin data dan VCC.
- BTS7960 dipakai dua arah (RPWM/LPWM) untuk mendukung elemen Peltier (heating & cooling). Jika hanya memakai elemen pemanas resistif satu arah, cukup gunakan RPWM saja dan tie LPWM ke 0.
- L298N pada firmware ini hanya mengatur kipas satu arah dengan kecepatan variabel (PWM di ENA).

### Library yang dibutuhkan (Arduino IDE Library Manager)
- `OneWire`
- `DallasTemperature`
- `Adafruit BMP280 Library`
- `Adafruit AHTX0`
- `Adafruit Unified Sensor`
- `ArduinoJson` (v6/v7)
- ESP32 Board Package (Wemos D1 R32 = varian ESP32 Dev Module)

### Konfigurasi sebelum upload
Edit bagian atas file `.ino`:
```cpp
const char* WIFI_SSID     = "NAMA_WIFI_ANDA";
const char* WIFI_PASSWORD = "PASSWORD_WIFI_ANDA";
const char* API_HOST      = "http://192.168.1.100/kompos_api";
```
Sesuaikan juga `SETPOINT_LOW`, `SETPOINT_HIGH`, dan `HYSTERESIS` dengan target fase kompos yang diinginkan.

### Logika kontrol
- Suhu kompos < `SETPOINT_LOW - HYSTERESIS` → BTS7960 mode **heating**, PWM proporsional terhadap selisih suhu.
- Suhu kompos > `SETPOINT_HIGH + HYSTERESIS` → BTS7960 mode **cooling**.
- Di antara batas hysteresis → status aktuator sebelumnya dipertahankan (mencegah chattering).
- Kipas L298N aktif jika suhu kompos di atas `SETPOINT_HIGH` (bantu pendinginan) atau kelembaban udara di atas `HUMIDITY_FAN_THRESHOLD` (bantu aerasi).

## 2. API Server (`api/`)

PHP murni, tanpa database — seluruh data tersimpan di `api/data/sensor_data.json`.

### Deploy
1. Upload folder `api/` ke server (XAMPP/Apache/Nginx+PHP), misalnya ke `htdocs/kompos_api/`.
2. Pastikan folder `api/data/` bisa ditulis oleh web server (`chmod 775 data`).
3. (Opsional) Isi `API_KEY` di `config.php` untuk mewajibkan header `X-API-Key` pada setiap request.
4. Sesuaikan `API_HOST` di firmware agar menunjuk ke URL server ini.

### Endpoint

**Kirim data (dari firmware)**
```
POST /index.php
Content-Type: application/json

{
  "device_id": "KOMPOS-NODE-01",
  "compost_temp": 52.3,
  "bmp280_temp": 29.1,
  "bmp280_pressure": 1009.4,
  "aht20_temp": 29.4,
  "aht20_humidity": 68.2,
  "heater_status": "heating",
  "heater_pwm": 180,
  "fan_status": "on",
  "fan_pwm": 200,
  "uptime_ms": 123456
}
```

**Query data**
| URL | Keterangan |
|---|---|
| `GET /index.php?action=latest&limit=20` | N data terbaru |
| `GET /index.php?action=all&limit=100&offset=0` | Semua data (paginasi) |
| `GET /index.php?action=range&start=2026-07-01&end=2026-07-18` | Filter rentang tanggal |
| `GET /index.php?action=device&device_id=KOMPOS-NODE-01` | Filter per device |
| `GET /index.php?action=stats&start=&end=&device_id=` | Statistik min/max/avg |
| `GET /index.php?action=count` | Jumlah total record |

Semua response berbentuk:
```json
{ "success": true, "message": "...", "data": { ... } }
```

### Endpoint tambahan
| URL | Keterangan |
|---|---|
| `GET /index.php?action=devices` | Daftar `device_id` unik yang pernah mengirim data |
| `GET /settings.php?device_id=KOMPOS-NODE-01` | Ambil pengaturan kontrol node (setpoint, hysteresis, dll) |
| `POST /settings.php` | Simpan/perbarui pengaturan node — body sama dengan field firmware (`setpoint_low`, `setpoint_high`, `hysteresis`, `humidity_fan_threshold`) |

Pengaturan tersimpan di `api/data/device_settings.json` (terpisah dari data sensor). **Firmware saat ini belum melakukan polling ke `settings.php`** — untuk menerapkan pengaturan yang diubah lewat dashboard secara otomatis ke node, tambahkan pemanggilan `GET settings.php?device_id=...` berkala di firmware dan perbarui variabel `SETPOINT_LOW/HIGH/HYSTERESIS` sesuai respons.

### Keamanan & catatan produksi
- File `api/data/.htaccess` memblokir akses langsung ke `sensor_data.json` dari browser (khusus Apache).
- `MAX_RECORDS` di `config.php` membatasi jumlah record tersimpan agar file JSON tidak tumbuh tanpa batas — untuk skala besar/jangka panjang, disarankan migrasi ke SQLite/MySQL.
- Penulisan file menggunakan `flock()` agar aman dari race condition saat beberapa node mengirim data bersamaan.

## 3. Dashboard Streamlit (`dashboard/kompos_dashboard.py`)

Visualisasi data sensor + pengaturan parameter kontrol node, seluruhnya lewat API PHP di atas (tidak mengakses file JSON secara langsung).

### Instalasi & menjalankan
```bash
pip install streamlit pandas plotly requests
streamlit run dashboard/kompos_dashboard.py
```

### Fitur
- **Tab Visualisasi Data**: metrik terkini (suhu kompos, suhu/kelembaban/tekanan udara, status pemanas & kipas), grafik suhu kompos dengan garis setpoint, grafik suhu udara & kelembaban/tekanan, grafik aktivitas PWM aktuator, dan statistik ringkas (min/avg/max, jumlah heating/cooling/idle).
- **Tab Pengaturan Node**: form untuk mengubah setpoint bawah/atas, hysteresis, dan ambang kelembaban kipas per device — tersimpan ke server via `settings.php`.
- **Tab Data Mentah**: tabel data lengkap + unduh CSV.
- Sidebar: URL server API & API key dapat diatur langsung dari UI, pilih device, rentang waktu cepat (24 jam/7 hari/30 hari/kustom), tombol refresh manual, dan toggle auto-refresh 30 detik.

## 4. Simulasi Data 6 Fase Kompos (`simulasi/simulate_6_fase_kompos.py`)

Membangkitkan data sensor sintetis untuk 6 fase dekomposisi kompos aerobik secara berurutan, lalu mengirimkannya ke server API PHP seolah dari node IoT nyata. Fase yang disimulasikan: **Mesofilik Awal → Termofilik Naik → Termofilik Puncak → Termofilik Turun → Mesofilik Kedua → Pematangan/Stabil** (total default 45 hari).

```bash
pip install requests numpy pandas

# Uji coba cepat, hanya buat CSV lokal tanpa kirim ke server:
python simulasi/simulate_6_fase_kompos.py --skip-api

# Kirim penuh ke server API:
python simulasi/simulate_6_fase_kompos.py \
    --api-url http://192.168.1.100/kompos_api \
    --device-id KOMPOS-SIM-01 \
    --interval-minutes 120
```

Output:
- Data dikirim ke `POST /index.php` (field sama seperti firmware asli, ditambah `timestamp` historis agar urutan waktu tetap benar untuk analisis time-series — `index.php` sudah diperbarui untuk menerima timestamp opsional ini).
- File CSV lokal **berlabel fase** (`kompos_6fase_simulasi.csv`) — dipakai sebagai data latih pada skrip analisis, karena server API sendiri tidak menyimpan label fase.

Contoh hasil: `simulasi/contoh_kompos_6fase_simulasi.csv`.

## 5. Analisis ARIMA & Decision Tree (`analisis/analisis_arima_decision_tree.py`)

```bash
pip install pandas numpy matplotlib seaborn scikit-learn statsmodels requests

python analisis/analisis_arima_decision_tree.py \
    --csv simulasi/kompos_6fase_simulasi.csv \
    --api-url http://192.168.1.100/kompos_api \
    --device-id KOMPOS-SIM-01 \
    --output-dir hasil_analisis
```

Jika `--api-url` tidak diisi atau server tidak terjangkau, skrip otomatis memakai CSV lokal sepenuhnya (mode mandiri/offline) — cocok untuk uji coba tanpa server aktif.

**Bagian 1 — ARIMA**: mencari orde `(p,d,q)` terbaik lewat grid search AIC pada suhu kompos, evaluasi RMSE/MAE/MAPE pada data uji, lalu meramalkan N langkah ke depan dengan interval kepercayaan 95%.

**Bagian 2 — Decision Tree**: klasifikasi fase kompos berdasarkan fitur suhu kompos, suhu/kelembaban/tekanan udara, laju perubahan suhu, dan rolling mean — dilatih dari CSV berlabel, lalu (jika `--api-url` diisi) diterapkan ke data live server untuk memprediksi **fase kompos saat ini** beserta tingkat keyakinannya.

**Grafik yang dihasilkan** (folder `--output-dir`):
| File | Isi |
|---|---|
| `00_timeline_fase.png` | Sebaran suhu kompos per fase sepanjang waktu |
| `01_arima_forecast.png` | Aktual vs prediksi vs peramalan ARIMA + interval kepercayaan |
| `02_confusion_matrix.png` | Confusion matrix klasifikasi fase |
| `03_feature_importance.png` | Tingkat kepentingan fitur pada Decision Tree |
| `04_decision_tree.png` | Struktur pohon keputusan (depth 3 untuk keterbacaan) |
| `prediksi_fase_live.csv` | Prediksi fase pada data live server (jika `--api-url` diisi) |

Contoh hasil: `analisis/contoh_hasil_analisis/`.

"""
KomposIoT - Simulasi Data 6 Fase Kompos
=================================================================
Membangkitkan data sensor sintetis yang merepresentasikan 6 fase
dekomposisi kompos secara berurutan, lalu mengirimkannya ke server
API PHP (index.php) seolah-olah berasal dari node IoT sungguhan.
Juga menyimpan salinan lokal berlabel fase (CSV) untuk keperluan
training model klasifikasi pada skrip analisis.

6 Fase yang disimulasikan (mengikuti teori dekomposisi kompos aerobik):
  1. Mesofilik Awal      - aktivitas mikroba awal, suhu naik bertahap
  2. Termofilik Naik     - suhu naik cepat, dekomposisi aktif dimulai
  3. Termofilik Puncak   - suhu maksimum, dekomposisi paling intensif
  4. Termofilik Turun    - suhu mulai turun, aktivitas mikroba melambat
  5. Mesofilik Kedua      - suhu mendekati ambient, maturasi berlangsung
  6. Pematangan/Stabil   - suhu stabil, kompos matang

Jalankan:
    pip install requests numpy pandas

    # Hanya membuat CSV lokal (tanpa mengirim ke server) - untuk uji coba:
    python simulate_6_fase_kompos.py --skip-api

    # Kirim penuh ke server API:
    python simulate_6_fase_kompos.py --api-url http://192.168.1.100/kompos_api

Author: Wirarama Wedashwara Wyrawan - Universitas Mataram
=================================================================
"""

import argparse
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

# ============================= DEFINISI 6 FASE KOMPOS =============================
# Setiap fase: (nama, durasi_hari, suhu_kompos_awal, suhu_kompos_akhir,
#               kelembaban_awal(%), kelembaban_akhir(%), noise_std)
PHASES = [
    {
        "name": "Mesofilik Awal",
        "duration_days": 3,
        "temp_start": 27.0, "temp_end": 39.0,
        "humidity_start": 68.0, "humidity_end": 65.0,
        "noise_std": 0.6,
    },
    {
        "name": "Termofilik Naik",
        "duration_days": 4,
        "temp_start": 39.0, "temp_end": 57.0,
        "humidity_start": 65.0, "humidity_end": 60.0,
        "noise_std": 1.0,
    },
    {
        "name": "Termofilik Puncak",
        "duration_days": 11,
        "temp_start": 57.0, "temp_end": 67.0,
        "humidity_start": 60.0, "humidity_end": 55.0,
        "noise_std": 1.3,
    },
    {
        "name": "Termofilik Turun",
        "duration_days": 7,
        "temp_start": 67.0, "temp_end": 43.0,
        "humidity_start": 55.0, "humidity_end": 52.0,
        "noise_std": 1.0,
    },
    {
        "name": "Mesofilik Kedua",
        "duration_days": 10,
        "temp_start": 43.0, "temp_end": 31.0,
        "humidity_start": 52.0, "humidity_end": 50.0,
        "noise_std": 0.7,
    },
    {
        "name": "Pematangan/Stabil",
        "duration_days": 10,
        "temp_start": 31.0, "temp_end": 27.0,
        "humidity_start": 50.0, "humidity_end": 48.0,
        "noise_std": 0.4,
    },
]

# ---- Parameter kontrol (samakan dengan firmware, untuk hitung status aktuator) ----
SETPOINT_LOW = 45.0
SETPOINT_HIGH = 65.0
HYSTERESIS = 2.0
HUMIDITY_FAN_THRESHOLD = 85.0

AMBIENT_TEMP_OFFSET = -8.0   # suhu udara sekitar lebih rendah dari suhu inti kompos
AMBIENT_PRESSURE_BASE = 1010.0


def smooth_curve(start, end, n, noise_std, rng, curvature=1.6):
    """Kurva transisi halus (ease-in-out) start->end sepanjang n titik + noise acak."""
    t = np.linspace(0, 1, n)
    eased = t ** curvature / (t ** curvature + (1 - t) ** curvature + 1e-9)
    eased[0], eased[-1] = 0.0, 1.0
    base = start + (end - start) * eased
    noise = rng.normal(0, noise_std, n)
    # noise kumulatif kecil agar terlihat seperti random-walk halus, bukan acak murni
    smoothed_noise = pd.Series(noise).rolling(3, min_periods=1, center=True).mean().to_numpy()
    return base + smoothed_noise


def compute_actuator_status(compost_temp, humidity, prev_heater, prev_fan):
    """Replika sederhana logika hysteresis firmware untuk BTS7960 & L298N."""
    if compost_temp < (SETPOINT_LOW - HYSTERESIS):
        diff = min(SETPOINT_LOW - compost_temp, 10)
        heater_status, heater_pwm = "heating", int(np.interp(diff, [0, 10], [120, 255]))
    elif compost_temp > (SETPOINT_HIGH + HYSTERESIS):
        diff = min(compost_temp - SETPOINT_HIGH, 10)
        heater_status, heater_pwm = "cooling", int(np.interp(diff, [0, 10], [120, 255]))
    elif SETPOINT_LOW <= compost_temp <= SETPOINT_HIGH:
        heater_status, heater_pwm = "idle", 0
    else:
        heater_status, heater_pwm = prev_heater, (0 if prev_heater == "idle" else 150)

    need_cooling_assist = compost_temp > SETPOINT_HIGH
    need_humidity_vent = humidity > HUMIDITY_FAN_THRESHOLD
    if need_cooling_assist or need_humidity_vent:
        fan_status, fan_pwm = "on", (255 if need_cooling_assist else 160)
    else:
        fan_status, fan_pwm = "off", 0

    return heater_status, heater_pwm, fan_status, fan_pwm


def generate_dataset(start_time, interval_minutes, seed=42):
    """Bangkitkan seluruh dataset 6 fase sebagai DataFrame."""
    rng = np.random.default_rng(seed)
    rows = []
    current_time = start_time
    prev_heater, prev_fan = "idle", "off"

    for phase in PHASES:
        n_points = max(2, int(phase["duration_days"] * 24 * 60 / interval_minutes))
        compost_curve = smooth_curve(
            phase["temp_start"], phase["temp_end"], n_points, phase["noise_std"], rng
        )
        humidity_curve = smooth_curve(
            phase["humidity_start"], phase["humidity_end"], n_points, 0.8, rng
        )

        for i in range(n_points):
            compost_temp = round(float(compost_curve[i]), 2)
            humidity = round(float(np.clip(humidity_curve[i], 30, 95)), 2)

            air_temp = round(compost_temp + AMBIENT_TEMP_OFFSET + rng.normal(0, 0.4), 2)
            aht_temp = round(air_temp + rng.normal(0, 0.3), 2)
            pressure = round(AMBIENT_PRESSURE_BASE + rng.normal(0, 1.2), 2)

            heater_status, heater_pwm, fan_status, fan_pwm = compute_actuator_status(
                compost_temp, humidity, prev_heater, prev_fan
            )
            prev_heater, prev_fan = heater_status, fan_status

            rows.append({
                "timestamp": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                "fase": phase["name"],
                "compost_temp": compost_temp,
                "bmp280_temp": air_temp,
                "bmp280_pressure": pressure,
                "aht20_temp": aht_temp,
                "aht20_humidity": humidity,
                "heater_status": heater_status,
                "heater_pwm": heater_pwm,
                "fan_status": fan_status,
                "fan_pwm": fan_pwm,
            })
            current_time += timedelta(minutes=interval_minutes)

    return pd.DataFrame(rows)


def send_to_api(df, api_url, device_id, api_key=None, delay_seconds=0.0, verbose=True):
    """Kirim setiap baris (tanpa kolom 'fase') ke endpoint POST /index.php."""
    endpoint = f"{api_url.rstrip('/')}/index.php"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    success, failed = 0, 0
    total = len(df)

    for idx, row in df.iterrows():
        payload = row.drop(labels=["fase"]).to_dict()
        try:
            r = requests.post(endpoint, json=payload, headers=headers, timeout=8)
            ok = r.ok and r.json().get("success", False)
        except (requests.exceptions.RequestException, ValueError):
            ok = False

        if ok:
            success += 1
        else:
            failed += 1

        if verbose and (idx + 1) % 50 == 0:
            print(f"  → progres: {idx + 1}/{total} terkirim ({success} sukses, {failed} gagal)")

        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return success, failed


def main():
    parser = argparse.ArgumentParser(description="Simulasi 6 fase kompos -> API PHP KomposIoT")
    parser.add_argument("--api-url", default="http://192.168.1.100/kompos_api",
                         help="Base URL folder api/ pada server (default: %(default)s)")
    parser.add_argument("--api-key", default="", help="API key jika diaktifkan di server")
    parser.add_argument("--device-id", default="KOMPOS-SIM-01", help="device_id yang dikirim")
    parser.add_argument("--interval-minutes", type=int, default=120,
                         help="Interval antar pembacaan sensor simulasi, dalam menit (default: 120)")
    parser.add_argument("--start-date", default=None,
                         help="Tanggal mulai simulasi format YYYY-MM-DD (default: mundur otomatis dari hari ini)")
    parser.add_argument("--delay-seconds", type=float, default=0.0,
                         help="Jeda antar request HTTP (detik), untuk menghindari membanjiri server")
    parser.add_argument("--skip-api", action="store_true",
                         help="Hanya membuat CSV lokal, tidak mengirim ke server (mode uji coba)")
    parser.add_argument("--output-csv", default="kompos_6fase_simulasi.csv",
                         help="Path file CSV output berlabel fase")
    parser.add_argument("--seed", type=int, default=42, help="Random seed agar hasil reproducible")
    args = parser.parse_args()

    total_days = sum(p["duration_days"] for p in PHASES)
    if args.start_date:
        start_time = datetime.strptime(args.start_date, "%Y-%m-%d")
    else:
        start_time = datetime.now() - timedelta(days=total_days)

    print(f"=== Simulasi 6 Fase Kompos ===")
    print(f"Total durasi     : {total_days} hari")
    print(f"Interval sampel  : {args.interval_minutes} menit")
    print(f"Mulai simulasi   : {start_time.strftime('%Y-%m-%d %H:%M')}")
    print(f"Device ID        : {args.device_id}\n")

    df = generate_dataset(start_time, args.interval_minutes, seed=args.seed)
    df.to_csv(args.output_csv, index=False)
    print(f"✓ Dataset dibangkitkan: {len(df)} baris data")
    print(f"✓ CSV berlabel fase disimpan: {args.output_csv}\n")

    print("Ringkasan per fase:")
    print(df.groupby("fase", sort=False)["compost_temp"]
            .agg(["count", "min", "max", "mean"])
            .round(2).to_string())
    print()

    if args.skip_api:
        print("Mode --skip-api aktif: data TIDAK dikirim ke server.")
        return

    print(f"Mengirim data ke server: {args.api_url}/index.php ...")
    success, failed = send_to_api(
        df, args.api_url, args.device_id, args.api_key or None, args.delay_seconds
    )
    print(f"\n✓ Selesai. {success} record berhasil terkirim, {failed} gagal.")
    if failed > 0:
        print("  Periksa apakah server API dapat diakses dan URL sudah benar.")


if __name__ == "__main__":
    sys.exit(main())

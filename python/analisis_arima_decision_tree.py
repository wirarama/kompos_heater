"""
KomposIoT - Analisis ARIMA & Klasifikasi Decision Tree
=================================================================
1. ARIMA          : peramalan (forecasting) suhu inti kompos
2. Decision Tree  : klasifikasi fase kompos berdasarkan pembacaan sensor
3. Visualisasi    : seluruh hasil disimpan sebagai file PNG

Sumber data:
  - Data historis BERLABEL fase (CSV hasil simulate_6_fase_kompos.py)
    -> dipakai untuk MELATIH model Decision Tree.
  - Data TERKINI dari server API PHP (opsional, --api-url)
    -> dipakai untuk ARIMA (data riil terbaru) dan didemokan diklasifikasi
       fasenya oleh model yang sudah dilatih (server tidak menyimpan label
       fase, jadi fase pada data live diprediksi oleh model).
  - Jika --api-url tidak diisi/tidak terjangkau, skrip otomatis memakai
    CSV historis sebagai sumber data ARIMA juga (mode mandiri/offline).

Jalankan:
    pip install pandas numpy matplotlib seaborn scikit-learn statsmodels requests

    python analisis_arima_decision_tree.py \
        --csv kompos_6fase_simulasi.csv \
        --api-url http://192.168.1.100/kompos_api \
        --device-id KOMPOS-SIM-01

Author: Wirarama Wedashwara Wyrawan - Universitas Mataram
=================================================================
"""

import argparse
import os
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import seaborn as sns
from sklearn.metrics import (accuracy_score, classification_report,
                              confusion_matrix, mean_absolute_error,
                              mean_absolute_percentage_error,
                              mean_squared_error)
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier, plot_tree
from statsmodels.tsa.arima.model import ARIMA

warnings.filterwarnings("ignore")

sns.set_theme(style="whitegrid")
NAVY = "#1F3864"
BLUE = "#2E5C8A"
PALETTE = ["#1F3864", "#2E5C8A", "#4C9AFF", "#2E8B8B", "#E8590C", "#B08A2E"]


# ============================= MUAT DATA =============================
def load_labeled_csv(path):
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def fetch_from_api(api_url, device_id, api_key=None, limit=5000):
    """Ambil seluruh data dari API PHP (tanpa label fase)."""
    try:
        headers = {"X-API-Key": api_key} if api_key else {}
        r = requests.get(
            f"{api_url.rstrip('/')}/index.php",
            params={"action": "device", "device_id": device_id, "limit": limit},
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        payload = r.json()
        if not payload.get("success"):
            print(f"  ! API merespons gagal: {payload.get('message')}")
            return None
        records = payload["data"].get("records", [])
        if not records:
            return None
        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df.sort_values("timestamp").reset_index(drop=True)
    except requests.exceptions.RequestException as e:
        print(f"  ! Tidak bisa mengakses API ({e}). Menggunakan data CSV lokal sebagai gantinya.")
        return None


# ============================= BAGIAN 1: ARIMA =============================
def find_best_arima_order(series, candidate_orders):
    best_aic, best_order, best_model = np.inf, None, None
    for order in candidate_orders:
        try:
            model = ARIMA(series, order=order).fit()
            if model.aic < best_aic:
                best_aic, best_order, best_model = model.aic, order, model
        except Exception:
            continue
    return best_order, best_model, best_aic


def run_arima_analysis(df, output_dir, forecast_steps=24):
    print("\n=== 1. Analisis ARIMA (Peramalan Suhu Kompos) ===")

    series = df.set_index("timestamp")["compost_temp"].asfreq(
        pd.infer_freq(df["timestamp"]) or "2H"
    )
    series = series.interpolate()

    split_idx = int(len(series) * 0.85)
    train, test = series.iloc[:split_idx], series.iloc[split_idx:]

    print(f"  Data latih: {len(train)} titik | Data uji: {len(test)} titik")
    print("  Mencari orde ARIMA terbaik (grid search AIC)...")

    candidate_orders = [(p, d, q) for p in (1, 2, 3) for d in (0, 1) for q in (0, 1, 2)]
    best_order, model, best_aic = find_best_arima_order(train, candidate_orders)
    print(f"  ✓ Orde terbaik: ARIMA{best_order} (AIC={best_aic:.2f})")

    # Evaluasi di data uji
    forecast_test = model.forecast(steps=len(test))
    rmse = np.sqrt(mean_squared_error(test, forecast_test))
    mae = mean_absolute_error(test, forecast_test)
    mape = mean_absolute_percentage_error(test, forecast_test) * 100
    print(f"  Evaluasi pada data uji -> RMSE: {rmse:.3f}°C | MAE: {mae:.3f}°C | MAPE: {mape:.2f}%")

    # Refit dengan seluruh data untuk peramalan ke depan
    final_model = ARIMA(series, order=best_order).fit()
    forecast_result = final_model.get_forecast(steps=forecast_steps)
    forecast_mean = forecast_result.predicted_mean
    conf_int = forecast_result.conf_int(alpha=0.05)

    freq = series.index.freq or pd.infer_freq(series.index)
    future_index = pd.date_range(
        start=series.index[-1], periods=forecast_steps + 1, freq=freq
    )[1:]
    forecast_mean.index = future_index
    conf_int.index = future_index

    # ---- Visualisasi ----
    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.plot(series.index, series.values, color=BLUE, label="Data Aktual", linewidth=1.4)
    ax.plot(test.index, forecast_test.values, color="#E8590C", linestyle="--",
            label="Prediksi pada Data Uji", linewidth=1.6)
    ax.plot(forecast_mean.index, forecast_mean.values, color="#2E8B8B",
            label=f"Peramalan {forecast_steps} Langkah ke Depan", linewidth=1.8)
    ax.fill_between(conf_int.index, conf_int.iloc[:, 0], conf_int.iloc[:, 1],
                     color="#2E8B8B", alpha=0.2, label="Interval Kepercayaan 95%")
    ax.axvline(test.index[0], color="gray", linestyle=":", linewidth=1)
    ax.set_title(f"Peramalan Suhu Inti Kompos — ARIMA{best_order}", fontsize=13, color=NAVY, weight="bold")
    ax.set_xlabel("Waktu")
    ax.set_ylabel("Suhu Kompos (°C)")
    ax.legend(loc="upper left", fontsize=9)
    fig.autofmt_xdate()
    fig.tight_layout()
    out_path = os.path.join(output_dir, "01_arima_forecast.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  ✓ Grafik disimpan: {out_path}")

    return {
        "order": best_order, "aic": best_aic, "rmse": rmse, "mae": mae, "mape": mape,
        "forecast_mean": forecast_mean, "conf_int": conf_int,
    }


# ============================= BAGIAN 2: DECISION TREE =============================
def engineer_features(df):
    """Tambahkan fitur turunan: laju perubahan suhu & rolling mean."""
    df = df.sort_values("timestamp").reset_index(drop=True).copy()
    df["compost_temp_delta"] = df["compost_temp"].diff().fillna(0)
    df["compost_temp_roll_mean"] = df["compost_temp"].rolling(3, min_periods=1).mean()
    df["temp_gap_udara_kompos"] = df["compost_temp"] - df["bmp280_temp"]
    return df


FEATURE_COLUMNS = [
    "compost_temp", "bmp280_temp", "aht20_temp", "aht20_humidity",
    "bmp280_pressure", "compost_temp_delta", "compost_temp_roll_mean",
    "temp_gap_udara_kompos",
]


def run_decision_tree_analysis(df_labeled, df_live, output_dir):
    print("\n=== 2. Klasifikasi Fase Kompos (Decision Tree) ===")

    df_feat = engineer_features(df_labeled)
    X = df_feat[FEATURE_COLUMNS]
    y = df_feat["fase"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    clf = DecisionTreeClassifier(
        max_depth=6, min_samples_leaf=5, random_state=42, class_weight="balanced"
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"  ✓ Akurasi pada data uji: {acc * 100:.2f}%")
    print("\n  Laporan klasifikasi:")
    print(classification_report(y_test, y_pred, zero_division=0))

    labels = sorted(y.unique(), key=lambda l: list(y.unique()).index(l))
    cm = confusion_matrix(y_test, y_pred, labels=clf.classes_)

    # ---- Visualisasi: Confusion Matrix ----
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", cbar=True,
                xticklabels=clf.classes_, yticklabels=clf.classes_, ax=ax)
    ax.set_title("Confusion Matrix — Klasifikasi Fase Kompos", fontsize=12, color=NAVY, weight="bold")
    ax.set_xlabel("Prediksi")
    ax.set_ylabel("Aktual")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    fig.tight_layout()
    out_cm = os.path.join(output_dir, "02_confusion_matrix.png")
    fig.savefig(out_cm, dpi=150)
    plt.close(fig)
    print(f"  ✓ Grafik disimpan: {out_cm}")

    # ---- Visualisasi: Feature Importance ----
    importance = pd.Series(clf.feature_importances_, index=FEATURE_COLUMNS).sort_values()
    fig, ax = plt.subplots(figsize=(8, 5))
    importance.plot(kind="barh", color=BLUE, ax=ax)
    ax.set_title("Feature Importance — Decision Tree", fontsize=12, color=NAVY, weight="bold")
    ax.set_xlabel("Tingkat Kepentingan")
    fig.tight_layout()
    out_imp = os.path.join(output_dir, "03_feature_importance.png")
    fig.savefig(out_imp, dpi=150)
    plt.close(fig)
    print(f"  ✓ Grafik disimpan: {out_imp}")

    # ---- Visualisasi: Struktur Pohon Keputusan ----
    fig, ax = plt.subplots(figsize=(22, 11))
    plot_tree(clf, feature_names=FEATURE_COLUMNS, class_names=clf.classes_,
              filled=True, rounded=True, fontsize=8, max_depth=3, ax=ax)
    ax.set_title("Struktur Decision Tree (dipangkas hingga depth=3 untuk keterbacaan)",
                 fontsize=13, color=NAVY, weight="bold")
    fig.tight_layout()
    out_tree = os.path.join(output_dir, "04_decision_tree.png")
    fig.savefig(out_tree, dpi=150)
    plt.close(fig)
    print(f"  ✓ Grafik disimpan: {out_tree}")

    # ---- Terapkan model ke data live (jika ada) untuk prediksi fase saat ini ----
    live_predictions = None
    if df_live is not None and not df_live.empty:
        df_live_feat = engineer_features(df_live)
        X_live = df_live_feat[FEATURE_COLUMNS]
        pred_fase = clf.predict(X_live)
        pred_proba = clf.predict_proba(X_live).max(axis=1)
        df_live_feat["fase_prediksi"] = pred_fase
        df_live_feat["keyakinan"] = pred_proba
        live_predictions = df_live_feat[["timestamp", "compost_temp", "fase_prediksi", "keyakinan"]]

        latest = live_predictions.iloc[-1]
        print(f"\n  → Prediksi fase TERKINI (data live server): "
              f"{latest['fase_prediksi']} (keyakinan {latest['keyakinan']*100:.1f}%, "
              f"suhu {latest['compost_temp']}°C)")

        out_live_csv = os.path.join(output_dir, "prediksi_fase_live.csv")
        live_predictions.to_csv(out_live_csv, index=False)
        print(f"  ✓ Prediksi fase data live disimpan: {out_live_csv}")

    return {"model": clf, "accuracy": acc, "live_predictions": live_predictions}


# ============================= BAGIAN 3: VISUALISASI RINGKASAN =============================
def plot_phase_timeline(df_labeled, output_dir):
    fig, ax = plt.subplots(figsize=(13, 5.5))
    fases = list(df_labeled["fase"].unique())
    color_map = {f: PALETTE[i % len(PALETTE)] for i, f in enumerate(fases)}

    for fase in fases:
        subset = df_labeled[df_labeled["fase"] == fase]
        ax.scatter(subset["timestamp"], subset["compost_temp"],
                   s=10, color=color_map[fase], label=fase)

    ax.axhspan(45, 65, color="gray", alpha=0.08, label="Rentang setpoint kontrol")
    ax.set_title("Timeline Suhu Kompos per Fase (Data Simulasi)", fontsize=13, color=NAVY, weight="bold")
    ax.set_xlabel("Waktu")
    ax.set_ylabel("Suhu Kompos (°C)")
    ax.legend(loc="upper right", fontsize=8, ncol=2)
    fig.autofmt_xdate()
    fig.tight_layout()
    out_path = os.path.join(output_dir, "00_timeline_fase.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"\n✓ Grafik timeline fase disimpan: {out_path}")


# ============================= MAIN =============================
def main():
    parser = argparse.ArgumentParser(description="Analisis ARIMA & Decision Tree data KomposIoT")
    parser.add_argument("--csv", default="kompos_6fase_simulasi.csv",
                         help="CSV historis berlabel fase (hasil simulate_6_fase_kompos.py)")
    parser.add_argument("--api-url", default=None,
                         help="URL server API PHP untuk mengambil data live (opsional)")
    parser.add_argument("--api-key", default="", help="API key jika diaktifkan di server")
    parser.add_argument("--device-id", default="KOMPOS-SIM-01", help="device_id yang dianalisis")
    parser.add_argument("--forecast-steps", type=int, default=24,
                         help="Jumlah langkah peramalan ARIMA ke depan")
    parser.add_argument("--output-dir", default="hasil_analisis",
                         help="Folder output untuk semua grafik PNG")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print("=== Memuat data ===")
    df_labeled = load_labeled_csv(args.csv)
    print(f"  ✓ CSV historis berlabel dimuat: {len(df_labeled)} baris, "
          f"{df_labeled['fase'].nunique()} fase")

    df_live = None
    if args.api_url:
        print(f"  Mengambil data live dari server: {args.api_url} ...")
        df_live = fetch_from_api(args.api_url, args.device_id, args.api_key or None)
        if df_live is not None:
            print(f"  ✓ Data live diterima: {len(df_live)} baris")

    # Sumber data untuk ARIMA: live jika tersedia & cukup panjang, jika tidak pakai CSV
    df_for_arima = df_live if (df_live is not None and len(df_live) >= 20) else df_labeled
    if df_for_arima is df_labeled:
        print("  (ARIMA memakai data CSV historis karena data live tidak tersedia/terlalu pendek)")

    plot_phase_timeline(df_labeled, args.output_dir)
    arima_result = run_arima_analysis(df_for_arima, args.output_dir, args.forecast_steps)
    tree_result = run_decision_tree_analysis(df_labeled, df_live, args.output_dir)

    # ---- Ringkasan akhir ----
    print("\n" + "=" * 60)
    print("RINGKASAN HASIL ANALISIS")
    print("=" * 60)
    print(f"ARIMA          : orde {arima_result['order']}, RMSE={arima_result['rmse']:.3f}°C, "
          f"MAPE={arima_result['mape']:.2f}%")
    print(f"Decision Tree  : akurasi klasifikasi fase = {tree_result['accuracy']*100:.2f}%")
    print(f"Semua grafik   : folder '{args.output_dir}/'")
    print("=" * 60)


if __name__ == "__main__":
    main()

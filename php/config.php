<?php
/**
 * KomposIoT - Konfigurasi Server API
 * Penyimpanan data menggunakan file JSON (tanpa database).
 */

// Path file penyimpanan data (array JSON)
define('DATA_FILE', __DIR__ . '/data/sensor_data.json');

// Batas maksimum record yang disimpan (agar file tidak membengkak tanpa batas)
// Set 0 untuk tidak membatasi.
define('MAX_RECORDS', 20000);

// Kunci API sederhana (opsional). Kosongkan ("") untuk menonaktifkan validasi.
define('API_KEY', '');

// Zona waktu
date_default_timezone_set('Asia/Makassar'); // WITA (sesuaikan dengan lokasi: WIB=Asia/Jakarta, WIT=Asia/Jayapura)

/**
 * Memastikan file data ada dan berformat array JSON valid.
 */
function ensure_data_file() {
    if (!file_exists(DATA_FILE)) {
        $dir = dirname(DATA_FILE);
        if (!is_dir($dir)) {
            mkdir($dir, 0775, true);
        }
        file_put_contents(DATA_FILE, json_encode([]));
    }
}

/**
 * Membaca seluruh data dari file JSON dengan file locking (shared lock).
 */
function read_data() {
    ensure_data_file();
    $fp = fopen(DATA_FILE, 'r');
    if (!$fp) return [];

    flock($fp, LOCK_SH);
    $content = stream_get_contents($fp);
    flock($fp, LOCK_UN);
    fclose($fp);

    $data = json_decode($content, true);
    return is_array($data) ? $data : [];
}

/**
 * Menulis seluruh data ke file JSON dengan exclusive lock (aman untuk konkurensi).
 */
function write_data(array $data) {
    ensure_data_file();
    $fp = fopen(DATA_FILE, 'c');
    if (!$fp) return false;

    flock($fp, LOCK_EX);
    ftruncate($fp, 0);
    rewind($fp);
    fwrite($fp, json_encode($data, JSON_PRETTY_PRINT));
    fflush($fp);
    flock($fp, LOCK_UN);
    fclose($fp);
    return true;
}

/**
 * Kirim response JSON standar lalu keluar.
 */
function respond($success, $message, $data = null, $httpCode = 200) {
    http_response_code($httpCode);
    header('Content-Type: application/json');
    echo json_encode([
        'success' => $success,
        'message' => $message,
        'data'    => $data,
    ], JSON_PRETTY_PRINT);
    exit;
}

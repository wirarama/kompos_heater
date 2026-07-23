<?php
/**
 * KomposIoT - API Pengaturan Node
 * ------------------------------------------------------------------
 * Menyimpan & membaca parameter kontrol per device_id (setpoint suhu,
 * hysteresis, ambang kelembaban untuk kipas, dsb) — file JSON terpisah
 * dari data sensor.
 *
 * GET  /settings.php?device_id=KOMPOS-NODE-01
 *      -> ambil pengaturan device tsb (default jika belum pernah diset)
 *
 * GET  /settings.php
 *      -> ambil semua pengaturan yang tersimpan (semua device)
 *
 * POST /settings.php
 *      Body (JSON):
 *      {
 *        "device_id": "KOMPOS-NODE-01",
 *        "setpoint_low": 45.0,
 *        "setpoint_high": 65.0,
 *        "hysteresis": 2.0,
 *        "humidity_fan_threshold": 85.0
 *      }
 *      -> simpan/perbarui pengaturan device tsb
 *
 * Catatan: firmware perlu di-update agar melakukan polling endpoint ini
 * secara berkala (mis. tiap 60 detik) untuk menerapkan pengaturan baru.
 * ------------------------------------------------------------------
 */

require_once __DIR__ . '/config.php';

define('SETTINGS_FILE', __DIR__ . '/data/device_settings.json');

header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, X-API-Key');

$method = $_SERVER['REQUEST_METHOD'];
if ($method === 'OPTIONS') {
    http_response_code(204);
    exit;
}

if (API_KEY !== '') {
    $headers = getallheaders();
    $key = $headers['X-API-Key'] ?? ($_GET['api_key'] ?? '');
    if ($key !== API_KEY) {
        respond(false, 'API key tidak valid.', null, 401);
    }
}

$DEFAULT_SETTINGS = [
    'setpoint_low'           => 45.0,
    'setpoint_high'          => 65.0,
    'hysteresis'             => 2.0,
    'humidity_fan_threshold' => 85.0,
    'updated_at'             => null,
];

function ensure_settings_file() {
    if (!file_exists(SETTINGS_FILE)) {
        $dir = dirname(SETTINGS_FILE);
        if (!is_dir($dir)) mkdir($dir, 0775, true);
        file_put_contents(SETTINGS_FILE, json_encode(new stdClass()));
    }
}

function read_settings() {
    ensure_settings_file();
    $fp = fopen(SETTINGS_FILE, 'r');
    flock($fp, LOCK_SH);
    $content = stream_get_contents($fp);
    flock($fp, LOCK_UN);
    fclose($fp);
    $data = json_decode($content, true);
    return is_array($data) ? $data : [];
}

function write_settings(array $all) {
    ensure_settings_file();
    $fp = fopen(SETTINGS_FILE, 'c');
    flock($fp, LOCK_EX);
    ftruncate($fp, 0);
    rewind($fp);
    fwrite($fp, json_encode($all, JSON_PRETTY_PRINT));
    fflush($fp);
    flock($fp, LOCK_UN);
    fclose($fp);
}

if ($method === 'GET') {
    $all = read_settings();
    $deviceId = $_GET['device_id'] ?? null;

    if ($deviceId) {
        $settings = $all[$deviceId] ?? $GLOBALS['DEFAULT_SETTINGS'];
        respond(true, "Pengaturan untuk $deviceId.", $settings);
    } else {
        respond(true, 'Seluruh pengaturan device.', $all);
    }
} elseif ($method === 'POST') {
    $raw = file_get_contents('php://input');
    $input = json_decode($raw, true);

    if (!is_array($input) || empty($input['device_id'])) {
        respond(false, 'Body JSON tidak valid atau device_id kosong.', null, 400);
    }

    $deviceId = (string) $input['device_id'];
    $all = read_settings();
    $current = $all[$deviceId] ?? $GLOBALS['DEFAULT_SETTINGS'];

    foreach (['setpoint_low', 'setpoint_high', 'hysteresis', 'humidity_fan_threshold'] as $field) {
        if (isset($input[$field])) {
            $current[$field] = floatval($input[$field]);
        }
    }
    $current['updated_at'] = date('Y-m-d H:i:s');

    if ($current['setpoint_low'] >= $current['setpoint_high']) {
        respond(false, 'setpoint_low harus lebih kecil dari setpoint_high.', null, 422);
    }

    $all[$deviceId] = $current;
    write_settings($all);

    respond(true, "Pengaturan untuk $deviceId berhasil disimpan.", $current);
} else {
    respond(false, 'Method tidak didukung.', null, 405);
}

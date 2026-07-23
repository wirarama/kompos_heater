<?php
/**
 * KomposIoT - API Server
 * ------------------------------------------------------------------
 * Menerima data sensor dari firmware (POST, JSON) dan menyediakan
 * query data (GET) — seluruh penyimpanan menggunakan file JSON.
 *
 * ENDPOINT PENERIMAAN DATA
 *   POST /index.php
 *   Body (JSON):
 *   {
 *     "device_id": "KOMPOS-NODE-01",
 *     "compost_temp": 52.3,
 *     "bmp280_temp": 29.1,
 *     "bmp280_pressure": 1009.4,
 *     "aht20_temp": 29.4,
 *     "aht20_humidity": 68.2,
 *     "heater_status": "heating",
 *     "heater_pwm": 180,
 *     "fan_status": "on",
 *     "fan_pwm": 200,
 *     "uptime_ms": 123456
 *   }
 *
 * ENDPOINT QUERY DATA (GET, parameter ?action=...)
 *   ?action=latest                         -> 1 data terbaru
 *   ?action=latest&limit=20                -> N data terbaru
 *   ?action=all&limit=100&offset=0         -> semua data (dengan paginasi)
 *   ?action=range&start=YYYY-MM-DD&end=YYYY-MM-DD  -> filter rentang tanggal
 *   ?action=device&device_id=KOMPOS-NODE-01&limit=50 -> filter per device
 *   ?action=stats&start=&end=&device_id=   -> statistik min/max/avg
 *   ?action=count                          -> jumlah total record
 *   (tanpa action, GET)                    -> sama seperti action=latest&limit=50
 *
 * ------------------------------------------------------------------
 * Author: Wirarama Wedashwara Wyrawan - Universitas Mataram
 */

require_once __DIR__ . '/config.php';

header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, X-API-Key');

$method = $_SERVER['REQUEST_METHOD'];

if ($method === 'OPTIONS') {
    http_response_code(204);
    exit;
}

// ---- Validasi API key opsional ----
if (API_KEY !== '') {
    $headers = getallheaders();
    $key = $headers['X-API-Key'] ?? ($_GET['api_key'] ?? '');
    if ($key !== API_KEY) {
        respond(false, 'API key tidak valid.', null, 401);
    }
}

if ($method === 'POST') {
    handle_post();
} elseif ($method === 'GET') {
    handle_get();
} else {
    respond(false, 'Method tidak didukung.', null, 405);
}

// =====================================================================
// PENERIMAAN DATA (POST)
// =====================================================================
function handle_post() {
    $raw = file_get_contents('php://input');
    $input = json_decode($raw, true);

    if (!is_array($input)) {
        respond(false, 'Body JSON tidak valid.', null, 400);
    }

    if (empty($input['device_id'])) {
        respond(false, 'Field device_id wajib diisi.', null, 422);
    }

    $data = read_data();

    $newId = count($data) > 0 ? (max(array_column($data, 'id')) + 1) : 1;

    // Timestamp default = waktu server saat diterima. Namun jika client
    // (misal skrip simulasi/backfill data historis) mengirim field
    // "timestamp" yang valid, gunakan nilai tsb agar urutan waktu data
    // historis tetap benar untuk keperluan analisis time-series.
    $timestamp = date('Y-m-d H:i:s');
    if (!empty($input['timestamp']) && strtotime($input['timestamp']) !== false) {
        $timestamp = date('Y-m-d H:i:s', strtotime($input['timestamp']));
    }

    $record = [
        'id'              => $newId,
        'timestamp'       => $timestamp,
        'device_id'       => (string) $input['device_id'],
        'compost_temp'    => isset($input['compost_temp']) ? floatval($input['compost_temp']) : null,
        'bmp280_temp'     => isset($input['bmp280_temp']) ? floatval($input['bmp280_temp']) : null,
        'bmp280_pressure' => isset($input['bmp280_pressure']) ? floatval($input['bmp280_pressure']) : null,
        'aht20_temp'      => isset($input['aht20_temp']) ? floatval($input['aht20_temp']) : null,
        'aht20_humidity'  => isset($input['aht20_humidity']) ? floatval($input['aht20_humidity']) : null,
        'heater_status'   => $input['heater_status'] ?? 'idle',
        'heater_pwm'      => isset($input['heater_pwm']) ? intval($input['heater_pwm']) : 0,
        'fan_status'      => $input['fan_status'] ?? 'off',
        'fan_pwm'         => isset($input['fan_pwm']) ? intval($input['fan_pwm']) : 0,
        'uptime_ms'       => isset($input['uptime_ms']) ? intval($input['uptime_ms']) : null,
    ];

    $data[] = $record;

    // Batasi jumlah record tersimpan jika MAX_RECORDS > 0
    if (MAX_RECORDS > 0 && count($data) > MAX_RECORDS) {
        $data = array_slice($data, count($data) - MAX_RECORDS);
    }

    if (!write_data($data)) {
        respond(false, 'Gagal menyimpan data ke file JSON.', null, 500);
    }

    respond(true, 'Data berhasil disimpan.', $record, 201);
}

// =====================================================================
// QUERY DATA (GET)
// =====================================================================
function handle_get() {
    $action = $_GET['action'] ?? 'latest';
    $data = read_data();

    switch ($action) {
        case 'latest':
            $limit = isset($_GET['limit']) ? max(1, intval($_GET['limit'])) : 1;
            $result = array_slice(array_reverse($data), 0, $limit);
            respond(true, 'Data terbaru.', $result);
            break;

        case 'all':
            $limit  = isset($_GET['limit']) ? max(1, intval($_GET['limit'])) : 100;
            $offset = isset($_GET['offset']) ? max(0, intval($_GET['offset'])) : 0;
            $reversed = array_reverse($data); // terbaru dulu
            $result = array_slice($reversed, $offset, $limit);
            respond(true, 'Semua data (dengan paginasi).', [
                'total'   => count($data),
                'limit'   => $limit,
                'offset'  => $offset,
                'records' => $result,
            ]);
            break;

        case 'range':
            $start = $_GET['start'] ?? null;
            $end   = $_GET['end'] ?? null;
            if (!$start || !$end) {
                respond(false, 'Parameter start dan end wajib diisi (format: YYYY-MM-DD).', null, 400);
            }
            $startTs = strtotime($start . ' 00:00:00');
            $endTs   = strtotime($end . ' 23:59:59');

            $filtered = array_values(array_filter($data, function ($row) use ($startTs, $endTs) {
                $ts = strtotime($row['timestamp']);
                return $ts >= $startTs && $ts <= $endTs;
            }));

            respond(true, "Data rentang $start s/d $end.", [
                'total'   => count($filtered),
                'records' => array_reverse($filtered),
            ]);
            break;

        case 'device':
            $deviceId = $_GET['device_id'] ?? null;
            $limit = isset($_GET['limit']) ? max(1, intval($_GET['limit'])) : 100;
            if (!$deviceId) {
                respond(false, 'Parameter device_id wajib diisi.', null, 400);
            }
            $filtered = array_values(array_filter($data, function ($row) use ($deviceId) {
                return $row['device_id'] === $deviceId;
            }));
            $result = array_slice(array_reverse($filtered), 0, $limit);
            respond(true, "Data untuk device $deviceId.", [
                'total'   => count($filtered),
                'records' => $result,
            ]);
            break;

        case 'stats':
            $filtered = $data;

            if (!empty($_GET['device_id'])) {
                $deviceId = $_GET['device_id'];
                $filtered = array_values(array_filter($filtered, function ($row) use ($deviceId) {
                    return $row['device_id'] === $deviceId;
                }));
            }
            if (!empty($_GET['start']) && !empty($_GET['end'])) {
                $startTs = strtotime($_GET['start'] . ' 00:00:00');
                $endTs   = strtotime($_GET['end'] . ' 23:59:59');
                $filtered = array_values(array_filter($filtered, function ($row) use ($startTs, $endTs) {
                    $ts = strtotime($row['timestamp']);
                    return $ts >= $startTs && $ts <= $endTs;
                }));
            }

            respond(true, 'Statistik data.', compute_stats($filtered));
            break;

        case 'count':
            respond(true, 'Jumlah total record.', ['total' => count($data)]);
            break;

        case 'devices':
            $deviceIds = array_values(array_unique(array_column($data, 'device_id')));
            sort($deviceIds);
            respond(true, 'Daftar device.', $deviceIds);
            break;

        default:
            respond(false, "Action '$action' tidak dikenali.", null, 400);
    }
}

// =====================================================================
// UTILITAS STATISTIK
// =====================================================================
function compute_stats(array $rows) {
    if (empty($rows)) {
        return ['total_records' => 0];
    }

    $fields = ['compost_temp', 'bmp280_temp', 'bmp280_pressure', 'aht20_temp', 'aht20_humidity'];
    $stats = ['total_records' => count($rows)];

    foreach ($fields as $field) {
        $values = array_filter(array_column($rows, $field), function ($v) {
            return $v !== null;
        });

        if (empty($values)) {
            $stats[$field] = ['min' => null, 'max' => null, 'avg' => null];
            continue;
        }

        $stats[$field] = [
            'min' => round(min($values), 2),
            'max' => round(max($values), 2),
            'avg' => round(array_sum($values) / count($values), 2),
        ];
    }

    $heatingCount = count(array_filter($rows, fn($r) => ($r['heater_status'] ?? '') === 'heating'));
    $coolingCount = count(array_filter($rows, fn($r) => ($r['heater_status'] ?? '') === 'cooling'));
    $fanOnCount   = count(array_filter($rows, fn($r) => ($r['fan_status'] ?? '') === 'on'));

    $stats['heater_summary'] = [
        'heating_count' => $heatingCount,
        'cooling_count' => $coolingCount,
        'idle_count'    => count($rows) - $heatingCount - $coolingCount,
    ];
    $stats['fan_summary'] = [
        'on_count'  => $fanOnCount,
        'off_count' => count($rows) - $fanOnCount,
    ];

    return $stats;
}

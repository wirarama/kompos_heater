/*
 * =====================================================================
 * KomposIoT - Firmware Wemos D1 R32 (ESP32)
 * Kendali Suhu Kompos & Monitoring Lingkungan
 * =====================================================================
 * Sensor  : DS18B20  -> suhu inti kompos (kontrol utama)
 *           BMP280   -> suhu & tekanan udara sekitar
 *           AHT20    -> suhu & kelembaban udara sekitar
 * Aktuator: BTS7960  -> kendali elemen pemanas / Peltier (heating & cooling)
 *           L298N    -> kendali kipas aerasi/pendingin
 *
 * Author  : Wirarama Wedashwara Wyrawan - Universitas Mataram
 * =====================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>
#include <Adafruit_AHTX0.h>

// ============================= KONFIGURASI ============================
// ---- WiFi ----
const char* WIFI_SSID     = "NAMA_WIFI_ANDA";
const char* WIFI_PASSWORD = "PASSWORD_WIFI_ANDA";

// ---- Server API (PHP, penyimpanan JSON) ----
const char* API_HOST      = "http://192.168.1.100/kompos_api"; // ganti sesuai server
const char* API_ENDPOINT  = "/index.php";
const char* DEVICE_ID     = "KOMPOS-NODE-01";

// ---- Interval ----
const unsigned long SENSOR_READ_INTERVAL = 5000;    // baca sensor tiap 5 detik
const unsigned long DATA_SEND_INTERVAL   = 30000;   // kirim data tiap 30 detik
const unsigned long CONTROL_INTERVAL     = 5000;    // evaluasi kontrol tiap 5 detik

// ---- Target Suhu Kompos (fase termofilik umum: 45-65 C) ----
float SETPOINT_LOW   = 45.0;   // di bawah ini -> heater ON (heating)
float SETPOINT_HIGH  = 65.0;   // di atas ini  -> cooling / fan aktif penuh
float HYSTERESIS     = 2.0;    // celah agar tidak sering switching

// ---- Batas keamanan kelembaban udara (opsional, mempengaruhi kipas) ----
float HUMIDITY_FAN_THRESHOLD = 85.0; // kelembaban tinggi -> bantu aerasi kipas

// ========================= DEFINISI PIN (Wemos D1 R32 / ESP32) =========
// DS18B20 (OneWire)
#define PIN_DS18B20      4   // D2

// I2C (BMP280 + AHT20 berbagi bus)
#define PIN_I2C_SDA      21
#define PIN_I2C_SCL      22

// BTS7960 - kendali pemanas/Peltier (dua arah: heating & cooling)
#define PIN_BTS_RPWM     25  // arah "heating"
#define PIN_BTS_LPWM     26  // arah "cooling"
#define PIN_BTS_R_EN     27
#define PIN_BTS_L_EN     14

// L298N - kendali kipas aerasi/pendingin (satu arah, kecepatan variabel)
#define PIN_L298_ENA     32  // PWM kecepatan kipas
#define PIN_L298_IN1     33
#define PIN_L298_IN2     13

// LED indikator status (built-in)
#define PIN_STATUS_LED   2

// ---- PWM channel & konfigurasi (ESP32 LEDC) ----
#define PWM_FREQ         5000
#define PWM_RESOLUTION   8      // 0-255
#define CH_BTS_RPWM      0
#define CH_BTS_LPWM      1
#define CH_FAN_ENA       2

// ============================= OBJEK SENSOR =============================
OneWire oneWire(PIN_DS18B20);
DallasTemperature ds18b20(&oneWire);

Adafruit_BMP280 bmp280;
Adafruit_AHTX0 aht20;
bool bmpOk = false;
bool ahtOk = false;

// ============================= STATE GLOBAL =============================
float compostTemp   = NAN;
float bmpTemp       = NAN;
float bmpPressure   = NAN;
float ahtTemp       = NAN;
float ahtHumidity   = NAN;

String heaterStatus = "idle";   // "heating" | "cooling" | "idle"
int    heaterPWM    = 0;        // 0-255
String fanStatus    = "off";    // "on" | "off"
int    fanPWM       = 0;        // 0-255

unsigned long lastSensorRead = 0;
unsigned long lastDataSend   = 0;
unsigned long lastControl    = 0;

// ============================= SETUP =============================
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=== KomposIoT - Wemos D1 R32 ===");

  pinMode(PIN_STATUS_LED, OUTPUT);
  digitalWrite(PIN_STATUS_LED, LOW);

  setupActuators();
  setupSensors();
  connectWiFi();

  Serial.println("Setup selesai.\n");
}

// ============================= LOOP =============================
void loop() {
  unsigned long now = millis();

  if (now - lastSensorRead >= SENSOR_READ_INTERVAL) {
    lastSensorRead = now;
    readAllSensors();
  }

  if (now - lastControl >= CONTROL_INTERVAL) {
    lastControl = now;
    runControlLogic();
  }

  if (now - lastDataSend >= DATA_SEND_INTERVAL) {
    lastDataSend = now;
    sendDataToServer();
  }

  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }
}

// ============================= SETUP AKTUATOR =============================
void setupActuators() {
  // BTS7960
  pinMode(PIN_BTS_R_EN, OUTPUT);
  pinMode(PIN_BTS_L_EN, OUTPUT);
  digitalWrite(PIN_BTS_R_EN, HIGH);
  digitalWrite(PIN_BTS_L_EN, HIGH);

  ledcSetup(CH_BTS_RPWM, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(PIN_BTS_RPWM, CH_BTS_RPWM);
  ledcSetup(CH_BTS_LPWM, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(PIN_BTS_LPWM, CH_BTS_LPWM);
  ledcWrite(CH_BTS_RPWM, 0);
  ledcWrite(CH_BTS_LPWM, 0);

  // L298N (fan)
  pinMode(PIN_L298_IN1, OUTPUT);
  pinMode(PIN_L298_IN2, OUTPUT);
  digitalWrite(PIN_L298_IN1, HIGH);
  digitalWrite(PIN_L298_IN2, LOW);

  ledcSetup(CH_FAN_ENA, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(PIN_L298_ENA, CH_FAN_ENA);
  ledcWrite(CH_FAN_ENA, 0);
}

// ============================= SETUP SENSOR =============================
void setupSensors() {
  ds18b20.begin();
  Serial.print("DS18B20 ditemukan: ");
  Serial.println(ds18b20.getDeviceCount());

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

  bmpOk = bmp280.begin(0x76) || bmp280.begin(0x77);
  if (bmpOk) {
    bmp280.setSampling(Adafruit_BMP280::MODE_NORMAL,
                        Adafruit_BMP280::SAMPLING_X2,
                        Adafruit_BMP280::SAMPLING_X16,
                        Adafruit_BMP280::FILTER_X16,
                        Adafruit_BMP280::STANDBY_MS_500);
    Serial.println("BMP280 OK");
  } else {
    Serial.println("BMP280 TIDAK ditemukan!");
  }

  ahtOk = aht20.begin();
  Serial.println(ahtOk ? "AHT20 OK" : "AHT20 TIDAK ditemukan!");
}

// ============================= WIFI =============================
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.print("Menghubungkan WiFi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempt = 0;
  while (WiFi.status() != WL_CONNECTED && attempt < 20) {
    delay(500);
    Serial.print(".");
    attempt++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi terhubung. IP: " + WiFi.localIP().toString());
    digitalWrite(PIN_STATUS_LED, HIGH);
  } else {
    Serial.println("\nGagal konek WiFi, akan dicoba lagi.");
    digitalWrite(PIN_STATUS_LED, LOW);
  }
}

// ============================= BACA SENSOR =============================
void readAllSensors() {
  // DS18B20
  ds18b20.requestTemperatures();
  float t = ds18b20.getTempCByIndex(0);
  if (t != DEVICE_DISCONNECTED_C) {
    compostTemp = t;
  } else {
    Serial.println("Peringatan: DS18B20 gagal dibaca");
  }

  // BMP280
  if (bmpOk) {
    bmpTemp     = bmp280.readTemperature();
    bmpPressure = bmp280.readPressure() / 100.0F; // hPa
  }

  // AHT20
  if (ahtOk) {
    sensors_event_t humEvt, tempEvt;
    aht20.getEvent(&humEvt, &tempEvt);
    ahtTemp     = tempEvt.temperature;
    ahtHumidity = humEvt.relative_humidity;
  }

  Serial.printf("Kompos: %.2fC | BMP280: %.2fC / %.1fhPa | AHT20: %.2fC / %.1f%%RH\n",
                compostTemp, bmpTemp, bmpPressure, ahtTemp, ahtHumidity);
}

// ============================= LOGIKA KONTROL =============================
// Hysteresis dua arah untuk BTS7960 (heating/cooling) + kipas L298N
void runControlLogic() {
  if (isnan(compostTemp)) {
    // Data tidak valid -> matikan semua aktuator demi keamanan
    setHeater("idle", 0);
    setFan("off", 0);
    return;
  }

  // ---- Kendali suhu kompos via BTS7960 ----
  if (compostTemp < (SETPOINT_LOW - HYSTERESIS)) {
    // Terlalu dingin -> heating
    int pwm = mapTempToPWM(SETPOINT_LOW - compostTemp, 0, 10, 120, 255);
    setHeater("heating", pwm);
  } else if (compostTemp > (SETPOINT_HIGH + HYSTERESIS)) {
    // Terlalu panas -> cooling (Peltier arah balik)
    int pwm = mapTempToPWM(compostTemp - SETPOINT_HIGH, 0, 10, 120, 255);
    setHeater("cooling", pwm);
  } else if (compostTemp >= SETPOINT_LOW && compostTemp <= SETPOINT_HIGH) {
    // Dalam rentang aman -> idle
    setHeater("idle", 0);
  }
  // Di zona hysteresis (di antara low-hyst dan low, atau high dan high+hyst):
  // pertahankan status aktuator sebelumnya (tidak diubah) untuk mencegah chattering

  // ---- Kendali kipas aerasi/pendingin ----
  bool needCoolingAssist = compostTemp > SETPOINT_HIGH;
  bool needHumidityVent  = (!isnan(ahtHumidity)) && (ahtHumidity > HUMIDITY_FAN_THRESHOLD);

  if (needCoolingAssist || needHumidityVent) {
    int fanSpeed = needCoolingAssist ? 255 : 160;
    setFan("on", fanSpeed);
  } else {
    setFan("off", 0);
  }
}

int mapTempToPWM(float diff, float inMin, float inMax, int outMin, int outMax) {
  diff = constrain(diff, inMin, inMax);
  return (int)((diff - inMin) * (outMax - outMin) / (inMax - inMin) + outMin);
}

void setHeater(String status, int pwm) {
  heaterStatus = status;
  heaterPWM = pwm;

  if (status == "heating") {
    ledcWrite(CH_BTS_LPWM, 0);
    ledcWrite(CH_BTS_RPWM, pwm);
  } else if (status == "cooling") {
    ledcWrite(CH_BTS_RPWM, 0);
    ledcWrite(CH_BTS_LPWM, pwm);
  } else {
    ledcWrite(CH_BTS_RPWM, 0);
    ledcWrite(CH_BTS_LPWM, 0);
  }
}

void setFan(String status, int pwm) {
  fanStatus = status;
  fanPWM = pwm;
  ledcWrite(CH_FAN_ENA, pwm);
}

// ============================= KIRIM DATA KE SERVER =============================
void sendDataToServer() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi tidak terhubung, lewati pengiriman data.");
    return;
  }

  HTTPClient http;
  String url = String(API_HOST) + String(API_ENDPOINT);
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<512> doc;
  doc["device_id"]        = DEVICE_ID;
  doc["compost_temp"]     = isnan(compostTemp) ? nullptr : compostTemp;
  doc["bmp280_temp"]      = isnan(bmpTemp) ? nullptr : bmpTemp;
  doc["bmp280_pressure"]  = isnan(bmpPressure) ? nullptr : bmpPressure;
  doc["aht20_temp"]       = isnan(ahtTemp) ? nullptr : ahtTemp;
  doc["aht20_humidity"]   = isnan(ahtHumidity) ? nullptr : ahtHumidity;
  doc["heater_status"]    = heaterStatus;
  doc["heater_pwm"]       = heaterPWM;
  doc["fan_status"]       = fanStatus;
  doc["fan_pwm"]          = fanPWM;
  doc["uptime_ms"]        = millis();

  String payload;
  serializeJson(doc, payload);

  int httpCode = http.POST(payload);

  if (httpCode > 0) {
    Serial.printf("Data terkirim. HTTP %d: %s\n", httpCode, http.getString().c_str());
  } else {
    Serial.printf("Gagal mengirim data: %s\n", http.errorToString(httpCode).c_str());
  }

  http.end();
}

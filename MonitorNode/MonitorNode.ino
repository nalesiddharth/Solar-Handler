/*
  MonitorNode.ino
  ESP32 monitoring node: reads DHT22, BH1750 and analog voltage divider and uploads readings to Firebase.

  IMPORTANT: replace placeholders below with your WiFi and Firebase configuration before flashing.
  For public repos, DO NOT commit secrets. Consider using a gitignored `secrets.h` or build-time defines.

  Wiring summary:
  - DHT22 data -> GPIO4
  - BH1750 -> I2C SDA = GPIO21, SCL = GPIO22
  - Panel voltage sense -> GPIO34 (ADC)
*/

#include <WiFi.h>
#include <Firebase_ESP_Client.h>
#include <DHT.h>
#include <Wire.h>
#include <BH1750.h>
#include "time.h"

// WiFi credentials (REPLACE BEFORE USE)
#define WIFI_SSID "<YOUR_WIFI_SSID>"
#define WIFI_PASSWORD "<YOUR_WIFI_PASSWORD>"

// Firebase credentials (REPLACE BEFORE USE)
#define API_KEY "<YOUR_FIREBASE_API_KEY>"
#define DATABASE_URL "https://<YOUR_PROJECT_ID>.firebaseio.com" // no trailing slash

FirebaseData fbdo;
FirebaseAuth auth;
FirebaseConfig config;

// Time
const char* ntpServer = "pool.ntp.org";
const long gmtOffset_sec = 19800; // IST
const int daylightOffset_sec = 0;

// Sensor setup
DHT dht(4, DHT22); // GPIO 4
BH1750 lightMeter;
const int voltagePin = 34; // Analog input for voltage

void connectToWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected.");
}

void setupTime() {
  configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);
  while (time(nullptr) < 100000) {
    Serial.println("Waiting for NTP sync...");
    delay(1000);
  }
  Serial.println("Time synced.");
}

void setup() {
  Serial.begin(115200);
  dht.begin();
  Wire.begin(21, 22); // SDA, SCL for BH1750
  lightMeter.begin();

  connectToWiFi();
  setupTime();

  config.api_key = API_KEY;
  config.database_url = DATABASE_URL;

  // Replace with your Firebase auth credentials or configure DB rules accordingly.
  auth.user.email = "<YOUR_FIREBASE_USER_EMAIL>";
  auth.user.password = "<YOUR_FIREBASE_USER_PASSWORD>";

  Firebase.begin(&config, &auth);
  Firebase.reconnectWiFi(true);
}

void loop() {
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();
  float lux = lightMeter.readLightLevel();

  int raw = analogRead(voltagePin);
  float analogVoltage = (raw / 4095.0) * 3.3;
  float solarVoltage = analogVoltage * (25.0 / 3.3); // Adjusted for your voltage divider

  if (isnan(temperature) || isnan(humidity) || isnan(lux)) {
    Serial.println("Sensor read failed.");
    delay(60000);
    return;
  }

  time_t now = time(nullptr);
  String timestamp = String(now);
  String path = "/solar_data/" + timestamp;

  Serial.printf("Uploading data to %s\n", path.c_str());

  if (!Firebase.RTDB.setFloat(&fbdo, path + "/temperature", temperature))
    Serial.println("Temperature upload failed: " + fbdo.errorReason());

  if (!Firebase.RTDB.setFloat(&fbdo, path + "/humidity", humidity))
    Serial.println("Humidity upload failed: " + fbdo.errorReason());

  if (!Firebase.RTDB.setFloat(&fbdo, path + "/lux", lux))
    Serial.println("Lux upload failed: " + fbdo.errorReason());

  if (!Firebase.RTDB.setFloat(&fbdo, path + "/solar_voltage", solarVoltage))
    Serial.println("Voltage upload failed: " + fbdo.errorReason());

  char timeStr[30];
  strftime(timeStr, sizeof(timeStr), "%Y-%m-%d %H:%M:%S", localtime(&now));
  Firebase.RTDB.setString(&fbdo, path + "/readable_time", String(timeStr));

  delay(60000); // Upload every minute
}

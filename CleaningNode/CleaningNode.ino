/*
  CleaningNode.ino
  ESP8266 node that listens to Firebase `/commands/clean` and runs a servo cleaning cycle.

  IMPORTANT: Replace the placeholder values below with your WiFi and Firebase settings
  before flashing. For public repositories, keep real credentials out of source control.

  Wiring summary:
  - SG90 servo signal -> D7 (GPIO13)
  - Servo power -> external 5V supply (common GND)

  Recommended: move secrets into a separate `secrets.h` that is gitignored.
*/

#include <ESP8266WiFi.h>
#include <Firebase_ESP_Client.h>
#include <Servo.h>

// WiFi credentials (REPLACE BEFORE USE)
#define WIFI_SSID "<YOUR_WIFI_SSID>"
#define WIFI_PASSWORD "<YOUR_WIFI_PASSWORD>"

// Firebase credentials (REPLACE BEFORE USE)
// Use your project's Web API key and DB URL. Do NOT commit these to a public repo.
#define API_KEY "<YOUR_FIREBASE_API_KEY>"
#define DATABASE_URL "https://<YOUR_PROJECT_ID>.firebaseio.com"

// Firebase setup
FirebaseData fbdo;
FirebaseAuth auth;
FirebaseConfig config;

// Servo setup
Servo cleanerServo;
const int servoPin = 13;  // D7 on NodeMCU

void connectToWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConnected to WiFi.");
}

void setup() {
  Serial.begin(9600);

  cleanerServo.attach(servoPin, 500, 2400);  // SG90 range
  connectToWiFi();

  config.api_key = API_KEY;
  config.database_url = DATABASE_URL;

  // Firebase email/password for a lightweight auth user (optional).
  // Replace with your user or use database rules that allow read/write from the device.
  auth.user.email = "<YOUR_FIREBASE_USER_EMAIL>";
  auth.user.password = "<YOUR_FIREBASE_USER_PASSWORD>";

  Firebase.begin(&config, &auth);
  Firebase.reconnectWiFi(true);
}

void cleanPanel() {
  Serial.println("Starting cleaning cycle...");
  cleanerServo.write(90);
  for (int i = 0; i < 5; i++) {
    for (int angle = -10; angle <= 90; angle += 5) {
      cleanerServo.write(angle);
      delay(5);
    }
    delay(100);
    for (int angle = 90; angle >= -10; angle -= 5) {
      cleanerServo.write(angle);
      delay(5);
    }
    delay(100);
    cleanerServo.write(90);
  }
  Serial.println("Cleaning complete.");
}

void loop() {
  if (Firebase.RTDB.getBool(&fbdo, "/commands/clean")) {
    if (fbdo.dataType() == "boolean" && fbdo.boolData() == true) {
      cleanPanel();
      // Reset the flag
      if (!Firebase.RTDB.setBool(&fbdo, "/commands/clean", false)) {
        Serial.println("Failed to reset clean flag: " + fbdo.errorReason());
      }
    }
  } else {
    Serial.println("Failed to read clean flag: " + fbdo.errorReason());
  }

  delay(10000);  // Check every 10 seconds
}

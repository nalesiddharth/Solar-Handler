# Solar Panel Cleaning & Monitoring (ESP32/ESP8266 + Flask + Firebase)

## Overview

This repository contains a Solar Panel Monitoring and Automated Cleaning project built around ESP-based sensor/actuator nodes, a Firebase Realtime Database backend, and a Flask dashboard for visualization and control. The project predicts solar voltage for the next hour using an LSTM-based model and triggers an automated cleaning cycle if panel performance drops significantly while ambient light is high.

Components
- Monitor Node (ESP32): reads DHT22 (temperature/humidity), BH1750 (lux), and an analog voltage divider for panel voltage, and uploads readings to Firebase every minute.
- Cleaning Node (ESP8266): listens to Firebase `commands/clean` and runs a servo cleaning cycle when triggered.
- Flask app + model: Provides a dashboard and runs background tasks to retrain a prediction model and compute metrics.
- Data utilities: scripts to upload historical CSV data to Firebase for bootstrapping the model and a JSON-based local dashboard server.


## Key Features
- Minute-resolution telemetry: lux, temperature, humidity, solar voltage.
- LSTM-based next-hour prediction pushed to `/next_hour_predictions` in Firebase.
- Automatic cleaning logic based on light level, predicted vs actual voltage and a cooldown timer to avoid excessive cleaning.
- Manual cleaning trigger via dashboard.
- Performance metrics (RMSE / MAE) and cleaning effectiveness logging.


## Security & Git
Do NOT commit your Firebase service account JSON or device credentials. This repo's `.gitignore` is configured to ignore service account files matching `irradianceprediction-firebase-adminsdk-*.json`.

When publishing to GitHub:
- Remove or rotate any API keys / passwords found in Arduino sketches before pushing. Replace them with placeholders and document in README.
- Keep `irradianceprediction-firebase-adminsdk-*.json` outside the repository, or store it in a private secrets manager and set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable locally.


## Setup — Cloud (Firebase)
1. Create a Firebase project and enable Realtime Database (locked to proper rules).
2. Create a service account (Project Settings → Service accounts → Generate new private key). Save the JSON file securely and do not commit it.
3. Set environment variable on your Flask host: `GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service-account.json` or place the file in the project root with the exact name `irradianceprediction-firebase-adminsdk-<id>.json` (not recommended for public repos).
4. Ensure your Firebase RTDB URL matches the one in the Arduino sketches and server files, or update the `DATABASE_URL` constant in the sketches.


## Setup — Python server (Flask + Model)
1. Create a Python virtual environment and install requirements:

```bash
python -m venv venv
# Windows
venv\Scripts\activate
pip install -r requirements.txt
```

2. Export the credentials env var and run the server (example, Windows PowerShell):

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\irradianceprediction-firebase-adminsdk-xxxxx.json"
python model2.py
# or
python app.py
```

Notes:
- `model.py` and `model2.py` provide different variants of the same server. Use `model2.py` for the more feature-complete version (logging, cleaning evaluation, etc.).
- `sample2.py` provides a local JSON-based mock server for offline demos; it looks for `templates/IrradiancePredictionData.json` by default or you can set `IRRADIANCE_JSON`.


## Setup — Hardware
This section describes wiring for both nodes (Monitor and Cleaning).

Parts
- ESP32 development board (for MonitorNode)
- ESP8266 NodeMCU / Wemos (for CleaningNode)
- DHT22 sensor (temperature & humidity)
- BH1750 light sensor (I2C)
- SG90 servo (cleaning actuator)
- Voltage divider for measuring panel voltage
- Wires, breadboard, 3.3V power supply (or regulated battery)

Monitor Node (ESP32)
- DHT22 data pin -> GPIO4
- BH1750 -> I2C: SDA = GPIO21, SCL = GPIO22
- Panel voltage sense -> Analog input GPIO34 (use appropriate divider; code assumes factor 25/3.3)
- Power: 3.3V and GND from regulated source

Cleaning Node (ESP8266 / NodeMCU)
- SG90 servo signal -> D7 (GPIO13) as used in the sketch
- Power servo from stable 5V supply common-ground with ESP board
- Ensure servo has sufficient current; do NOT power servo from the ESP's 3.3V regulator.

Servo notes
- In `CleanerTest.ino` and `CleaningNode.ino` the servo is attached with `attach(pin, 500, 2400)` which constrains pulse widths; adjust if you use a different servo.


## Flashing the Arduino / ESP firmware
1. Open the appropriate sketch in Arduino IDE:
   - `MonitorNode/MonitorNode.ino` (for ESP32)
   - `CleaningNode/CleaningNode.ino` (for ESP8266)
2. Replace the WiFi SSID / password, and Firebase auth values in the sketch. For public repos, replace them with placeholders like `"<YOUR_SSID>"` and document them here.
3. Select the correct board in Tools → Board and the correct COM port.
4. Click Upload.


## Firebase structure (used by the code)
- `/solar_data/{timestamp}`: objects containing `readable_time`, `temperature`, `humidity`, `lux`, `solar_voltage`.
- `/predictions`: pushes with `time`, `predicted`, `actual` (latest predictions/actual comparisons).
- `/next_hour_predictions/{minute}`: mapping of minute index (1..60) to predicted voltage.
- `/commands/clean`: boolean flag (set true to trigger cleaning; nodes reset flag to false after cleaning).
- `/cleaning_history` and `/cleaning_effectiveness`: logs produced by `model2.py`.


## Data upload (historical)
The `sample.py` script uploads `corrected_dataset.csv` to Firebase. Before running it, set `GOOGLE_APPLICATION_CREDENTIALS` like above.

## Troubleshooting
- If the Flask app cannot read credentials, ensure the `GOOGLE_APPLICATION_CREDENTIALS` path is correct.
- If servo behaves oddly, check pulse min/max and verify power supply.
- For BH1750 I2C issues, ensure correct pull-ups and correct SDA/SCL pins for your board.


## License & Credits
This project was developed as a student project. You may reuse code for educational purposes; please attribute the original author when appropriate.

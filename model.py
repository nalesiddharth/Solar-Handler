"""Model server: data ingestion, training loop and prediction endpoints.

This module is intentionally conservative when changing behavior. It
reformats and documents the module for clarity only.
"""

import pandas as pd
import numpy as np
import firebase_admin
from firebase_admin import db, credentials
from datetime import datetime, timedelta
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Model
from tensorflow.keras.layers import Input, LSTM, Dense, Dropout, Concatenate, Bidirectional
from tensorflow.keras.losses import Huber
from flask import Flask, jsonify, render_template
import threading
import time
import os

# Firebase setup
# Firebase setup (use env var if provided)
cred_path = os.environ.get(
    'GOOGLE_APPLICATION_CREDENTIALS',
    'irradianceprediction-firebase-adminsdk-fbsvc-defb0c87df.json'
)
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred, {
    'databaseURL': "https://irradianceprediction-default-rtdb.firebaseio.com"
})

# Flask setup
app = Flask(__name__)

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/predictions')
def get_predictions():
    global model, scaler_env, scaler_time, scaler_target

    # Fetch the last 60 minutes of actual data
    ref = db.reference("/solar_data")
    raw_data = ref.get()
    if not raw_data:
        return jsonify({"labels": [], "recent_actual": [], "future": []})

    data = []
    for _, values in raw_data.items():
        if "readable_time" not in values:
            continue
        values["timestamp"] = values["readable_time"]
        data.append(values)

    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    df.dropna(subset=['timestamp'], inplace=True)
    df.sort_values('timestamp', inplace=True)

    now = datetime.now()
    df = df[df['timestamp'] >= now - timedelta(minutes=60)]
    if len(df) < 60:
        return jsonify({"labels": [], "recent_actual": [], "future": []})

    # Feature engineering
    df['hour'] = df['timestamp'].dt.hour
    df['dayofweek'] = df['timestamp'].dt.dayofweek
    df['month'] = df['timestamp'].dt.month
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
    df['day_sin'] = np.sin(2 * np.pi * df['dayofweek'] / 7)
    df['day_cos'] = np.cos(2 * np.pi * df['dayofweek'] / 7)
    df['solar_voltage_lag1'] = df['solar_voltage'].shift(1)
    df.dropna(inplace=True)

    features_env = ['lux', 'temperature', 'humidity', 'solar_voltage_lag1']
    features_time = ['hour_sin', 'hour_cos', 'day_sin', 'day_cos', 'month']
    target = 'solar_voltage'

    env_scaled = scaler_env.transform(df[features_env])
    time_scaled = scaler_time.transform(df[features_time])

    env_seq = env_scaled[-60:]
    time_seq = time_scaled[-60:]

    # Predict the next 60 minutes
    future_predictions = []
    for i in range(60):
        pred_scaled = model.predict([
            env_seq[np.newaxis, :, :],
            time_seq[np.newaxis, :, :]
        ], verbose=0)

        pred_voltage = scaler_target.inverse_transform(pred_scaled)[0][0]
        future_predictions.append(float(np.round(pred_voltage, 4)))

        # Prepare input for next prediction
        next_env = np.append(env_seq[1:], [[env_seq[-1][0], env_seq[-1][1], env_seq[-1][2], pred_scaled[0][0]]], axis=0)
        hour_now = datetime.now() + timedelta(minutes=i+1)
        hour_sin = np.sin(2 * np.pi * hour_now.hour / 24)
        hour_cos = np.cos(2 * np.pi * hour_now.hour / 24)
        day_sin = np.sin(2 * np.pi * hour_now.weekday() / 7)
        day_cos = np.cos(2 * np.pi * hour_now.weekday() / 7)
        month = hour_now.month / 12.0
        next_time = np.append(time_seq[1:], [[hour_sin, hour_cos, day_sin, day_cos, month]], axis=0)

        env_seq = next_env
        time_seq = next_time

    labels = [t.strftime('%H:%M') for t in df['timestamp']] + [
        (df['timestamp'].iloc[-1] + timedelta(minutes=i+1)).strftime('%H:%M') for i in range(60)
    ]
    actual_vals = df['solar_voltage'].tolist()

    return jsonify({
        "labels": labels,
        "recent_actual": actual_vals,
        "future": future_predictions
    })

@app.route('/clean', methods=['POST'])
def manual_clean():
    db.reference("/commands/clean").set(True)
    return jsonify({"status": "Cleaning triggered"})

# Globals
model = None
scaler_env = None
scaler_time = None
scaler_target = None

def retrain_model():
    global model, scaler_env, scaler_time, scaler_target
    while True:
        ref = db.reference("/solar_data")
        raw_data = ref.get()
        if not raw_data:
            print("No data found.")
            time.sleep(3600)
            continue

        data = []
        for _, values in raw_data.items():
            if "readable_time" not in values:
                continue
            values["timestamp"] = values["readable_time"]
            data.append(values)

        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df.dropna(subset=['timestamp'], inplace=True)
        df.sort_values("timestamp", inplace=True)
        df = df[df['timestamp'] >= datetime.now() - timedelta(days=30)]
        if df.empty:
            print("No recent data.")
            time.sleep(3600)
            continue

        df['hour'] = df['timestamp'].dt.hour
        df['dayofweek'] = df['timestamp'].dt.dayofweek
        df['month'] = df['timestamp'].dt.month
        df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
        df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
        df['day_sin'] = np.sin(2 * np.pi * df['dayofweek'] / 7)
        df['day_cos'] = np.cos(2 * np.pi * df['dayofweek'] / 7)
        df['solar_voltage_lag1'] = df['solar_voltage'].shift(1)
        df.dropna(inplace=True)

        features_env = ['lux', 'temperature', 'humidity', 'solar_voltage_lag1']
        features_time = ['hour_sin', 'hour_cos', 'day_sin', 'day_cos', 'month']
        target = 'solar_voltage'

        scaler_env = MinMaxScaler()
        scaler_time = MinMaxScaler()
        scaler_target = MinMaxScaler()

        scaled_env = scaler_env.fit_transform(df[features_env])
        scaled_time = scaler_time.fit_transform(df[features_time])
        scaled_target = scaler_target.fit_transform(df[[target]])

        sequence_length = 60
        X_env, X_time, y = [], [], []
        for i in range(sequence_length, len(df)):
            X_env.append(scaled_env[i-sequence_length:i])
            X_time.append(scaled_time[i-sequence_length:i])
            y.append(scaled_target[i])

        X_env, X_time, y = np.array(X_env), np.array(X_time), np.array(y)

        input_env = Input(shape=(X_env.shape[1], X_env.shape[2]))
        input_time = Input(shape=(X_time.shape[1], X_time.shape[2]))
        lstm_env = Bidirectional(LSTM(128, return_sequences=True))(input_env)
        lstm_env = Dropout(0.3)(lstm_env)
        lstm_env = Bidirectional(LSTM(64))(lstm_env)
        lstm_time = Bidirectional(LSTM(64, return_sequences=True))(input_time)
        lstm_time = Dropout(0.3)(lstm_time)
        lstm_time = Bidirectional(LSTM(32))(lstm_time)
        combined = Concatenate()([lstm_env, lstm_time])
        dense = Dense(64, activation='relu')(combined)
        output = Dense(1)(dense)

        model = Model(inputs=[input_env, input_time], outputs=output)
        model.compile(optimizer='adam', loss=Huber())
        model.fit([X_env, X_time], y, epochs=20, batch_size=16, verbose=0)

        print("Model retrained at:", datetime.now())
        time.sleep(3600)

# Start retraining thread
threading.Thread(target=retrain_model, daemon=True).start()

# Run Flask app
if __name__ == '__main__':
    app.run(debug=False, use_reloader=False)

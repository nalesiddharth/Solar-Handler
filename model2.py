"""Model2 server: improved logging, cleaning evaluation and prediction pipelines.

Only minimal formatting/documentation changes were applied to preserve runtime
behavior while improving readability for publishing.
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
from flask import Flask, jsonify, render_template, request
import threading
import time
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants for cleaning thresholds
LUX_THRESHOLD = 50000  # Adjust based on your sensor and environment
EXPECTED_VOLTAGE_THRESHOLD = 10.5  # Adjust based on your panel specifications
CLEANING_COOLDOWN_MINUTES = 60  # Prevent too frequent cleanings

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
    return render_template('dashboard2.html')

@app.route('/api/predictions')
def get_predictions():
    try:
        ref = db.reference("/next_hour_predictions")
        data = ref.get()
        
        if not data:
            return jsonify({"labels": [], "future": [], "recent_actual": [], "recent_pred": []})
        
        # Handle both dictionary and list formats
        if isinstance(data, dict):
            # Original code for dictionary format
            sorted_keys = sorted(data.keys(), key=lambda x: int(x) if x is not None and x.isdigit() else 0)
            labels = [f"{k} min" for k in sorted_keys]
            future_values = [data[k] for k in sorted_keys]
        else:
            # Handle list format
            labels = [f"{i+1} min" for i in range(len(data))]
            future_values = data
        
        recent_ref = db.reference("/predictions")
        recent_data = recent_ref.order_by_key().limit_to_last(60).get()
        
        if recent_data:
            recent_actual = [float(v['actual']) for v in recent_data.values() if 'actual' in v]
            recent_pred = [float(v['predicted']) for v in recent_data.values() if 'predicted' in v]
        else:
            recent_actual = []
            recent_pred = []
        
        return jsonify({
            "labels": labels,
            "future": future_values,
            "recent_actual": recent_actual,
            "recent_pred": recent_pred
        })
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/clean', methods=['POST'])
def manual_clean():
    try:
        db.reference("/commands/clean").set(True)
        db.reference("/cleaning_history").push({
            "time": str(datetime.now()),
            "trigger": "manual",
            "status": "initiated"
        })
        return jsonify({"status": "Cleaning triggered", "error": None})
    except Exception as e:
        logger.error(f"Error triggering cleaning: {str(e)}")
        return jsonify({"error": str(e)})

@app.route('/api/system-status')
def system_status():
    try:
        # Fetch the latest data
        latest_data_ref = db.reference("/solar_data").order_by_key().limit_to_last(1).get()
        if not latest_data_ref:
            return jsonify({"status": "No data available"})
        
        latest_data = list(latest_data_ref.values())[0]
        
        # Get model info
        model_info = {
            "last_trained": db.reference("/model_info/last_trained").get() or "Never",
            "training_samples": db.reference("/model_info/training_samples").get() or 0
        }
        
        return jsonify({
            "latest_reading": latest_data,
            "model_info": model_info,
            "error": None
        })
    except Exception as e:
        logger.error(f"Error fetching system status: {str(e)}")
        return jsonify({"error": str(e)})
    
@app.route('/solar_data')
def get_solar_data():
    try:
        ref = db.reference("/solar_data")
        data = ref.order_by_key().limit_to_last(60).get()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)})


# Globals for model reuse
model = None
scaler_env = None
scaler_time = None
scaler_target = None
latest_env_seq = None
latest_time_seq = None
last_cleaning_time = None

# Calculate performance metrics
def calculate_metrics():
    try:
        ref = db.reference("/predictions")
        data = ref.order_by_key().limit_to_last(1440).get()  # Last 24 hours (60 min * 24 hours)
        
        if not data:
            return
            
        actual_values = []
        predicted_values = []
        
        for _, values in data.items():
            if 'actual' in values and 'predicted' in values:
                actual = float(values['actual'])
                predicted = float(values['predicted'])
                if actual > 0:  # Filter out night time readings
                    actual_values.append(actual)
                    predicted_values.append(predicted)
        
        if len(actual_values) < 10:  # Need sufficient data
            return
            
        # Calculate RMSE
        rmse = np.sqrt(np.mean((np.array(actual_values) - np.array(predicted_values))**2))
        
        # Calculate MAE
        mae = np.mean(np.abs(np.array(actual_values) - np.array(predicted_values)))
        
        # Update metrics in Firebase
        db.reference("/performance_metrics").update({
            "rmse": float(np.round(rmse, 4)),
            "mae": float(np.round(mae, 4)),
            "updated_at": str(datetime.now()),
            "samples": len(actual_values)
        })
        
        logger.info(f"Updated performance metrics: RMSE={rmse:.4f}, MAE={mae:.4f}")
    except Exception as e:
        logger.error(f"Error calculating metrics: {str(e)}")

# Automatic cleaning check
def check_cleaning_needed():
    global last_cleaning_time
    
    if last_cleaning_time is None:
        last_cleaning_time = datetime.now() - timedelta(minutes=CLEANING_COOLDOWN_MINUTES)
    
    while True:
        try:
            # Don't check if we recently cleaned
            time_since_last_cleaning = (datetime.now() - last_cleaning_time).total_seconds() / 60
            if time_since_last_cleaning < CLEANING_COOLDOWN_MINUTES:
                time.sleep(60)
                continue
                
            # Fetch latest data
            latest_data_ref = db.reference("/solar_data").order_by_key().limit_to_last(5).get()
            
            if not latest_data_ref:
                time.sleep(60)
                continue
                
            data_points = list(latest_data_ref.values())
            
            # Check for voltage drop despite high ambient light
            if len(data_points) >= 3:
                # Get average of last few readings
                avg_lux = sum(float(dp.get('lux', 0)) for dp in data_points) / len(data_points)
                avg_voltage = sum(float(dp.get('solar_voltage', 0)) for dp in data_points) / len(data_points)
                
                # Get predicted voltage
                predictions_ref = db.reference("/predictions").order_by_key().limit_to_last(1).get()
                if predictions_ref:
                    latest_pred = float(list(predictions_ref.values())[0].get('predicted', 0))
                    
                    # If actual voltage is significantly lower than predicted and light is good
                    voltage_diff_percent = (latest_pred - avg_voltage) / latest_pred * 100 if latest_pred > 0 else 0
                    
                    if (avg_lux > LUX_THRESHOLD and avg_voltage < EXPECTED_VOLTAGE_THRESHOLD and 
                        voltage_diff_percent > 15):  # 15% lower than prediction
                        # Trigger cleaning
                        db.reference("/commands/clean").set(True)
                        last_cleaning_time = datetime.now()
                        
                        # Log cleaning event
                        db.reference("/cleaning_history").push({
                            "time": str(datetime.now()),
                            "trigger": "automatic",
                            "lux": float(avg_lux),
                            "actual_voltage": float(avg_voltage),
                            "predicted_voltage": float(latest_pred),
                            "voltage_diff_percent": float(voltage_diff_percent)
                        })
                        
                        logger.info(f"Auto-cleaning triggered at {datetime.now()}")
                        
                        # Update last cleaning time in metrics
                        db.reference("/performance_metrics").update({
                            "last_cleaning": str(datetime.now())
                        })
        except Exception as e:
            logger.error(f"Error in cleaning check: {str(e)}")
        
        time.sleep(60)  # Check every minute

# Function to evaluate cleaning effectiveness
def evaluate_cleaning_effectiveness():
    while True:
        try:
            # Check if cleaning was recently performed
            cleaning_ref = db.reference("/commands/clean").get()
            
            if cleaning_ref:
                # Get voltage before cleaning
                pre_cleaning_ref = db.reference("/solar_data").order_by_key().limit_to_last(5).get()
                if pre_cleaning_ref:
                    pre_cleaning_voltage = np.mean([float(dp.get('solar_voltage', 0)) 
                                                  for dp in pre_cleaning_ref.values()])
                    
                    # Wait for cleaning to complete (assume 2 minutes)
                    time.sleep(120)
                    
                    # Reset cleaning flag
                    db.reference("/commands/clean").set(False)
                    
                    # Wait for new readings after cleaning (3 minutes)
                    time.sleep(180)
                    
                    # Get voltage after cleaning
                    post_cleaning_ref = db.reference("/solar_data").order_by_key().limit_to_last(5).get()
                    if post_cleaning_ref:
                        post_cleaning_voltage = np.mean([float(dp.get('solar_voltage', 0)) 
                                                      for dp in post_cleaning_ref.values()])
                        
                        # Calculate improvement
                        voltage_improvement = post_cleaning_voltage - pre_cleaning_voltage
                        improvement_percent = (voltage_improvement / pre_cleaning_voltage * 100 
                                             if pre_cleaning_voltage > 0 else 0)
                        
                        # Store cleaning effectiveness
                        db.reference("/cleaning_effectiveness").push({
                            "time": str(datetime.now()),
                            "pre_cleaning_voltage": float(pre_cleaning_voltage),
                            "post_cleaning_voltage": float(post_cleaning_voltage),
                            "voltage_improvement": float(voltage_improvement),
                            "improvement_percent": float(improvement_percent)
                        })
                        
                        logger.info(f"Cleaning effectiveness: {improvement_percent:.2f}% improvement")
        except Exception as e:
            logger.error(f"Error in evaluating cleaning: {str(e)}")
            
        time.sleep(60)  # Check every minute

# Retrain model every hour
def retrain_model():
    global model, scaler_env, scaler_time, scaler_target, latest_env_seq, latest_time_seq
    
    while True:
        try:
            ref = db.reference("/solar_data")
            raw_data = ref.get()
            
            if not raw_data:
                logger.warning("No data available to train.")
                time.sleep(300)  # Wait 5 minutes and try again
                continue
                
            data = []
            for key, values in raw_data.items():
                if "readable_time" not in values:
                    continue
                values["timestamp"] = values["readable_time"]
                data.append(values)
            
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'], format="%Y-%m-%d %H:%M:%S", errors='coerce')
            df.dropna(subset=['timestamp'], inplace=True)
            df.sort_values("timestamp", inplace=True)
            
            # Filter last 30 days of data
            cutoff = datetime.now() - timedelta(days=30)
            df = df[df['timestamp'] >= cutoff]
            
            if df.empty:
                logger.warning("No data available to train.")
                time.sleep(3600)
                continue
                
            # Feature engineering
            df['hour'] = df['timestamp'].dt.hour
            df['dayofweek'] = df['timestamp'].dt.dayofweek
            df['month'] = df['timestamp'].dt.month
            df['day'] = df['timestamp'].dt.day
            
            # Cyclical time features
            df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
            df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
            df['day_sin'] = np.sin(2 * np.pi * df['dayofweek'] / 7)
            df['day_cos'] = np.cos(2 * np.pi * df['dayofweek'] / 7)
            df['month_sin'] = np.sin(2 * np.pi * df['month'] / 12)
            df['month_cos'] = np.cos(2 * np.pi * df['month'] / 12)
            
            # Add lag features
            df['solar_voltage_lag1'] = df['solar_voltage'].shift(1)
            df['lux_lag1'] = df['lux'].shift(1)
            
            # Remove rows with NaN values after creating lag features
            df.dropna(inplace=True)
            
            # Detect and remove outliers (optional)
            Q1 = df['solar_voltage'].quantile(0.25)
            Q3 = df['solar_voltage'].quantile(0.75)
            IQR = Q3 - Q1
            df = df[~((df['solar_voltage'] < (Q1 - 1.5 * IQR)) | (df['solar_voltage'] > (Q3 + 1.5 * IQR)))]
            
            features_env = ['lux', 'temperature', 'humidity', 'solar_voltage_lag1', 'lux_lag1']
            features_time = ['hour_sin', 'hour_cos', 'day_sin', 'day_cos', 'month_sin', 'month_cos']
            target = 'solar_voltage'
            
            # Scale features
            scaler_env = MinMaxScaler()
            scaler_time = MinMaxScaler()
            scaler_target = MinMaxScaler()
            
            scaled_env = scaler_env.fit_transform(df[features_env])
            scaled_time = scaler_time.fit_transform(df[features_time])
            scaled_target = scaler_target.fit_transform(df[[target]])
            
            # Create sequences
            sequence_length = 60
            X_env, X_time, y = [], [], []
            
            for i in range(sequence_length, len(df)):
                X_env.append(scaled_env[i-sequence_length:i])
                X_time.append(scaled_time[i-sequence_length:i])
                y.append(scaled_target[i])
                
            X_env = np.array(X_env)
            X_time = np.array(X_time)
            y = np.array(y)
            
            # Build model
            input_env = Input(shape=(X_env.shape[1], X_env.shape[2]))
            input_time = Input(shape=(X_time.shape[1], X_time.shape[2]))
            
            # Environmental features branch
            lstm_env = Bidirectional(LSTM(128, return_sequences=True))(input_env)
            lstm_env = Dropout(0.3)(lstm_env)
            lstm_env = Bidirectional(LSTM(64))(lstm_env)
            
            # Time features branch
            lstm_time = Bidirectional(LSTM(64, return_sequences=True))(input_time)
            lstm_time = Dropout(0.3)(lstm_time)
            lstm_time = Bidirectional(LSTM(32))(lstm_time)
            
            # Combine branches
            combined = Concatenate()([lstm_env, lstm_time])
            dense = Dense(64, activation='relu')(combined)
            output = Dense(1)(dense)
            
            model = Model(inputs=[input_env, input_time], outputs=output)
            model.compile(optimizer='adam', loss=Huber())
            
            # Train model
            model.fit([X_env, X_time], y, epochs=20, batch_size=16, verbose=0)
            
            # Store latest sequences for predictions
            latest_env_seq = X_env[-1].copy()
            latest_time_seq = X_time[-1].copy()
            
            # Update model info in Firebase
            db.reference("/model_info").update({
                "last_trained": str(datetime.now()),
                "training_samples": len(df),
                "features_env": features_env,
                "features_time": features_time
            })
            
            logger.info(f"Model retrained at: {datetime.now()} with {len(df)} samples")
            
            # Calculate and update metrics
            calculate_metrics()
            
        except Exception as e:
            logger.error(f"Error retraining model: {str(e)}")
            
        time.sleep(3600)  # retrain every hour

# Use trained model for predictions every minute
# Use trained model for predictions every minute
def predict_minutely():
    global model, scaler_target, latest_env_seq, latest_time_seq
    
    while True:
        if model is None or latest_env_seq is None or latest_time_seq is None:
            time.sleep(5)
            continue
            
        future_predictions = []
        env_seq = latest_env_seq.copy()
        time_seq = latest_time_seq.copy()
        
        for i in range(60):
            pred_scaled = model.predict([
                env_seq[np.newaxis, :, :],
                time_seq[np.newaxis, :, :]
            ], verbose=0)
            
            pred_voltage = scaler_target.inverse_transform(pred_scaled)[0][0]
            future_predictions.append(float(np.round(pred_voltage, 4)))
            
            # Prepare input for next prediction
            new_env = np.append(env_seq[1:], [[
                env_seq[-1][0],  # lux
                env_seq[-1][1],  # temperature
                env_seq[-1][2],  # humidity
                pred_scaled[0][0],  # solar_voltage_lag1
                env_seq[-1][0]  # lux_lag1 (reusing the lux value)
            ]], axis=0)

            
            hour_now = datetime.now() + timedelta(minutes=i+1)
            hour_sin = np.sin(2 * np.pi * hour_now.hour / 24)
            hour_cos = np.cos(2 * np.pi * hour_now.hour / 24)
            day_sin = np.sin(2 * np.pi * hour_now.weekday() / 7)
            day_cos = np.cos(2 * np.pi * hour_now.weekday() / 7)
            month = hour_now.month / 12.0
            
            new_time = np.append(time_seq[1:], [[hour_sin, hour_cos, day_sin, day_cos, month]], axis=0)
            
            env_seq = new_env
            time_seq = new_time
            
        # Save predictions to Firebase
        if isinstance(future_predictions, list):
            for i, voltage in enumerate(future_predictions):
                minute_index = str(i + 1)
                db.reference(f"/next_hour_predictions/{minute_index}").set(voltage)
                
        # Save latest prediction to "/predictions"
        latest_pred = future_predictions[0]
        
        # Fetch actual latest solar voltage
        latest_solar_data_ref = db.reference("/solar_data")
        latest_solar_data = latest_solar_data_ref.order_by_key().limit_to_last(1).get()
        
        actual_solar_voltage = None
        if latest_solar_data:
            for key, values in latest_solar_data.items():
                actual_solar_voltage = values.get("solar_voltage", None)
                
        db.reference("/predictions").push({
            "time": str(datetime.now()),
            "predicted": latest_pred,
            "actual": actual_solar_voltage if actual_solar_voltage is not None else 0
        })
        
        # Update latest sequences
        latest_env_seq = env_seq
        latest_time_seq = time_seq
        
        time.sleep(60)  # predict every minute

# Start background threads
threading.Thread(target=retrain_model, daemon=True).start()
threading.Thread(target=predict_minutely, daemon=True).start()
threading.Thread(target=check_cleaning_needed, daemon=True).start()
threading.Thread(target=evaluate_cleaning_effectiveness, daemon=True).start()

# Run Flask app
if __name__ == '__main__':
    app.run(debug=False, use_reloader=False, host='0.0.0.0', port=5000)

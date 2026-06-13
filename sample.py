import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime
import time

# Initialize Firebase (use env var or local file)
import os
cred_path = os.environ.get(
    'GOOGLE_APPLICATION_CREDENTIALS',
    'irradianceprediction-firebase-adminsdk-fbsvc-defb0c87df.json'
)
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred, {
    'databaseURL': "https://irradianceprediction-default-rtdb.firebaseio.com"
})

# Read the CSV file
df = pd.read_csv('corrected_dataset.csv')

# Reference to the solar_data node in Firebase
ref = db.reference('/solar_data')

# Process and upload each row
for idx, row in df.iterrows():
    # Convert date string to Unix timestamp (milliseconds)
    date_obj = datetime.strptime(row['readable_time'], '%m/%d/%Y %H:%M')
    timestamp = int(date_obj.timestamp() * 1000)  # Convert to milliseconds
    
    # Create data entry
    data = {
        'readable_time': row['readable_time'],
        'temperature': float(row['temperature']),
        'humidity': float(row['humidity']),
        'lux': float(row['lux']),
        'solar_voltage': float(row['solar_voltage'])
    }
    
    # Upload to Firebase using timestamp as the key
    ref.child(str(timestamp)).set(data)
    
    # Print progress
    print(f"Uploaded entry {idx+1}/{len(df)}: {row['readable_time']}")
    
    # Small delay to prevent rate limiting
    time.sleep(0.1)

print("Data upload complete!")

"""Flask dashboard entrypoint (lightweight).

This module exposes a small API used by the front-end dashboard to fetch
predictions stored in Firebase Realtime Database.

The Firebase service account JSON path is read from the environment variable
`GOOGLE_APPLICATION_CREDENTIALS` (recommended). If not set, the code falls
back to a local filename for convenience during local testing.
"""

from flask import Flask, render_template, jsonify
import firebase_admin
from firebase_admin import credentials, db
import os

# Load Firebase credentials from environment or local file (do not commit service account to git)
cred_path = os.environ.get(
    'GOOGLE_APPLICATION_CREDENTIALS',
    'irradianceprediction-firebase-adminsdk-fbsvc-defb0c87df.json'
)
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred, {
    'databaseURL': "https://irradianceprediction-default-rtdb.firebaseio.com"
})

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/predictions')
def get_predictions():
    ref = db.reference("/next_hour_predictions")
    data = ref.get()
    if not data:
        return jsonify({"labels": [], "values": []})
    labels = [f"{i+1} min" for i in range(len(data))]
    values = [data[k] for k in sorted(data, key=int)]
    return jsonify({"labels": labels, "values": values})

if __name__ == '__main__':
    app.run(debug=True)

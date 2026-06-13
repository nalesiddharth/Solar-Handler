import json
from flask import Flask, jsonify, render_template
import os

app = Flask(__name__)

# Make JSON_PATH robust: look in `templates/` next to this script
JSON_PATH = os.environ.get('IRRADIANCE_JSON', os.path.join(
    os.path.dirname(__file__), 'templates', 'IrradiancePredictionData.json'
))

def load_data():
    """Load the full JSON dataset."""
    with open(JSON_PATH, "r") as f:
        return json.load(f)

@app.route("/")
def index():
    return render_template("dashboard2.html")

# ------------------------------
# API: SYSTEM STATUS
# ------------------------------
@app.route("/api/system-status")
def api_system_status():
    data = load_data()

    # Latest solar reading
    solar = data.get("solar_data", {})
    latest = list(solar.values())[-1] if solar else None

    model_info = data.get("model_info", {
        "last_trained": "Never",
        "training_samples": 0
    })

    return jsonify({
        "latest_reading": latest,
        "model_info": model_info,
        "error": None
    })

# ------------------------------
# API: PREDICTIONS (Next hour)
# ------------------------------
@app.route("/api/predictions")
def api_predictions():
    data = load_data()

    next_hour = data.get("next_hour_predictions", {})

    # Convert predictions to ordered arrays
    labels = []
    future = []

    for k in sorted(next_hour, key=lambda x: int(x)):
        labels.append(f"{k} min")
        future.append(next_hour[k])

    # Recent 60 actual/pred values
    preds = data.get("predictions", {})
    preds_sorted = list(preds.values())[-60:]

    recent_actual = [p["actual"] for p in preds_sorted if "actual" in p]
    recent_pred = [p["predicted"] for p in preds_sorted if "predicted" in p]

    return jsonify({
        "labels": labels,
        "future": future,
        "recent_actual": recent_actual,
        "recent_pred": recent_pred
    })

# ------------------------------
# API: SOLAR DATA (for temp/humidity)
# ------------------------------
@app.route("/solar_data")
def api_solar_data():
    data = load_data()
    solar = data.get("solar_data", {})

    # Only last 60 entries
    last60 = dict(list(solar.items())[-60:])
    return jsonify(last60)

# ------------------------------
# API: CLEAN (dummy stub)
# ------------------------------
@app.route("/clean", methods=["POST"])
def api_clean():
    # No real cleaning — just return success so the UI behaves normally
    return jsonify({"status": "OK (dummy)", "error": None})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime

import paho.mqtt.client as mqtt
from flask import (Flask, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import (LoginManager, current_user, login_required,
                         login_user, logout_user)
from flask_socketio import SocketIO
from werkzeug.security import check_password_hash

from auth import User
from database import (get_recent_logs, get_setting, init_db, log_telemetry,
                      purge_old_logs, set_setting)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "zan-dashboard-dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access the dashboard."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    return User.get_by_id(int(user_id))


# ── In-memory network state ────────────────────────────────────────────────────

_state = {
    "nodes": {},      # node_id → latest reading dict
    "links": {},      # "n1→n2" → latest reading dict
    "insights": [],   # last 20 AI anomaly alerts
    "healthy": True,
    "mqtt_connected": False,
}
_state_lock = threading.Lock()

# Per-link history for charts: "n1→n2" → deque of last 60 readings
from collections import deque
_history = {}
_HISTORY_LEN = 60


def _update_state(reading):
    node_id = reading["node_id"]
    target = reading["target_node"]
    link_key = "{}→{}".format(node_id, target)

    with _state_lock:
        _state["nodes"][node_id] = reading
        _state["links"][link_key] = reading

        if link_key not in _history:
            _history[link_key] = deque(maxlen=_HISTORY_LEN)
        _history[link_key].append({
            "t": reading.get("received_at", ""),
            "lat": reading["latency_ms"],
            "rssi": reading["rssi_dbm"],
            "loss": reading["packet_loss_pct"],
        })


# ── MQTT bridge ────────────────────────────────────────────────────────────────

_mqtt_client = None
_mqtt_thread_stop = None


def _on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe("zan/telemetry/#")
        client.subscribe("zan/insights")
        with _state_lock:
            _state["mqtt_connected"] = True
        socketio.emit("mqtt_status", {"connected": True})
        logger.info("MQTT connected")
    else:
        logger.warning("MQTT connect rc=%d", rc)


def _on_disconnect(client, userdata, rc):
    with _state_lock:
        _state["mqtt_connected"] = False
    socketio.emit("mqtt_status", {"connected": False})


def _on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception:
        return

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    if msg.topic == "zan/insights":
        insight = {**payload, "received_at": now}
        with _state_lock:
            _state["insights"] = (_state["insights"] + [insight])[-20:]
            _state["healthy"] = False
        socketio.emit("insight", insight)
        threading.Thread(target=_emit_sdn_update, daemon=True).start()
        return

    node_id = payload.get("node_id")
    target = payload.get("target_node")
    if not node_id or not target:
        return

    reading = {
        "node_id": node_id,
        "target_node": target,
        "latency_ms": float(payload.get("latency_ms", 0)),
        "rssi_dbm": int(payload.get("rssi_dbm", -50)),
        "packet_loss_pct": float(payload.get("packet_loss_pct", 0)),
        "uptime_s": int(payload.get("uptime_s", 0)),
        "timestamp": payload.get("timestamp", time.time()),
        "received_at": now,
    }

    _update_state(reading)
    log_telemetry(reading, msg.topic, msg.payload.decode())
    socketio.emit("telemetry", reading)


def _mqtt_loop(broker, port, stop_event):
    global _mqtt_client
    client = mqtt.Client()
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message
    _mqtt_client = client

    while not stop_event.is_set():
        try:
            client.connect(broker, port, keepalive=60)
            client.loop_forever()
        except Exception as exc:
            if stop_event.is_set():
                break
            logger.error("MQTT error: %s — retry in 5 s", exc)
            time.sleep(5)


def start_mqtt():
    global _mqtt_thread_stop
    broker = get_setting("mqtt_broker", "localhost")
    port = int(get_setting("mqtt_port", "1883"))
    _mqtt_thread_stop = threading.Event()
    t = threading.Thread(target=_mqtt_loop, args=(broker, port, _mqtt_thread_stop), daemon=True)
    t.start()
    logger.info("MQTT thread started → %s:%d", broker, port)


def _emit_sdn_update():
    """Fetch SDN status from controller and push to all Socket.IO clients."""
    ctrl = get_setting("controller_url", "http://localhost:8080")
    try:
        with urllib.request.urlopen(f"{ctrl}/zan/network-status", timeout=2) as r:
            data = json.loads(r.read())
        socketio.emit("sdn_update", data)
    except Exception:
        pass


def restart_mqtt():
    global _mqtt_thread_stop, _mqtt_client
    if _mqtt_thread_stop:
        _mqtt_thread_stop.set()
    if _mqtt_client:
        try:
            _mqtt_client.disconnect()
        except Exception:
            pass
    time.sleep(0.3)
    start_mqtt()


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.get_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    with _state_lock:
        snap = {
            "nodes": dict(_state["nodes"]),
            "links": dict(_state["links"]),
            "insights": list(_state["insights"]),
            "healthy": _state["healthy"],
            "mqtt_connected": _state["mqtt_connected"],
        }
    return render_template("dashboard.html", state=snap)


@app.route("/logs")
@login_required
def logs():
    return render_template("logs.html")


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        for key in ("mqtt_broker", "mqtt_port", "controller_url", "anomaly_threshold"):
            val = request.form.get(key)
            if val is not None:
                set_setting(key, val.strip())

        new_pw = request.form.get("new_password", "").strip()
        if new_pw:
            user = User.get_by_username(current_user.username)
            if user:
                user.update_password(new_pw)
                flash("Password updated.", "success")

        flash("Settings saved.", "success")
        restart_mqtt()
        return redirect(url_for("settings"))

    s = {
        "mqtt_broker":       get_setting("mqtt_broker", "localhost"),
        "mqtt_port":         get_setting("mqtt_port", "1883"),
        "controller_url":    get_setting("controller_url", "http://localhost:8080"),
        "anomaly_threshold": get_setting("anomaly_threshold", "0.75"),
    }
    return render_template("settings.html", s=s)


# ── JSON API ───────────────────────────────────────────────────────────────────

@app.route("/api/state")
@login_required
def api_state():
    with _state_lock:
        return jsonify(_state)


@app.route("/api/history/<path:link_key>")
@login_required
def api_history(link_key):
    data = list(_history.get(link_key, []))
    return jsonify(data)


@app.route("/api/logs")
@login_required
def api_logs():
    limit = request.args.get("limit", 100, type=int)
    return jsonify(get_recent_logs(limit=limit))


@app.route("/api/sdn-status")
@login_required
def api_sdn_status():
    ctrl = get_setting("controller_url", "http://localhost:8080")
    try:
        with urllib.request.urlopen(f"{ctrl}/zan/network-status", timeout=2) as r:
            return jsonify(json.loads(r.read()))
    except Exception as exc:
        return jsonify({"error": str(exc), "connected_switches": [],
                        "degraded_links": [], "mac_table": {}})


# ── Socket.IO ──────────────────────────────────────────────────────────────────

@socketio.on("connect")
def on_ws_connect():
    with _state_lock:
        socketio.emit("mqtt_status", {"connected": _state["mqtt_connected"]})


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    start_mqtt()
    socketio.run(app, host="0.0.0.0", port=5000, debug=False,
                 allow_unsafe_werkzeug=True)

"""
MQTT subscriber for ZAN telemetry.

Subscribes to zan/telemetry/#, maintains a per-link sliding window,
runs Isolation Forest inference on every new reading, and POSTs
anomaly insights to the os-ken controller.
"""

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque

import paho.mqtt.client as mqtt
import requests

logger = logging.getLogger(__name__)

MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
LINUX_PC_URL = os.environ.get("LINUX_PC_URL", "http://192.168.1.20:8080")
ANOMALY_THRESHOLD = float(os.environ.get("ANOMALY_THRESHOLD", 0.75))
WINDOW_SIZE = int(os.environ.get("WINDOW_SIZE", 30))
NODE_TIMEOUT_S = float(os.environ.get("NODE_TIMEOUT_S", 20))

MQTT_TOPIC = "zan/telemetry/#"
ALERT_COOLDOWN_S = 30.0


class ZANSubscriber:
    """
    Subscribes to MQTT telemetry, runs per-link inference, posts insights.

    Thread-safety: all mutable state is protected by self._lock.
    Inference and HTTP POST run synchronously in the MQTT network loop
    thread — fast enough for 5-second telemetry intervals.
    """

    def __init__(self, model):
        self._model = model
        self._lock = threading.Lock()

        # Per-link sliding windows  key: (node_id, target_node)
        self._windows = defaultdict(lambda: deque(maxlen=WINDOW_SIZE))

        # last time a reading was received for each link
        self._last_seen = {}

        # last time an alert was fired for each link (cooldown)
        self._last_alert = {}

        # currently active alerts  key: link_key → alert dict
        self._active_alerts = {}

        # counters
        self._total_received = 0
        self._total_anomalies = 0

        self._client = None
        self._running = False

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("MQTT connected to %s:%d", MQTT_BROKER, MQTT_PORT)
            client.subscribe(MQTT_TOPIC)
            logger.info("Subscribed to %s", MQTT_TOPIC)
        else:
            logger.error("MQTT connect failed rc=%d", rc)

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            logger.warning("Unexpected MQTT disconnect rc=%d — will auto-reconnect", rc)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.debug("Bad payload on %s: %s", msg.topic, exc)
            return

        node_id = payload.get("node_id")
        target = payload.get("target_node")
        if not node_id or not target:
            return

        reading = {
            "latency_ms": float(payload.get("latency_ms", 0.0)),
            "rssi_dbm": int(payload.get("rssi_dbm", -50)),
            "packet_loss_pct": float(payload.get("packet_loss_pct", 0.0)),
            "uptime_s": int(payload.get("uptime_s", 0)),
            "timestamp": float(payload.get("timestamp", time.time())),
        }

        link_key = (node_id, target)

        with self._lock:
            self._windows[link_key].append(reading)
            self._last_seen[link_key] = time.time()
            self._total_received += 1

        if self._model.is_loaded():
            self._run_inference(link_key, node_id, target)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def _run_inference(self, link_key, node_id, target):
        with self._lock:
            readings = list(self._windows[link_key])

        if len(readings) < 10:
            return

        confidence, anomaly_type = self._model.score(readings)

        now = time.time()
        if confidence > ANOMALY_THRESHOLD and anomaly_type:
            last = self._last_alert.get(link_key, 0.0)
            if now - last > ALERT_COOLDOWN_S:
                alert = {
                    "type": anomaly_type,
                    "nodes": [node_id, target],
                    "confidence": round(confidence, 4),
                    "detected_at": now,
                }
                with self._lock:
                    self._last_alert[link_key] = now
                    self._active_alerts[link_key] = alert
                    self._total_anomalies += 1

                logger.warning(
                    "ANOMALY [%s] %s→%s conf=%.3f",
                    anomaly_type, node_id, target, confidence,
                )
                self._post_insight(anomaly_type, [node_id, target], confidence)
        else:
            with self._lock:
                if link_key in self._active_alerts:
                    logger.info("Resolved: %s→%s", node_id, target)
                    del self._active_alerts[link_key]

    # ------------------------------------------------------------------
    # Controller notification
    # ------------------------------------------------------------------

    def _post_insight(self, anomaly_type, nodes, confidence):
        payload = {
            "type": anomaly_type,
            "nodes": nodes,
            "confidence": round(confidence, 4),
        }
        # Publish to MQTT so the dashboard receives it in real time
        if self._client:
            import json as _json
            self._client.publish("zan/insights", _json.dumps(payload), qos=1)

        url = "{}/zan/insight".format(LINUX_PC_URL)
        try:
            resp = requests.post(url, json=payload, timeout=5)
            logger.info(
                "POST %s → HTTP %d", url, resp.status_code
            )
        except requests.RequestException as exc:
            logger.warning("Could not reach controller at %s: %s", url, exc)

    # ------------------------------------------------------------------
    # Node-down watcher  (separate thread)
    # ------------------------------------------------------------------

    def _timeout_watcher(self):
        """Detect links that have gone silent for > NODE_TIMEOUT_S seconds."""
        while self._running:
            time.sleep(5)
            now = time.time()
            to_alert = []

            with self._lock:
                for link_key, last_t in list(self._last_seen.items()):
                    if now - last_t > NODE_TIMEOUT_S:
                        last = self._last_alert.get(link_key, 0.0)
                        if now - last > ALERT_COOLDOWN_S:
                            self._last_alert[link_key] = now
                            self._active_alerts[link_key] = {
                                "type": "NODE_FAILURE",
                                "nodes": list(link_key),
                                "confidence": 1.0,
                                "detected_at": now,
                            }
                            self._total_anomalies += 1
                            to_alert.append(link_key)

            for link_key in to_alert:
                node_id, target = link_key
                logger.warning(
                    "NODE_FAILURE: %s→%s silent for >%.0fs",
                    node_id, target, NODE_TIMEOUT_S,
                )
                self._post_insight("NODE_FAILURE", [node_id, target], 1.0)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        self._running = True

        self._client = mqtt.Client()
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
        self._client.loop_start()

        watcher = threading.Thread(target=self._timeout_watcher, daemon=True)
        watcher.start()

        logger.info("ZANSubscriber started")

    def stop(self):
        self._running = False
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
        logger.info("ZANSubscriber stopped")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self):
        with self._lock:
            active_alerts = [
                {
                    "link": "{}→{}".format(k[0], k[1]),
                    "type": v["type"],
                    "confidence": v["confidence"],
                    "detected_at": v["detected_at"],
                }
                for k, v in self._active_alerts.items()
            ]
            return {
                "healthy": len(self._active_alerts) == 0,
                "active_links": len(self._last_seen),
                "active_alerts": len(self._active_alerts),
                "total_readings": self._total_received,
                "total_anomalies": self._total_anomalies,
                "alerts": active_alerts,
            }

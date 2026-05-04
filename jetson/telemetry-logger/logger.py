"""
ZAN telemetry logger.

Subscribes to zan/telemetry/# and appends each reading to a timestamped
CSV file under /logs. Creates a new file each time the container starts.
"""

import csv
import json
import logging
import os
import threading
import time

import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
LOG_DIR = os.environ.get("LOG_DIR", "/logs")
MQTT_TOPIC = "zan/telemetry/#"

CSV_FIELDS = [
    "received_at", "topic",
    "timestamp", "node_id", "target_node",
    "latency_ms", "rssi_dbm", "packet_loss_pct", "uptime_s",
]

_csv_file = None
_csv_writer = None
_write_lock = threading.Lock()


def open_log():
    global _csv_file, _csv_writer
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOG_DIR, "telemetry_{}.csv".format(ts))
    _csv_file = open(path, "w", newline="", buffering=1)
    _csv_writer = csv.DictWriter(_csv_file, fieldnames=CSV_FIELDS, extrasaction="ignore")
    _csv_writer.writeheader()
    logger.info("Logging to %s", path)


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Connected to %s:%d", MQTT_BROKER, MQTT_PORT)
        client.subscribe(MQTT_TOPIC)
        logger.info("Subscribed to %s", MQTT_TOPIC)
    else:
        logger.error("Connect failed rc=%d", rc)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception:
        return

    row = {k: payload.get(k, "") for k in CSV_FIELDS}
    row["received_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    row["topic"] = msg.topic

    with _write_lock:
        if _csv_writer:
            _csv_writer.writerow(row)

    logger.debug(
        "%s→%s lat=%.1f rssi=%d loss=%.4f",
        payload.get("node_id", "?"),
        payload.get("target_node", "?"),
        float(payload.get("latency_ms", 0)),
        int(payload.get("rssi_dbm", 0)),
        float(payload.get("packet_loss_pct", 0)),
    )


def main():
    open_log()

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as exc:
            logger.error("MQTT error: %s — retrying in 5s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()

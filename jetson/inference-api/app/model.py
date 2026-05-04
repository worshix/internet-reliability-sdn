"""
ZAN anomaly model wrapper.

Loads a pre-trained Isolation Forest from disk and provides:
  - extract_features(readings)   — convert a sliding window into a feature vector
  - classify_anomaly_type(readings) — rule-based type label
  - ZANAnomalyModel.score(readings) — returns (confidence: float, anomaly_type: str|None)
"""

import os
import pickle
import logging

import numpy as np

logger = logging.getLogger(__name__)

MODEL_PATH = os.environ.get("MODEL_PATH", "/models/isolation_forest.pkl")
ANOMALY_THRESHOLD = float(os.environ.get("ANOMALY_THRESHOLD", 0.75))
FEATURE_WINDOW = 10


def extract_features(readings):
    """
    Convert a list of telemetry dicts (one link) into a 7-element feature vector.
    Returns None if fewer than FEATURE_WINDOW readings are available.

    Feature vector:
        [mean_latency, std_latency, latency_slope,
         mean_rssi,    rssi_slope,
         mean_packet_loss, max_packet_loss]
    """
    if len(readings) < FEATURE_WINDOW:
        return None

    window = readings[-FEATURE_WINDOW:]
    lat = np.array([r["latency_ms"] for r in window], dtype=float)
    rssi = np.array([r["rssi_dbm"] for r in window], dtype=float)
    pkt = np.array([r["packet_loss_pct"] for r in window], dtype=float)

    x = np.arange(FEATURE_WINDOW, dtype=float)
    lat_slope = float(np.polyfit(x, lat, 1)[0])
    rssi_slope = float(np.polyfit(x, rssi, 1)[0])

    return [
        float(np.mean(lat)),
        float(np.std(lat)),
        lat_slope,
        float(np.mean(rssi)),
        rssi_slope,
        float(np.mean(pkt)),
        float(np.max(pkt)),
    ]


def classify_anomaly_type(readings):
    """
    Rule-based classification of the anomaly type.
    Maps to the insight types expected by the os-ken controller.

    Returns one of:
        LINK_FAILURE      — 100 % packet loss / latency sentinel 999 ms
        RF_INTERFERENCE   — RSSI below −55 dBm
        CONGESTION        — elevated packet loss with normal RSSI
        LINK_DEGRADATION  — rising latency, otherwise normal
    """
    if not readings:
        return "LINK_FAILURE"

    latest = readings[-1]
    recent = readings[-min(5, len(readings)):]

    if latest["latency_ms"] >= 999.0 or latest["packet_loss_pct"] >= 1.0:
        return "LINK_FAILURE"

    avg_rssi = float(np.mean([r["rssi_dbm"] for r in recent]))
    if avg_rssi < -55:
        return "RF_INTERFERENCE"

    avg_loss = float(np.mean([r["packet_loss_pct"] for r in recent]))
    if avg_loss > 0.15:
        return "CONGESTION"

    return "LINK_DEGRADATION"


class ZANAnomalyModel:
    def __init__(self):
        self._clf = None

    def load(self, path=None):
        path = path or MODEL_PATH
        with open(path, "rb") as fh:
            self._clf = pickle.load(fh)
        logger.info("Isolation Forest loaded from %s", path)

    def is_loaded(self):
        return self._clf is not None

    def score(self, readings):
        """
        Score a sliding window for one link.

        Returns
        -------
        confidence : float  0.0 (normal) → 1.0 (definite anomaly)
        anomaly_type : str | None   None when confidence ≤ threshold
        """
        if self._clf is None:
            raise RuntimeError("Model not loaded — call load() first")

        features = extract_features(readings)
        if features is None:
            return 0.0, None

        # decision_function: positive = normal, negative = anomaly
        # Typical range ≈ −0.5 … +0.5  →  map to 0…1 confidence
        raw = float(self._clf.decision_function([features])[0])
        confidence = max(0.0, min(1.0, 0.5 - raw))

        anomaly_type = None
        if confidence > ANOMALY_THRESHOLD:
            anomaly_type = classify_anomaly_type(readings)

        return confidence, anomaly_type

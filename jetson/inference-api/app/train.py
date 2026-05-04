"""
Standalone training script for the ZAN Isolation Forest anomaly detector.

Usage:
    python train.py

Or imported by main.py on startup if /models/isolation_forest.pkl is absent.

Environment variables:
    DATASET_PATH  path to the labelled telemetry CSV  (default: /models/dataset.csv)
    MODEL_PATH    where to save the trained model      (default: /models/isolation_forest.pkl)
"""

import os
import pickle
import logging

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

DATASET_PATH = os.environ.get("DATASET_PATH", "/models/dataset.csv")
MODEL_PATH = os.environ.get("MODEL_PATH", "/models/isolation_forest.pkl")
FEATURE_WINDOW = 10


def load_dataset(path):
    """Read CSV and tolerate truncated/comment rows produced by AI generators."""
    logger.info("Reading dataset from %s", path)
    try:
        df = pd.read_csv(path, on_bad_lines="skip")
    except TypeError:
        df = pd.read_csv(path, error_bad_lines=False)

    for col in ("node_id", "target_node", "anomaly_type"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.rstrip(".,")

    numeric_cols = [
        "timestamp", "latency_ms", "rssi_dbm",
        "packet_loss_pct", "uptime_s", "anomaly_label",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["latency_ms", "rssi_dbm", "packet_loss_pct"])
    logger.info("  %d usable rows (dropped %d bad)", len(df), before - len(df))
    return df


def extract_features(df):
    """
    For every (node_id, target_node) pair, slide a window of FEATURE_WINDOW
    readings and compute summary statistics.

    Feature vector (7 elements):
        [mean_latency, std_latency, latency_slope,
         mean_rssi,    rssi_slope,
         mean_packet_loss, max_packet_loss]
    """
    rows = []
    df = df.sort_values(["node_id", "target_node", "timestamp"]).reset_index(drop=True)

    for (node, target), grp in df.groupby(["node_id", "target_node"]):
        grp = grp.reset_index(drop=True)
        lat = grp["latency_ms"].values.astype(float)
        rssi = grp["rssi_dbm"].values.astype(float)
        pkt = grp["packet_loss_pct"].values.astype(float)

        for end in range(FEATURE_WINDOW, len(grp) + 1):
            w_lat = lat[end - FEATURE_WINDOW : end]
            w_rssi = rssi[end - FEATURE_WINDOW : end]
            w_pkt = pkt[end - FEATURE_WINDOW : end]

            x = np.arange(FEATURE_WINDOW, dtype=float)
            lat_slope = float(np.polyfit(x, w_lat, 1)[0])
            rssi_slope = float(np.polyfit(x, w_rssi, 1)[0])

            rows.append([
                float(np.mean(w_lat)),
                float(np.std(w_lat)),
                lat_slope,
                float(np.mean(w_rssi)),
                rssi_slope,
                float(np.mean(w_pkt)),
                float(np.max(w_pkt)),
            ])

    return np.array(rows, dtype=float)


def train():
    df = load_dataset(DATASET_PATH)

    normal_df = df[df["anomaly_label"] == 0].copy()
    logger.info("Normal rows available for training: %d", len(normal_df))

    if len(normal_df) < 30:
        raise ValueError(
            "Only {} normal rows found — need at least 30.".format(len(normal_df))
        )

    logger.info("Extracting features (window=%d) ...", FEATURE_WINDOW)
    X = extract_features(normal_df)
    logger.info("  Feature matrix: %s", X.shape)

    if len(X) == 0:
        raise ValueError("Feature extraction produced no vectors — check dataset format.")

    logger.info("Training Isolation Forest (n_estimators=200, contamination=0.05) ...")
    clf = IsolationForest(
        n_estimators=200,
        contamination=0.05,
        max_samples="auto",
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X)

    out_dir = os.path.dirname(MODEL_PATH)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(MODEL_PATH, "wb") as fh:
        pickle.dump(clf, fh)
    logger.info("Model saved → %s", MODEL_PATH)

    return clf


if __name__ == "__main__":
    train()

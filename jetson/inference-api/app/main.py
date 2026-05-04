"""
ZAN Inference API — FastAPI entrypoint.

On startup:
  1. Train Isolation Forest from dataset.csv if no saved model exists.
  2. Load the model.
  3. Start the MQTT subscriber (sliding-window inference loop).

Endpoints:
  GET  /zan/health   — liveness probe
  GET  /zan/ready    — readiness probe (503 until model loaded)
  GET  /zan/status   — full network health summary
  GET  /zan/alerts   — active anomaly alerts only
"""

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from model import ZANAnomalyModel
from mqtt_subscriber import ZANSubscriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

MODEL_PATH = os.environ.get("MODEL_PATH", "/models/isolation_forest.pkl")
DATASET_PATH = os.environ.get("DATASET_PATH", "/models/dataset.csv")

app = FastAPI(
    title="ZAN Inference API",
    description="Edge-AI anomaly detection for the Zimbabwe Adaptive Network",
    version="1.0.0",
)

_model = ZANAnomalyModel()
_subscriber = ZANSubscriber(_model)


@app.on_event("startup")
async def startup():
    if not os.path.exists(MODEL_PATH):
        logger.info("No model at %s — running train.py first …", MODEL_PATH)
        from train import train
        train()

    _model.load(MODEL_PATH)
    _subscriber.start()
    logger.info("ZAN Inference API ready")


@app.on_event("shutdown")
async def shutdown():
    _subscriber.stop()


@app.get("/zan/health", summary="Liveness probe")
async def health():
    return {"status": "ok"}


@app.get("/zan/ready", summary="Readiness probe")
async def ready():
    if not _model.is_loaded():
        raise HTTPException(status_code=503, detail="Model not yet loaded")
    return {"ready": True, "model": MODEL_PATH}


@app.get("/zan/status", summary="Full network health summary")
async def status():
    return JSONResponse(content=_subscriber.get_status())


@app.get("/zan/alerts", summary="Active anomaly alerts")
async def alerts():
    return JSONResponse(content=_subscriber.get_status()["alerts"])

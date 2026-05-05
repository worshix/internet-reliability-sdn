# python:3.8-slim is multi-arch (amd64 + arm64) — works on Jetson TX2 without NVIDIA runtime.
# The model is sklearn IsolationForest (CPU-only), no GPU needed.
FROM python:3.8-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /models

COPY app/ .

EXPOSE 8000

CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

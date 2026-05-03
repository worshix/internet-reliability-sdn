FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir \
    --timeout 300 \
    --retries 10 \
    -r requirements.txt
    
COPY app/ /app/

EXPOSE 6653 8080

CMD ["os-ken-manager", "--ofp-tcp-listen-port", "6653", "zan_controller"]
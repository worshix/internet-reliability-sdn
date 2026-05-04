# Jetson TX2 — JetPack 4.6.1 (r32.7.1)
# Check your version: cat /etc/nv_tegra_release
# Override for local x86 dev: docker build --build-arg BASE_IMAGE=python:3.9-slim .
ARG BASE_IMAGE=nvcr.io/nvidia/l4t-pytorch:r32.7.1-pth1.10-py3
FROM ${BASE_IMAGE}

# Install Python 3.8 alongside the default Python 3.6 in the l4t image
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common curl ca-certificates \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.8 python3.8-distutils python3.8-dev \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.8 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.8 10 \
    && apt-get purge -y software-properties-common \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python3.8 -m pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /models

COPY app/ .

EXPOSE 8000

CMD ["python3.8", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

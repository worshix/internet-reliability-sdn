FROM python:3.9-slim

WORKDIR /app

RUN pip3 install --no-cache-dir paho-mqtt==1.6.1

COPY logger.py .

CMD ["python3", "logger.py"]

# ZAN — Zimbabwe Adaptive Network
## ESP32 Firmware & Project Progress Tracker

> This file is the living memory of the project. It is updated after each
> implementation step to reflect current status, known values, and next actions.

---

## Quick Reference

| Item | Value |
|---|---|
| WiFi SSID | `internet-sdn` |
| WiFi Password | `internet-sdn` |
| MQTT broker | Jetson TX2 IP — **see Step 3** |
| MQTT port | `1883` |
| MQTT topic format | `zan/telemetry/esp32_0<N>` |
| Arduino-ESP32 core | >= 3.0.0 required |
| Required libraries | `PubSubClient`, `ArduinoJson` (gateway only) |

---

## Board Map

| File | Board | node_id | Role |
|---|---|---|---|
| `esp32/gateway/gateway.ino` | ESP32 #1 | 1 | Gateway — WiFi bridge to MQTT |
| `esp32/node_1/node_1.ino` | ESP32 #2 | 2 | Sensor node |
| `esp32/node_2/node_2.ino` | ESP32 #3 | 3 | Sensor node |
| `esp32/node_3/node_3.ino` | ESP32 #4 | 4 | Sensor node |
| `esp32/node_4/node_4.ino` | ESP32 #5 | 5 | Sensor node |

---

## Phase 1 Progress — ESP32 Telemetry Pipeline

- [x] Sensor node firmware written (node_1 – node_4)
- [x] Gateway firmware written
- [x] **Step 1:** Get MAC addresses from all 5 boards
- [x] **Step 2:** Update MAC addresses in all firmware files
- [ ] **Step 3:** Find Jetson IP and update gateway firmware
- [ ] **Step 4:** Install Arduino libraries on your machine
- [ ] **Step 5:** Flash all 5 boards
- [ ] **Step 6:** Start Mosquitto on Jetson and verify telemetry arrives
- [ ] **Step 7:** Log telemetry to CSV

---

## Step 1 — Get MAC Addresses (do this before flashing anything else)

Each ESP32 has a unique MAC address burned into its hardware. You need these
to configure ESP-NOW peer registration.

**How:** Flash this tiny sketch to each board one at a time, open Serial Monitor
at 115200 baud, and record the printed MAC address.

```cpp
#include <WiFi.h>
void setup() {
    Serial.begin(115200);
    WiFi.mode(WIFI_STA);
    Serial.println(WiFi.macAddress());
}
void loop() {}
```

**Record your MAC addresses here:**

| Board | node_id | MAC Address |
|---|---|---|
| ESP32 #1 (gateway) | 1 | `30:76:F5:A6:AD:4C` |
| ESP32 #2 | 2 | `B4:BF:E9:33:A5:60` |
| ESP32 #3 | 3 | `D4:E9:F4:C5:3E:54` |
| ESP32 #4 | 4 | `E0:8C:FE:31:EB:0C` |
| ESP32 #5 | 5 | `D4:E9:F4:C4:40:BC` |

---

## Step 2 — Update MAC Addresses in Firmware

In **every** `.ino` file (gateway + all 4 nodes), update the MAC address arrays
near the top of each file:

```cpp
uint8_t GATEWAY_MAC[6] = {0xXX, 0xXX, 0xXX, 0xXX, 0xXX, 0xXX};
uint8_t NODE2_MAC[6]   = {0xXX, 0xXX, 0xXX, 0xXX, 0xXX, 0xXX};
uint8_t NODE3_MAC[6]   = {0xXX, 0xXX, 0xXX, 0xXX, 0xXX, 0xXX};
uint8_t NODE4_MAC[6]   = {0xXX, 0xXX, 0xXX, 0xXX, 0xXX, 0xXX};
uint8_t NODE5_MAC[6]   = {0xXX, 0xXX, 0xXX, 0xXX, 0xXX, 0xXX};
```

Convert MAC `AA:BB:CC:DD:EE:FF` → `{0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF}`.

---

## Step 3 — Find Jetson IP and Update Gateway

On the Jetson TX2, run:

```bash
hostname -I
```

Take the first IP shown (e.g. `192.168.1.42`). In
`esp32/gateway/gateway.ino`, update:

```cpp
const char* MQTT_BROKER = "192.168.1.42";   // replace with real Jetson IP
```

**Jetson IP (fill in when known):** `192.168.1.50`

---

## Step 4 — Install Arduino Libraries

In Arduino IDE: **Sketch → Include Library → Manage Libraries**

| Library | Author | Used by |
|---|---|---|
| `PubSubClient` | Nick O'Leary | gateway only |
| `ArduinoJson` | Benoit Blanchon | gateway only |

Sensor nodes use only built-in ESP32 libraries (`esp_now.h`, `WiFi.h`).

Also verify: **Tools → Board → ESP32 Arduino** is installed and version ≥ 3.0.0.

---

## Step 5 — Flash Order

Flash in this order to avoid ESP-NOW channel issues:

1. **Gateway first** — it connects to WiFi and fixes the channel
2. **Sensor nodes** — they inherit the channel automatically

For each board: select the correct `.ino` file, select your ESP32 board model,
select the right COM port, then Upload.

---

## Step 6 — Start Mosquitto on Jetson and Verify

On the Jetson TX2:

```bash
# Install (first time only)
sudo apt install mosquitto mosquitto-clients

# Start broker
sudo systemctl start mosquitto

# Subscribe to all ZAN telemetry topics to verify data is arriving
mosquitto_sub -h localhost -t "zan/#" -v
```

Expected output (every ~5 seconds per node-pair):

```
zan/telemetry/esp32_02 {"node_id":"esp32_02","target_node":"esp32_03","latency_ms":24.3,"rssi_dbm":-67,"packet_loss_pct":0.0,"uptime_s":42,"timestamp":1711900042}
```

---

## Step 7 — Log Telemetry to CSV

Save this Python script on the Jetson as `log_telemetry.py`:

```python
import paho.mqtt.client as mqtt
import json, csv, time, os

CSV_FILE = "zan_telemetry.csv"
BROKER   = "localhost"

fieldnames = ["timestamp", "node_id", "target_node",
              "latency_ms", "rssi_dbm", "packet_loss_pct", "uptime_s"]

def on_connect(client, userdata, flags, rc, props=None):
    client.subscribe("zan/telemetry/#")
    print(f"[ZAN Logger] Connected rc={rc}, subscribed to zan/telemetry/#")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload)
        payload["timestamp"] = time.time()
        file_exists = os.path.isfile(CSV_FILE)
        with open(CSV_FILE, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if not file_exists:
                w.writeheader()
            w.writerow(payload)
        print(payload)
    except Exception as e:
        print(f"[ZAN Logger] Error: {e}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, 1883)
client.loop_forever()
```

Run it:

```bash
pip install paho-mqtt
python3 log_telemetry.py
```

**Phase 1 is complete when** `zan_telemetry.csv` is growing with real readings
from all 4 sensor nodes every 5 seconds.

---

## Troubleshooting

### ESP-NOW packets not arriving at gateway
The most common cause is a WiFi channel mismatch. The gateway connects to the
router (e.g. channel 6) but sensor nodes default to channel 1.

**Fix:** Find your router's WiFi channel (check router admin page). In all
sensor node `.ino` files, add after `WiFi.mode(WIFI_STA)`:
```cpp
esp_wifi_set_channel(6, WIFI_SECOND_CHAN_NONE);  // replace 6 with your channel
```
Add `#include "esp_wifi.h"` at the top.

### MQTT not connecting
- Confirm Mosquitto is running: `sudo systemctl status mosquitto`
- Check Mosquitto allows external connections: edit `/etc/mosquitto/mosquitto.conf`
  and ensure it contains:
  ```
  listener 1883
  allow_anonymous true
  ```
  Then restart: `sudo systemctl restart mosquitto`
- Confirm gateway and Jetson are on the same WiFi network
- Ping the Jetson from another device to confirm the IP is correct

### Latency reads 999 ms
This means no pong was received for that peer. Check:
- Both boards are powered and within ESP-NOW range (10–50 m indoors)
- MAC addresses are entered correctly
- The peer's firmware compiled and flashed without errors

---

## Firmware Architecture (reference)

```
Sensor node (×4)                    Gateway (×1)
┌─────────────────────┐             ┌──────────────────────────────┐
│ loop() every 2 s:   │  ESP-NOW    │ onDataRecv() callback:       │
│  sendPing(peer)     │────────────►│  xQueueSend(telemetry_q)     │
│                     │             │                              │
│ onDataRecv():       │  ESP-NOW    │ loop():                      │
│  PKT_PING → PONG    │◄────────────│  xQueueReceive()             │
│  PKT_PONG → record  │             │  publishTelemetry() → MQTT   │
│    RTT + RSSI       │             │                              │
│                     │             │ WiFi: internet-sdn           │
│ loop() every 5 s:   │  ESP-NOW    │ MQTT: Jetson TX2:1883        │
│  sendTelemetry()    │────────────►│ Topic: zan/telemetry/esp32_0N│
└─────────────────────┘             └──────────────────────────────┘
```

### Packet types

| Type | Size | Direction | Purpose |
|---|---|---|---|
| `PKT_PING` (0x01) | 8 B | node → peer | RTT measurement request |
| `PKT_PONG` (0x02) | 8 B | peer → node | RTT measurement reply |
| `PKT_TELEMETRY` (0x03) | 16 B | node → gateway | 5-second stats summary |

### MQTT JSON payload

```json
{
  "node_id":         "esp32_02",
  "target_node":     "esp32_03",
  "latency_ms":      24.3,
  "rssi_dbm":        -67,
  "packet_loss_pct": 0.02,
  "uptime_s":        120,
  "timestamp":       1711900000
}
```

---

## Upcoming Phases

| Phase | Goal | Status |
|---|---|---|
| Phase 1 | ESP32 telemetry pipeline | **In progress** |
| Phase 2 | Mininet + Ryu control plane | Not started |
| Phase 3 | AI anomaly detection model | Not started |
| Phase 4 | Edge-Inference integration (Jetson FastAPI → Ryu) | Not started |
| Phase 5 | AQoSRM full integration & thesis measurements | Not started |

---

*Last updated: Steps 1 & 2 complete — MAC addresses recorded and flashed into all firmware. Next: get Jetson IP (Step 3), install libraries (Step 4), flash boards (Step 5).*

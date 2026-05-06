# ZAN — Zimbabwe Adaptive Network
### AI-Driven SDN Network Reliability Platform

> A self-healing network management system that uses edge AI inference on a Jetson TX2,
> ESP32 wireless sensor nodes, and an SDN controller on a Linux PC to detect network
> anomalies in real time and automatically reroute traffic — with a live web dashboard.

---

## Table of Contents

1. [What Is ZAN?](#1-what-is-zan)
2. [How It Works — The Big Picture](#2-how-it-works--the-big-picture)
3. [System Architecture](#3-system-architecture)
4. [Hardware Requirements](#4-hardware-requirements)
5. [Repository Folder Structure](#5-repository-folder-structure)
6. [Quick Reference — Current Network Values](#6-quick-reference--current-network-values)
7. [Setting Up on a New Network (IP Changes)](#7-setting-up-on-a-new-network-ip-changes)
8. [Jetson TX2 Setup](#8-jetson-tx2-setup)
9. [Linux PC Setup](#9-linux-pc-setup)
10. [ESP32 Firmware Setup](#10-esp32-firmware-setup)
11. [Dashboard User Guide](#11-dashboard-user-guide)
12. [The AI Model — Isolation Forest](#12-the-ai-model--isolation-forest)
13. [SDN Controller — ZANController](#13-sdn-controller--zancontroller)
14. [Mininet Virtual Topology](#14-mininet-virtual-topology)
15. [MQTT Topics & Payload Formats](#15-mqtt-topics--payload-formats)
16. [Environment Variable Reference](#16-environment-variable-reference)
17. [Docker & Container Reference](#17-docker--container-reference)
18. [Admin Credentials](#18-admin-credentials)
19. [API Endpoint Reference](#19-api-endpoint-reference)
20. [Troubleshooting](#20-troubleshooting)

---

## 1. What Is ZAN?

Zimbabwe's internet infrastructure suffers from delayed fault recovery. When a link fails,
legacy routing protocols (OSPF, BGP) can take seconds to minutes to converge on a new path.
During that time, real-time services — VoIP calls, telemedicine, online banking — are degraded
or completely interrupted.

**ZAN (Zimbabwe Adaptive Network)** is a research prototype that solves this using three
technologies working together:

- **Software-Defined Networking (SDN)** — a central controller has a complete real-time
  map of the network and can reprogram every switch's forwarding rules within milliseconds.
- **Edge AI Inference** — an Isolation Forest anomaly model runs on a Jetson TX2 and
  continuously analyses live telemetry from ESP32 sensor nodes. When it detects a failing
  link, it sends an actionable alert to the SDN controller.
- **AQoSRM (Adaptive QoS Routing Mechanism)** — when faults are detected or the
  network is congested, AQoSRM prioritises VoIP and telemedicine traffic over bulk
  transfers so that the most important services remain usable even during degradation.

The result is a network that detects faults in under 20 seconds and reroutes traffic without
human intervention.

---

## 2. How It Works — The Big Picture

```
┌─────── Physical Layer (ESP32 Mesh) ─────────────────────────────────────────┐
│                                                                              │
│  esp32_01 ←──ESP-NOW──→ esp32_02                                            │
│       │                      │    (every 2 s: ping each peer, record RTT)   │
│  esp32_03 ←──ESP-NOW──→ esp32_04                                            │
│       │                                                                      │
│  esp32_gateway (ESP32 #5) ←── collects all telemetry via ESP-NOW            │
│       │                                                                      │
│       │  MQTT over WiFi (topic: zan/telemetry/#)                            │
│       ▼                                                                      │
└──────────────────────────────────────────────────────────────────────────── ┘
                 │
                 ▼
┌─────── Jetson TX2 (Docker containers) ──────────────────────────────────────┐
│                                                                              │
│  mosquitto        — MQTT broker, receives all ESP32 telemetry               │
│  inference-api    — subscribes to MQTT, runs Isolation Forest on a          │
│                     sliding window per link, detects anomalies,             │
│                     POSTs insights to controller + publishes to MQTT         │
│  telemetry-logger — writes every reading to /logs/*.csv for audit           │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────── ┘
                 │
                 │  HTTP POST  /zan/insight   (LAN, port 8080)
                 │  MQTT publish zan/insights  (for dashboard)
                 ▼
┌─────── Linux PC (Docker + bare metal) ──────────────────────────────────────┐
│                                                                              │
│  zan-controller  (Docker, host network)                                     │
│    — os-ken SDN controller on TCP 6653 (OpenFlow 1.3)                      │
│    — REST API on port 8080                                                  │
│    — receives AI insights, marks link degraded, clears flows on             │
│      affected switches so traffic re-learns via BFS shortest path           │
│    — AQoSRM: classifies flows by traffic type, installs priority queues     │
│                                                                              │
│  zan-dashboard  (Docker, host network)                                      │
│    — Flask + Socket.IO web app on port 5000                                 │
│    — subscribes to MQTT for live telemetry + AI alerts                      │
│    — proxies controller REST API for topology data                          │
│    — live charts, gauges, SDN topology panel, AI alert log                  │
│                                                                              │
│  Mininet  (bare metal, requires root)                                       │
│    — creates 5 virtual OVS switches (s1–s5) + 5 hosts (h1–h5)             │
│    — connects to zan-controller via OpenFlow on 127.0.0.1:6653             │
│    — mirrors the physical ESP32 topology (each switch = one ESP32 node)    │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────── ┘
```

**End-to-end anomaly response timeline:**

1. ESP32 nodes detect degrading RSSI/latency and report via MQTT (~5 s cadence)
2. Jetson inference-api accumulates a 10-reading window per link and scores it
3. If the Isolation Forest confidence > 0.75 **or** RSSI < −55 dBm, it fires an alert
4. Alert is POSTed to `http://<linux-pc>:8080/zan/insight` (controller) AND published to `zan/insights` (MQTT)
5. Controller marks the link degraded, clears flow tables on both endpoint switches
6. Mininet hosts re-learn new paths via BFS, automatically avoiding the degraded link
7. Dashboard receives the MQTT insight → shows alert row with "✓ Rerouted" badge + topology panel updates red

**Total response time: < 25 seconds** (dominated by the 10-reading window accumulation at 5 s/reading = ~50 s for Isolation Forest path; the rule-based RSSI hard floor can trigger in ~50 s too; NODE_FAILURE via silence timeout = 20 s).

---

## 3. System Architecture

### Physical-to-Virtual Topology Mapping

The ESP32 physical mesh is a **scale model** of the Mininet virtual topology.
Each ESP32 node maps to one Mininet switch and one Mininet host.

| ESP32 Node | Mininet Switch | Mininet Host | IP Address  | Represents (Zimbabwe ISP) |
|---|---|---|---|---|
| esp32_01 | s1 | h1 | 10.0.0.1 | Harare node |
| esp32_02 | s2 | h2 | 10.0.0.2 | Bulawayo node |
| esp32_03 | s3 | h3 | 10.0.0.3 | Mutare node |
| esp32_04 | s4 | h4 | 10.0.0.4 | Gweru node |
| esp32_gateway | s5 | h5 | 10.0.0.5 | Masvingo node |

| ESP32 Wireless Link | SDN Virtual Link | Bandwidth | Delay |
|---|---|---|---|
| esp32_01 ↔ esp32_02 | s1 ↔ s2 | 10 Mbps | 5 ms |
| esp32_02 ↔ esp32_03 | s2 ↔ s3 | 10 Mbps | 8 ms |
| esp32_01 ↔ esp32_03 | s1 ↔ s3 | 5 Mbps | 10 ms (redundant path) |
| esp32_03 ↔ esp32_04 | s3 ↔ s4 | 8 Mbps | 6 ms |
| esp32_04 ↔ esp32_gateway | s4 ↔ s5 | 5 Mbps | 4 ms |

When the AI flags `esp32_01 ↔ esp32_02` as degraded, the controller knows to reroute the
`s1 ↔ s2` Mininet link. This deliberate mapping is the core of the research contribution.

---

## 4. Hardware Requirements

| Device | Quantity | Purpose |
|---|---|---|
| Linux PC (Ubuntu 22.04+) | 1 | SDN controller, dashboard, Mininet host |
| NVIDIA Jetson TX2 | 1 | MQTT broker, AI edge inference |
| ESP32 development board | 5 | Wireless sensor mesh (4 nodes + 1 gateway) |
| USB cables | 5 | Flashing firmware |
| WiFi router/access point | 1 | LAN connecting Jetson, Linux PC, ESP32 gateway |

**Software prerequisites — Linux PC:**
- Docker + Docker Compose
- Python 3.10+, Mininet, Open vSwitch
- `mosquitto-clients` (for test publishing)

**Software prerequisites — Jetson TX2:**
- Docker + Docker Compose
- JetPack 4.x or 5.x

**Software prerequisites — Development machine:**
- Arduino IDE 2.x with ESP32 Arduino core ≥ 3.0.0
- Libraries: `PubSubClient`, `ArduinoJson` (gateway only)

---

## 5. Repository Folder Structure

```
internet-reliability-sdn/
│
├── esp32/                          # Arduino firmware for all 5 ESP32 boards
│   ├── gateway/
│   │   └── gateway.ino             # Gateway: collects ESP-NOW telemetry, publishes to MQTT
│   ├── node_1/ … node_4/
│   │   └── node_N.ino              # Sensor nodes: ping peers, measure RTT/RSSI/loss
│
├── jetson/                         # Everything that runs on the Jetson TX2
│   ├── .env                        # ← EDIT THIS for your network (see §16)
│   ├── docker-compose.yml          # Defines mosquitto, inference-api, telemetry-logger
│   ├── dataset.csv                 # Training dataset for the Isolation Forest model
│   ├── models/
│   │   └── isolation_forest.pkl   # Trained model (auto-generated by train.py)
│   ├── mosquitto/
│   │   └── mosquitto.conf          # Allows anonymous connections on port 1883
│   ├── inference-api/
│   │   ├── Dockerfile
│   │   └── app/
│   │       ├── main.py             # FastAPI entry point, starts ZANSubscriber
│   │       ├── mqtt_subscriber.py  # MQTT client, sliding window, anomaly firing
│   │       ├── model.py            # Isolation Forest wrapper + rule-based hard floor
│   │       └── train.py            # Standalone model training script
│   └── telemetry-logger/
│       └── ...                     # Subscribes to MQTT and writes CSV logs
│
├── linux-pc/                       # Everything that runs on the Linux PC
│   ├── docker-compose.yml          # Defines zan-controller + zan-dashboard (host network)
│   ├── controller/
│   │   ├── Dockerfile
│   │   └── app/
│   │       ├── zan_controller.py   # os-ken app: OpenFlow handler, REST API, AQoSRM, BFS reroute
│   │       ├── aqosrm.py           # Adaptive QoS Routing Mechanism (meter + queue logic)
│   │       └── topology_map.py     # ESP32 ↔ Mininet dpid mapping (LINK_MAP, ESP32_TO_DPID)
│   ├── dashboard/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── app.py                  # Flask + Socket.IO server, MQTT client, proxy routes
│   │   ├── auth.py                 # Flask-Login user model
│   │   ├── database.py             # SQLite: users, settings, telemetry_log tables
│   │   ├── templates/
│   │   │   ├── login.html
│   │   │   ├── dashboard.html      # Main live dashboard
│   │   │   ├── logs.html           # Paginated telemetry log viewer
│   │   │   └── settings.html       # MQTT broker / controller URL settings
│   │   └── static/
│   │       ├── css/style.css       # Dark theme, ZAN yellow colour scheme
│   │       └── js/main.js          # Socket.IO client, Chart.js graphs, Canvas Gauges, SDN panel
│   └── mininet/
│       └── zan_topology.py         # Mininet script: 5 switches, 5 hosts, QoS HTB queues
│
├── README.md                       # This file
├── README_V1.md                    # Original firmware setup notes (Phase 1)
├── overview.md                     # Detailed architecture and design rationale
└── DATASET_PROMPT.md               # AI prompt used to generate the training dataset
```

---

## 6. Quick Reference — Current Network Values

| Item | Value |
|---|---|
| **Linux PC IP** | `10.172.211.85` |
| **Jetson TX2 IP** | `10.172.211.12` |
| **WiFi SSID** | `internet-sdn` |
| **WiFi Password** | `internet-sdn` |
| **MQTT Broker** | Jetson TX2 — `10.172.211.12:1883` |
| **SDN Controller REST API** | `http://10.172.211.85:8080` |
| **Dashboard URL** | `http://10.172.211.85:5000` |
| **OpenFlow port** | `6653` (TCP, Mininet → controller) |
| **Dashboard admin username** | `admin` |
| **Dashboard admin password** | `zan-admin` |

---

## 7. Setting Up on a New Network (IP Changes)

When the system is deployed on a different network, IP addresses will change.
The following files must be updated. **Find every IP address that needs to change
and replace it with the new one.**

### 7.1 Find the new IPs first

On the **Linux PC**:
```bash
hostname -I    # note the first IP — this is your new Linux PC IP
```

On the **Jetson TX2**:
```bash
hostname -I    # note the first IP — this is your new Jetson IP
```

---

### 7.2 Files to Update

#### `jetson/.env` — Jetson environment variables

```env
LINUX_PC_URL=http://<NEW_LINUX_PC_IP>:8080   # ← change this
ANOMALY_THRESHOLD=0.75
WINDOW_SIZE=30
NODE_TIMEOUT_S=20
```

After editing, recreate the container (restart alone does not reload env vars):
```bash
cd ~/internet-reliability-sdn/jetson
docker-compose up -d inference-api
```

---

#### `esp32/gateway/gateway.ino` — ESP32 gateway firmware

Search for the `MQTT_BROKER` constant near the top of the file:
```cpp
const char* MQTT_BROKER = "10.172.211.12";   // ← change to new Jetson IP
```

After changing, reflash the gateway board via Arduino IDE.

---

#### Dashboard Settings (no file edit needed — done via UI)

Log into the dashboard → **Settings** page.

Change **MQTT Broker** to the new Jetson IP and **Controller URL** to the new Linux PC IP:

| Setting | New Value |
|---|---|
| MQTT Broker | `<NEW_JETSON_IP>` |
| MQTT Port | `1883` |
| Controller URL | `http://<NEW_LINUX_PC_IP>:8080` |

These settings are stored in the SQLite database and apply immediately without restart.

---

#### `linux-pc/database.py` — Default settings (only if resetting the database)

The defaults in `database.py` are only used when the database is first created:
```python
("mqtt_broker",    "localhost"),          # ← change to new Jetson IP
("controller_url", "http://localhost:8080"),  # this is fine since dashboard is on same host
```

The dashboard runs with `network_mode: host` so `localhost:8080` always reaches the
controller on the same machine.

---

#### Summary Checklist for New Network

- [ ] Note new Linux PC IP and new Jetson IP
- [ ] Edit `jetson/.env` → `LINUX_PC_URL`
- [ ] Run `docker-compose up -d inference-api` on Jetson
- [ ] Edit `esp32/gateway/gateway.ino` → `MQTT_BROKER`
- [ ] Reflash gateway ESP32
- [ ] Log in to dashboard → Settings → update MQTT Broker IP
- [ ] Verify dashboard shows live telemetry
- [ ] Test: `curl http://<linux-pc>:8080/zan/network-status`

---

## 8. Jetson TX2 Setup

### 8.1 First-Time Installation

```bash
# Clone the repository
git clone https://github.com/worshix/internet-reliability-sdn.git
cd internet-reliability-sdn/jetson

# Edit the .env file with your Linux PC IP
nano .env
```

```env
LINUX_PC_URL=http://<LINUX_PC_IP>:8080
ANOMALY_THRESHOLD=0.75
WINDOW_SIZE=30
NODE_TIMEOUT_S=20
```

```bash
# Start all Jetson services
docker-compose up -d

# Verify all three containers are running
docker-compose ps
```

Expected output:
```
jetson_mosquitto_1         Up   0.0.0.0:1883->1883/tcp
jetson_inference-api_1     Up   0.0.0.0:8000->8000/tcp
jetson_telemetry-logger_1  Up
```

### 8.2 Verify the MQTT Broker is Receiving Telemetry

```bash
docker exec -it jetson_mosquitto_1 \
  mosquitto_sub -h localhost -t "zan/#" -v
```

You should see a line every ~5 seconds per node pair:
```
zan/telemetry/esp32_02 {"node_id":"esp32_02","target_node":"esp32_03","latency_ms":14.2,...}
```

### 8.3 Verify the Inference API is Working

```bash
# Check it's up
curl http://localhost:8000/health

# Check its status (active alerts, total readings)
curl http://localhost:8000/status
```

### 8.4 Re-Training the Model

If you collect fresh telemetry and want to retrain the Isolation Forest:

```bash
# Place your new dataset.csv in jetson/dataset.csv
# Then run the training script inside the container
docker exec jetson_inference-api_1 python /app/train.py
docker-compose restart inference-api
```

### 8.5 View Inference Logs

```bash
docker-compose logs inference-api 2>&1 | tail -30

# Look for successful POSTs to the controller:
docker-compose logs inference-api 2>&1 | grep "POST\|HTTP\|WARNING"
```

---

## 9. Linux PC Setup

### 9.1 Install Dependencies (first time only)

```bash
# Docker
sudo apt update
sudo apt install -y docker.io docker-compose
sudo usermod -aG docker $USER   # re-login after this

# Mininet and Open vSwitch
sudo apt install -y mininet openvswitch-switch python3-mininet

# mosquitto clients (for testing)
sudo apt install -y mosquitto-clients
```

### 9.2 Start the Controller and Dashboard

```bash
cd ~/internet-reliability-sdn/linux-pc
docker-compose up -d

# Verify both containers are up
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Expected:
```
zan-controller   Up X minutes
zan-dashboard    Up X minutes
```

Verify the controller REST API is responding:
```bash
curl http://localhost:8080/zan/network-status
```

Expected (before Mininet starts):
```json
{"connected_switches": [], "degraded_links": [], "recent_insights": [], "mac_table": {}}
```

### 9.3 Start Mininet

Mininet **must run as root** on bare metal (not inside Docker):

```bash
sudo python3 ~/internet-reliability-sdn/linux-pc/mininet/zan_topology.py
```

This will:
1. Create 5 virtual OVS switches (s1–s5) and 5 hosts (h1–h5)
2. Connect each switch to the os-ken controller at `127.0.0.1:6653`
3. Configure HTB QoS queues on every inter-switch port (4 queues per port)
4. Drop you into the Mininet CLI (`mininet>`)

Verify switches connected to controller:
```bash
curl http://localhost:8080/zan/network-status
# "connected_switches" should now list [1,2,3,4,5]
```

### 9.4 Useful Mininet CLI Commands

```
mininet> pingall          # test connectivity between all hosts
mininet> h1 ping h5       # ping from h1 to h5
mininet> h1 iperf h5      # bandwidth test
mininet> dump             # show all nodes and links
mininet> exit             # cleanly stop Mininet and clean up QoS
```

### 9.5 View Container Logs

```bash
# Controller logs (shows OpenFlow events, reroutes, AI insights received)
docker logs zan-controller --tail 50

# Dashboard logs (shows MQTT connection, telemetry ingestion)
docker logs zan-dashboard --tail 50
```

### 9.6 Restart Containers

```bash
cd ~/internet-reliability-sdn/linux-pc
docker-compose restart              # restart both
docker-compose restart zan-controller
docker-compose restart zan-dashboard
```

---

## 10. ESP32 Firmware Setup

### 10.1 Board Roles

| File | Board | node_id | Role |
|---|---|---|---|
| `esp32/gateway/gateway.ino` | ESP32 #1 | gateway | WiFi bridge → MQTT broker |
| `esp32/node_1/node_1.ino` | ESP32 #2 | esp32_01 | Sensor node |
| `esp32/node_2/node_2.ino` | ESP32 #3 | esp32_02 | Sensor node |
| `esp32/node_3/node_3.ino` | ESP32 #4 | esp32_03 | Sensor node |
| `esp32/node_4/node_4.ino` | ESP32 #5 | esp32_04 | Sensor node |

### 10.2 MAC Addresses (current hardware)

| Board | node_id | MAC Address |
|---|---|---|
| ESP32 #1 (gateway) | gateway | `30:76:F5:A6:AD:4C` |
| ESP32 #2 | esp32_01 | `B4:BF:E9:33:A5:60` |
| ESP32 #3 | esp32_02 | `D4:E9:F4:C5:3E:54` |
| ESP32 #4 | esp32_03 | `E0:8C:FE:31:EB:0C` |
| ESP32 #5 | esp32_04 | `D4:E9:F4:C4:40:BC` |

If you change hardware, flash this to each new board to get its MAC:
```cpp
#include <WiFi.h>
void setup() { Serial.begin(115200); WiFi.mode(WIFI_STA); Serial.println(WiFi.macAddress()); }
void loop() {}
```

Then update the MAC arrays in every `.ino` file. Convert `AA:BB:CC:DD:EE:FF` → `{0xAA,0xBB,...}`.

### 10.3 Configuration Constants to Change

In `esp32/gateway/gateway.ino`:
```cpp
const char* WIFI_SSID     = "internet-sdn";       // your WiFi network name
const char* WIFI_PASSWORD = "internet-sdn";        // your WiFi password
const char* MQTT_BROKER   = "10.172.211.12";       // ← Jetson IP — CHANGE THIS
const int   MQTT_PORT     = 1883;
```

### 10.4 Flash Order

Flash in this exact order to avoid ESP-NOW channel mismatch:

1. **Gateway first** — it connects to WiFi and fixes the operating channel
2. **Sensor nodes** — they set their channel to match the gateway automatically

### 10.5 Verify Nodes Are Working

After flashing, open the Serial Monitor at **115200 baud** for any node.
You should see repeated lines like:
```
[ZAN] esp32_01→esp32_02  latency=14ms  rssi=-38dBm  loss=0.0%
```

On the Jetson, subscribe to confirm MQTT delivery:
```bash
docker exec jetson_mosquitto_1 \
  mosquitto_sub -h localhost -t "zan/telemetry/#" -v
```

---

## 11. Dashboard User Guide

### 11.1 Accessing the Dashboard

Open a browser and go to: `http://<LINUX_PC_IP>:5000`

You will be redirected to the login page. See [§18 Admin Credentials](#18-admin-credentials).

---

### 11.2 Health Banner

At the top of the dashboard is a status banner.

| State | Colour | Meaning |
|---|---|---|
| **Network Healthy** | Green with shield icon | No active AI anomaly alerts |
| **Anomaly Detected** | Yellow/amber with warning icon | At least one AI alert has fired recently |

---

### 11.3 Summary Statistics Row

Four counters shown at the top:

| Counter | Meaning |
|---|---|
| **Active Nodes** | Number of distinct ESP32 nodes that have sent telemetry in the last session |
| **Active Links** | Number of distinct node-pair links reporting measurements |
| **AI Alerts** | Total number of AI anomaly alerts received in this browser session |
| **Readings/min** | Estimated telemetry ingestion rate (derived from Socket.IO events per minute) |

---

### 11.4 SDN Topology Panel

Shows the live state of the Mininet virtual network.

**Switch badges (s1–s5):**

| Badge colour | Meaning |
|---|---|
| Grey | Switch is offline — not connected to the controller (Mininet not running) |
| Green | Switch is online and all its links are healthy |
| Red | Switch is online but has at least one degraded link |
| Yellow flash | Switch was just affected by a reroute event |

Each badge also shows `(Nh)` — the number of hosts whose MAC addresses have been
learned by that switch. Example: `s1 (1h)` means one host is communicating through s1.

**Degraded Links panel:**
Shows which switch pairs are currently marked degraded by the controller. Example: `s1 ↔ s2`.

**Clear button:**
Clicking **Clear** resets all degraded links on the controller. Switches return to green
on the next poll (~5 seconds). Use this after a node recovers from a fault.

**Last poll timestamp:** Updated every 5 seconds showing when the topology was last fetched.

---

### 11.5 Network Metrics — Live Gauges

Three Canvas Gauge instruments showing network-wide averages:

| Gauge | Unit | Range | Meaning |
|---|---|---|---|
| **Avg Latency** | ms | 0–100 | Average round-trip time across all active links |
| **Avg RSSI** | dBm | −100 to 0 | Average received signal strength (less negative = better signal) |
| **Packet Loss** | % | 0–100 | Average packet loss percentage across all links |

**Gauge colours:**
- Green needle: healthy range
- Orange/red needle: degraded range

The gauges update in real time as new telemetry arrives via Socket.IO.

---

### 11.6 Node Status Cards

One card per ESP32 sensor node (esp32_01 through esp32_04).

| Field | Meaning |
|---|---|
| **Live** badge (green) | Node is actively sending telemetry — last reading < 30 seconds ago |
| **Offline** badge (grey) | No telemetry received recently |
| **Red border** | Node is involved in an active AI anomaly alert |
| **Latency** | Round-trip time to the most recently reported peer (ms) |
| **RSSI** | Signal strength of the most recently reported link (dBm) |
| **Pkt Loss** | Packet loss percentage on the most recently reported link (%) |
| **Uptime** | How long this ESP32 node has been running since last reset (seconds) |

---

### 11.7 Latency Trend Graph

A real-time line chart showing latency history for a selected link.
The link selector dropdown in the top-right of the chart lets you choose which
node-pair to inspect (e.g. `esp32_01 → esp32_02`).

- **X-axis:** time (rolling 60-reading window, ~5 minutes at 5 s/reading)
- **Y-axis:** latency in milliseconds
- A **spike** in this graph is the first visual warning of a degrading link

---

### 11.8 RSSI Trend Graph

Same structure as the Latency Trend but plots `rssi_dbm` over time.

- Values trend towards 0 dBm when signal is excellent
- Values below −70 dBm indicate poor signal
- A **downward spike** (more negative) during a node-cover test triggers RF_INTERFERENCE

---

### 11.9 AI Anomaly Alerts

Every AI alert received via MQTT `zan/insights` appears here as a row.

| Column | Meaning |
|---|---|
| **NODE_FAILURE** badge (red) | The type of anomaly detected by the model |
| **Node pair** (e.g. `esp32_01 ↔ esp32_02`) | Which physical link the anomaly was detected on |
| **conf X.XX** | Confidence score from the model (0.0–1.0). `conf 1.00` = rule-based trigger |
| **Rerouting…** (pulsing yellow) | Reroute is in progress — waiting for controller confirmation |
| **✓ Rerouted** (green) | Controller confirmed the reroute: flows cleared, new paths learned |
| **Reroute attempted** (orange) | Controller was unreachable or link not in LINK_MAP |
| **Timestamp** | When the dashboard received the alert |

**Anomaly types:**

| Type | Trigger Condition |
|---|---|
| `NODE_FAILURE` | Node went completely silent for > 20 seconds (timeout watcher) |
| `RF_INTERFERENCE` | Average RSSI of last 5 readings dropped below −55 dBm |
| `CONGESTION` | Average packet loss > 15% with normal RSSI |
| `LINK_DEGRADATION` | Rising latency trend detected by Isolation Forest |

---

### 11.10 Settings Page

Navigate to **Settings** in the navbar. Configurable values:

| Setting | Default | Meaning |
|---|---|---|
| **MQTT Broker** | `localhost` | IP/hostname of the MQTT broker (Jetson TX2 IP on LAN) |
| **MQTT Port** | `1883` | MQTT broker port |
| **Controller URL** | `http://localhost:8080` | URL of the os-ken REST API |
| **Anomaly Threshold** | `0.75` | Isolation Forest confidence threshold (dashboard display only) |
| **Log Retention Days** | `7` | How long telemetry is kept in the database |

Changes take effect immediately. MQTT reconnects automatically when broker settings change.

---

### 11.11 Logs Page

A searchable, filterable table of all telemetry readings stored in the SQLite database.

- Filter by node using the dropdown
- Each row shows: timestamp, node, target, latency, RSSI, packet loss, uptime
- Useful for post-incident analysis

---

## 12. The AI Model — Isolation Forest

### 12.1 Why Isolation Forest?

The Isolation Forest is an **unsupervised anomaly detection** algorithm. This means it
learns what "normal" looks like from normal data only — it does not need labelled examples
of every failure mode.

This was chosen because:
- In a real network, anomalies are rare and varied — you cannot collect labelled examples of every fault type
- Isolation Forest is computationally lightweight and runs comfortably on the Jetson TX2 CPU
- It is robust to concept drift (gradual changes in baseline behaviour) when periodically retrained
- It has an interpretable confidence score that can be mapped to reroute aggressiveness

The alternative (a supervised classifier) would require a large labelled dataset for every
possible fault type — impractical in a research prototype.

### 12.2 Training Data

The model is trained on `jetson/dataset.csv`. This CSV contains simulated telemetry readings
for all 6 node-pair links under normal and anomalous conditions.

**CSV columns:**
```
timestamp, node_id, target_node, latency_ms, rssi_dbm, packet_loss_pct, uptime_s, anomaly_label, anomaly_type
```

`anomaly_label = 0` → normal, `anomaly_label = 1` → anomalous.

**The model is trained only on `anomaly_label = 0` rows.** The Isolation Forest learns the
distribution of normal behaviour. Anomalies are detected as points that are far from that
distribution.

### 12.3 Feature Engineering

Raw readings are aggregated into a **sliding window of 10 readings** per link.
Each window produces a 7-element feature vector:

| Feature | Description |
|---|---|
| `mean_latency` | Average RTT over the window (ms) |
| `std_latency` | Standard deviation of RTT — captures jitter |
| `latency_slope` | Linear trend of RTT — a positive slope = rising latency |
| `mean_rssi` | Average signal strength (dBm) |
| `rssi_slope` | Linear trend of RSSI — a negative slope = weakening signal |
| `mean_packet_loss` | Average packet loss fraction (0.0–1.0) |
| `max_packet_loss` | Maximum packet loss in the window |

This captures not just the current value but the **trend** — which is the key early warning signal.

### 12.4 Model Configuration

```
IsolationForest(
    n_estimators  = 200,     # 200 isolation trees — balances accuracy vs. speed
    contamination = 0.05,    # expect 5% anomalous windows in training data
    max_samples   = 'auto',  # auto-select sample size per tree
    random_state  = 42,      # reproducible results
    n_jobs        = -1,      # use all CPU cores on Jetson
)
```

### 12.5 Confidence Score

The raw output of Isolation Forest is a `decision_function` score:
- Positive → normal
- Negative → anomaly

This is mapped to a 0.0–1.0 confidence score:
```python
confidence = max(0.0, min(1.0, 0.5 - raw_score))
```

If `confidence > ANOMALY_THRESHOLD (0.75)`, an alert is fired.

### 12.6 Rule-Based Hard Floor (Belt-and-Suspenders)

To ensure physically obvious anomalies always trigger even if the Isolation Forest
underscores them, a rule-based check runs before the model score:

| Rule | Condition | Result |
|---|---|---|
| `RF_INTERFERENCE` | Average RSSI of last 5 readings < −55 dBm | confidence = 1.0, fires immediately |
| `LINK_FAILURE` | Latest latency ≥ 999 ms OR packet loss = 100% | confidence = 1.0, fires immediately |

These override the Isolation Forest and fire the alert unconditionally.

### 12.7 Alert Cooldown

Each link has a 30-second cooldown between alerts to prevent alert storms.
This is controlled by `ALERT_COOLDOWN_S = 30.0` in `mqtt_subscriber.py`.

### 12.8 Node Timeout Watcher

A background thread checks every 5 seconds whether any link has gone completely
silent. If a link has not reported for > `NODE_TIMEOUT_S` (default: 20 seconds),
a `NODE_FAILURE` alert is fired with `confidence = 1.0`.

---

## 13. SDN Controller — ZANController

The controller is an **os-ken** application (the actively-maintained OpenStack fork of Ryu).
It handles OpenFlow 1.3 events from Mininet switches and exposes a REST API.

### 13.1 Core Functionality

**MAC learning:** The controller learns which port each host MAC is reachable on.
When it receives a packet for an unknown destination, it floods; once learned, it installs
a specific flow rule pointing to the correct port.

**BFS path rerouting:** When an AI insight arrives marking a link degraded:
1. The link is added to `degraded_links`
2. Flow tables on both endpoint switches are cleared (`_clear_switch`)
3. The next packet from any host triggers a new flow lookup
4. `_bfs_path` computes the shortest path avoiding all degraded links
5. The new path is installed as flow rules hop-by-hop

**AQoSRM (Adaptive QoS Routing Mechanism):** Every new flow is classified by traffic type
and assigned to one of 4 HTB queues on the inter-switch ports:

| Queue | Traffic Class | Min Rate | Example |
|---|---|---|---|
| 0 | VoIP | 1 Mbps (guaranteed) | UDP 5004–5006, RTP |
| 1 | Video | 1 Mbps (guaranteed) | UDP 5000–5003, H.264 |
| 2 | Interactive | 500 kbps (guaranteed) | TCP port 80/443/8080 |
| 3 | Bulk | 2 Mbps max (rate-capped) | All other TCP |

The AQoSRM meter dynamically tightens the bulk queue rate limit based on anomaly
confidence — when confidence is high, bulk traffic is throttled more aggressively.

### 13.2 REST API Endpoints

All endpoints on `http://<LINUX_PC_IP>:8080`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/zan/network-status` | Returns connected switches, degraded links, recent AI insights, MAC table |
| `POST` | `/zan/insight` | Receives an AI anomaly insight, triggers reroute. Body: `{"type":"...","nodes":["esp32_01","esp32_02"],"confidence":0.95}` |
| `POST` | `/zan/clear-degraded` | Clears all degraded links. Switches return to green on the dashboard. |

**Response from `POST /zan/insight`:**
```json
{"status": "ok", "rerouted": true, "affected_dpids": [1, 2]}
```

`rerouted: true` means the switches were found connected and flows were cleared.
`rerouted: false` means Mininet was not running (switches not connected).

### 13.3 Topology Map (`topology_map.py`)

This file defines the physical-to-virtual mapping:

```python
ESP32_TO_DPID = {
    'esp32_01': 1,   # s1
    'esp32_02': 2,   # s2
    'esp32_03': 3,   # s3
    'esp32_04': 4,   # s4
}

LINK_MAP = {
    frozenset({'esp32_01', 'esp32_02'}): (1, 2),
    frozenset({'esp32_01', 'esp32_03'}): (1, 3),
    frozenset({'esp32_01', 'esp32_04'}): (1, 4),
    frozenset({'esp32_02', 'esp32_03'}): (2, 3),
    frozenset({'esp32_02', 'esp32_04'}): (2, 4),
    frozenset({'esp32_03', 'esp32_04'}): (3, 4),
}
```

When an insight arrives for a node pair, `LINK_MAP` is consulted to find the
corresponding Mininet switch pair and trigger the reroute on those exact switches.

---

## 14. Mininet Virtual Topology

The topology is defined in `linux-pc/mininet/zan_topology.py`.

```
h1 ── s1 ──(10Mbps/5ms)──── s2 ── h2
       │                     │
(5Mbps/10ms)          (10Mbps/8ms)
       │                     │
       └──────── s3 ─────────┘
                  │       h3
           (8Mbps/6ms)
                  │
                  s4 ── h4
                  │
           (5Mbps/4ms)
                  │
                  s5 ── h5
```

All inter-switch links use `TCLink` with bandwidth and delay limits.
The `s1–s3` link is the **redundant path** — BFS rerouting uses it when `s1–s2` or `s2–s3` is degraded.

**HTB QoS queues** are configured on every inter-switch port at startup:
- Queue 0 (VoIP): guaranteed 1 Mbps
- Queue 1 (Video): guaranteed 1 Mbps
- Queue 2 (Interactive): guaranteed 500 kbps
- Queue 3 (Bulk): max 2 Mbps

The controller connects to Mininet via `RemoteController` at `127.0.0.1:6653`.

---

## 15. MQTT Topics & Payload Formats

All MQTT topics use the broker on the Jetson TX2.

| Topic | Published by | Consumed by | Format |
|---|---|---|---|
| `zan/telemetry/<node_id>` | ESP32 gateway | Jetson inference-api, dashboard, telemetry-logger | JSON (see below) |
| `zan/insights` | Jetson inference-api | Dashboard | JSON (see below) |

### Telemetry payload (`zan/telemetry/esp32_02`)
```json
{
  "node_id":         "esp32_02",
  "target_node":     "esp32_03",
  "latency_ms":      14.2,
  "rssi_dbm":        -38,
  "packet_loss_pct": 0.0,
  "uptime_s":        3600,
  "timestamp":       1746000000.0
}
```

### Insight payload (`zan/insights`)
```json
{
  "type":       "RF_INTERFERENCE",
  "nodes":      ["esp32_01", "esp32_02"],
  "confidence": 1.0
}
```

---

## 16. Environment Variable Reference

### `jetson/.env`

| Variable | Default | Description |
|---|---|---|
| `LINUX_PC_URL` | `http://192.168.1.20:8080` | Full URL of the Linux PC os-ken REST API. **Must be updated to your Linux PC IP.** |
| `ANOMALY_THRESHOLD` | `0.75` | Minimum Isolation Forest confidence to fire an alert (0.0–1.0). Lower = more sensitive. |
| `WINDOW_SIZE` | `30` | Number of readings in the per-link sliding window (history length) |
| `NODE_TIMEOUT_S` | `20` | Seconds of silence before a link is declared NODE_FAILURE |

Variables used inside `docker-compose.yml` (also sourced from `.env`):

| Variable | Set in | Description |
|---|---|---|
| `MQTT_BROKER` | `docker-compose.yml` | Set to `mosquitto` (the service name, not an IP) — works inside Docker network |
| `MQTT_PORT` | `docker-compose.yml` | `1883` |
| `MODEL_PATH` | `docker-compose.yml` | `/models/isolation_forest.pkl` — path inside the container |
| `DATASET_PATH` | `docker-compose.yml` | `/models/dataset.csv` |

### Linux PC (Dashboard) — Docker environment

Set in `linux-pc/docker-compose.yml` under the `dashboard` service:

| Variable | Value | Description |
|---|---|---|
| `SECRET_KEY` | `zan-change-this-in-production` | Flask session secret key. Change for production. |
| `DB_PATH` | `/data/zan.db` | Path to the SQLite database inside the container. Persisted via Docker volume `zan-db`. |

---

## 17. Docker & Container Reference

### Linux PC — `linux-pc/docker-compose.yml`

```yaml
services:
  controller:                       # zan-controller
    build: ./controller
    network_mode: host              # shares Linux PC network stack — can reach Mininet
    volumes:
      - ./controller/app:/app       # live code reload without rebuild

  dashboard:                        # zan-dashboard
    build: ./dashboard
    network_mode: host              # port 5000 bound directly on Linux PC
    volumes:
      - ./dashboard:/app            # live code reload
      - zan-db:/data                # SQLite database persisted across restarts
```

Both containers use `network_mode: host` so they can communicate with:
- Mininet virtual switches (via `127.0.0.1:6653`)
- The Jetson MQTT broker over the LAN
- Each other via `localhost`

### Linux PC — Controller `Dockerfile`

The controller image is based on `python:3.11-slim`. It installs `os-ken` and runs:
```
os-ken-manager --observe-links zan_controller.py
```

### Linux PC — Dashboard `Dockerfile`

Based on `python:3.11-slim`. Installs Flask, Flask-Login, Flask-SocketIO, paho-mqtt.
Runs: `python app.py`

### Jetson — `jetson/docker-compose.yml`

Three services:

| Service | Image | Port | Purpose |
|---|---|---|---|
| `mosquitto` | `eclipse-mosquitto:2.0.18` | 1883 | MQTT broker |
| `inference-api` | Built from `./inference-api` | 8000 | FastAPI + anomaly detector |
| `telemetry-logger` | Built from `./telemetry-logger` | — | CSV telemetry archiver |

The inference-api app directory is volume-mounted (`./inference-api/app:/app`) so
code changes take effect after a container restart without rebuilding the image.

### Common Docker Commands

```bash
# Rebuild images after code changes that affect requirements/Dockerfile
docker-compose build --no-cache

# Restart without rebuild (picks up volume-mounted code changes)
docker-compose restart <service>

# Recreate with new environment variables (restart alone does NOT reload .env)
docker-compose up -d <service>

# View real-time logs
docker-compose logs -f <service> 2>&1 | grep "keyword"

# Check what environment variable a container actually has
docker exec <container_name> env | grep VAR_NAME
```

---

## 18. Admin Credentials

The dashboard uses session-based authentication backed by a SQLite database.
The default admin account is created automatically on first run.

| Field | Value |
|---|---|
| **Username** | `admin` |
| **Password** | `zan-admin` |
| **Login URL** | `http://<LINUX_PC_IP>:5000/login` |

To change the password, log in → Settings → Change Password.

> ⚠️ Change the default password before deploying on a network accessible by others.
> Also set a strong `SECRET_KEY` in `linux-pc/docker-compose.yml` environment.

---

## 19. API Endpoint Reference

### Controller API — `http://<LINUX_PC_IP>:8080`

#### `GET /zan/network-status`
Returns the current state of the SDN network.

```json
{
  "connected_switches": [1, 2, 3, 4, 5],
  "degraded_links": [[1, 2]],
  "recent_insights": [
    {
      "type": "RF_INTERFERENCE",
      "nodes": ["esp32_01", "esp32_02"],
      "confidence": 1.0,
      "rerouted": true,
      "affected_dpids": [1, 2]
    }
  ],
  "mac_table": {
    "1": ["00:00:00:00:00:01"],
    "2": ["00:00:00:00:00:02"]
  }
}
```

#### `POST /zan/insight`
Trigger an anomaly insight manually (for testing) or receive one from the Jetson.

```bash
curl -X POST http://localhost:8080/zan/insight \
  -H "Content-Type: application/json" \
  -d '{"type":"NODE_FAILURE","nodes":["esp32_01","esp32_02"],"confidence":1.0}'
```

Response:
```json
{"status": "ok", "rerouted": true, "affected_dpids": [1, 2]}
```

#### `POST /zan/clear-degraded`
Clears all degraded links and resets the topology to healthy state.

```bash
curl -X POST http://localhost:8080/zan/clear-degraded
```

### Dashboard Proxy API — `http://<LINUX_PC_IP>:5000` (requires login session)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/sdn-status` | Proxies `/zan/network-status` from controller |
| `POST` | `/api/clear-degraded` | Proxies `/zan/clear-degraded` from controller |
| `GET` | `/api/state` | Current in-memory telemetry state (nodes, links, insights) |
| `GET` | `/api/history/<node_id>→<target>` | Last 60 readings for a specific link |
| `GET` | `/api/logs?limit=100` | Recent telemetry log entries from database |

### Manual End-to-End Test

Use these two commands together to simulate a full alert (Jetson offline):

```bash
# 1. Trigger reroute on controller
curl -X POST http://localhost:8080/zan/insight \
  -H "Content-Type: application/json" \
  -d '{"type":"RF_INTERFERENCE","nodes":["esp32_01","esp32_02"],"confidence":1.0}'

# 2. Publish to MQTT so dashboard shows the alert
mosquitto_pub -h 10.172.211.12 -t "zan/insights" \
  -m '{"type":"RF_INTERFERENCE","nodes":["esp32_01","esp32_02"],"confidence":1.0}'
```

---

## 20. Troubleshooting

### Dashboard shows no telemetry data

1. Verify MQTT broker is reachable: `mosquitto_pub -h <JETSON_IP> -t test -m hello`
2. Check dashboard MQTT settings: Settings page → MQTT Broker should be Jetson IP
3. Check dashboard logs: `docker logs zan-dashboard --tail 30`
4. Verify ESP32 gateway is powered and connected to WiFi

---

### SDN Topology shows all switches offline (grey)

Mininet is not running or the controller is not connected.

```bash
# Check controller is running
docker ps | grep zan-controller

# Start Mininet
sudo python3 ~/internet-reliability-sdn/linux-pc/mininet/zan_topology.py

# Verify connection
curl http://localhost:8080/zan/network-status
```

---

### Alert badges always show "Reroute attempted" (never green)

This means the controller's `recent_insights` log does not have a matching entry with `rerouted: true`.

Check Jetson inference-api logs:
```bash
# On Jetson
docker-compose logs inference-api 2>&1 | grep "POST\|HTTP\|WARNING" | tail -10
```

You should see: `POST http://<LINUX_PC_IP>:8080/zan/insight → HTTP 200`

If instead you see `Connection refused` or `port=8000`:
1. Check `jetson/.env` — `LINUX_PC_URL` must be `http://<LINUX_PC_IP>:8080`
2. Run `docker-compose up -d inference-api` (not restart — restart does not reload .env)
3. Verify with: `docker exec jetson_inference-api_1 env | grep LINUX_PC_URL`

---

### ESP-NOW packets not arriving at gateway

Most common cause: WiFi channel mismatch.

The gateway connects to the router on (e.g.) channel 6, but sensor nodes default to channel 1.

**Fix:** Find your router's WiFi channel (check router admin page).
In all sensor node `.ino` files, add after `WiFi.mode(WIFI_STA)`:
```cpp
#include "esp_wifi.h"
esp_wifi_set_channel(6, WIFI_SECOND_CHAN_NONE);  // replace 6 with your channel
```

---

### MQTT not connecting (gateway side)

- Confirm Mosquitto is running on Jetson: `docker-compose logs mosquitto`
- Verify `mosquitto.conf` allows anonymous connections:
  ```
  listener 1883
  allow_anonymous true
  ```
- Ping the Jetson from the Linux PC: `ping <JETSON_IP>`

---

### Anomaly not triggering when covering node with foil

The Isolation Forest may score a mild RSSI drop below the 0.75 threshold.

**Rule-based floor:** RSSI < −55 dBm automatically fires `RF_INTERFERENCE` regardless.
Ensure the foil is wrapped tightly enough to push RSSI below −55 dBm.

**Check live RSSI** on the dashboard Node Status cards.
If RSSI stays above −55 dBm even with foil, try multiple layers or blocking all sides.

To lower the threshold temporarily:
1. Edit `jetson/.env` → `ANOMALY_THRESHOLD=0.5`
2. Run `docker-compose up -d inference-api` on Jetson

---

### Latency reads 999 ms

No ESP-NOW pong received from the target peer. Check:
- Both boards are powered and within range (~50 m indoors)
- MAC addresses are correct in firmware
- The peer board was successfully flashed

---

### Container not picking up .env changes

`docker-compose restart` does **not** reload environment variables.
Always use:
```bash
docker-compose up -d <service>
```
This recreates the container with the current `.env` values.

---

*ZAN — Zimbabwe Adaptive Network | Built for adaptive, AI-driven SDN network reliability*

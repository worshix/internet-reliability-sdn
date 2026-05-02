# ZAN — Zimbabwe Adaptive Network
## Complete Project Guide & Implementation Roadmap

---

## Table of Contents

1. [What Is This Project? (Plain English)](#1-what-is-this-project-plain-english)
2. [What Is SDN? (Simple Explanation)](#2-what-is-sdn-simple-explanation)
3. [What Is the ZAN Framework?](#3-what-is-the-zan-framework)
4. [Your Hardware & What Each Device Does](#4-your-hardware--what-each-device-does)
5. [How Everything Communicates](#5-how-everything-communicates)
6. [The Network Explained Simply](#6-the-network-explained-simply)
7. [The AI Model — What It Does & Where to Get Data](#7-the-ai-model--what-it-does--where-to-get-data)
8. [Software Stack Summary](#8-software-stack-summary)
9. [Docker Architecture & Deployment](#9-docker-architecture--deployment)
10. [Development Roadmap — Step by Step](#10-development-roadmap--step-by-step)
11. [How You Prove Your Objectives](#11-how-you-prove-your-objectives)
12. [Common Pitfalls to Avoid](#12-common-pitfalls-to-avoid)

---

## 1. What Is This Project? (Plain English)

Zimbabwe's internet infrastructure has a problem. The companies that provide internet (ISPs) use
old networking equipment and software that was designed decades ago. When something goes
wrong — a power cut, a cable fault, a congested link — that old equipment takes **seconds to
minutes** to figure out an alternative route. During that time, services like video calls, online
banking, and telemedicine are either degraded or completely down.

The traditional approach to fixing this is to buy very expensive proprietary hardware (like Cisco
MPLS equipment), which ISPs in Zimbabwe cannot afford due to foreign currency shortages.

**Your project proposes a different solution:** instead of replacing expensive hardware, you overlay
an intelligent software layer on top of whatever infrastructure already exists. This software layer:

- **Watches** the network continuously using small cheap devices (ESP32s)
- **Thinks** about what it sees using an AI model running on a Jetson TX2
- **Acts** by reprogramming how traffic flows using Software-Defined Networking (SDN)
- **Prioritizes** important traffic (VoIP, telemedicine) over less important traffic (downloads)

The result is a network that heals itself faster, routes smarter, and costs far less to deploy than
traditional solutions.

---

## 2. What Is SDN? (Simple Explanation)

In a traditional network, every router makes its own decisions about where to send packets. It's
like a city where every intersection has its own traffic light controller that doesn't talk to any
other intersection. Each light just follows its own rules. When there's an accident somewhere,
each intersection only finds out slowly, one by one.

**SDN (Software-Defined Networking)** changes this. It separates the "thinking" from the
"doing":

- The **data plane** = the roads and intersections (just forwards packets, doesn't think)
- The **control plane** = a central traffic management centre that watches everything and
  tells every intersection exactly what to do in real time

In SDN, one central controller (running on your Linux PC) has a complete map of the whole
network and can instantly reprogram every switch to change how traffic flows. When a link goes
down, the controller knows immediately and pushes new routing rules to every switch within
milliseconds.

**OpenFlow** is the language the controller uses to talk to the switches. Think of it as the
protocol that lets the central brain send instructions to each intersection.

**Mininet** is a tool that simulates a full network of OpenFlow switches on a single Linux
machine. It's used here because you don't have physical OpenFlow switches — Mininet creates
virtual ones that behave identically for demonstration purposes.

**os-ken** is the SDN controller framework. It is the actively-maintained OpenStack fork of Ryu,
running on modern Python (3.9+). The API is essentially identical to Ryu, so all standard Ryu
tutorials and example apps apply, but without the dependency-hell of Ryu's pinned Python 3.6–3.8.

---

## 3. What Is the ZAN Framework?

ZAN (Zimbabwe Adaptive Network) is the name for the complete system you are building. It has
four layers that work together:

### Layer 1 — Data Plane (Infrastructure Layer)
The actual network paths that carry traffic. In your prototype, this is Mininet running virtual
OpenFlow switches on your Linux PC. In a real deployment, these would be physical switches at
ISP exchange points.

### Layer 2 — Control Plane (SDN Controller Layer)
The os-ken controller running in a Docker container on your Linux PC. It holds the network map,
computes best paths, and pushes flow rules to the switches. It also implements **AQoSRM**
(explained below).

### Layer 3 — Intelligence Layer (Edge Devices)
Your 5 ESP32 boards. These are the "sensors" of the network. They continuously measure
real-world network conditions — latency between nodes, signal strength (RSSI), packet loss —
and stream that data to the Jetson. They represent edge nodes in a real ISP network (think: a
small device installed at a base station or exchange point that monitors what's happening there).

### Layer 4 — Edge-Inference Integration Layer
Running on your Jetson TX2, packaged as Docker containers. This is the bridge between the
sensors and the controller. It receives raw telemetry from the ESP32s, runs it through an AI model
to detect anomalies and predict failures, and then sends actionable insights to the os-ken
controller via REST API. The controller then acts on those insights.

### What is AQoSRM?
**Adaptive QoS Routing Mechanism** is the name for your intelligent traffic prioritization
algorithm. It runs inside the os-ken controller and classifies incoming traffic into priority tiers:

| Priority | Traffic Type | Example |
|---|---|---|
| Highest | Real-time voice | VoIP calls |
| High | Real-time video | Telemedicine, video conferencing |
| Medium | Interactive | Web browsing, online banking |
| Low | Bulk transfer | File downloads, backups |

When the network is congested or recovering from a fault, AQoSRM ensures high-priority
traffic gets through first. Low-priority traffic is delayed, not dropped entirely.

**Critical design point — true adaptiveness:** AQoSRM is not just static port-based DiffServ.
The AI's anomaly confidence/severity score *dynamically modifies* the queue weights and rate
limits. Example: when the AI reports `congestion confidence 0.9`, AQoSRM tightens the
bulk-traffic queue's rate limit further than at confidence 0.5. This tight coupling between AI
output and QoS behaviour is what makes the mechanism genuinely adaptive — and is your
defensible thesis contribution.

---

## 4. Your Hardware & What Each Device Does

### Linux PC
**Role:** SDN Controller host + Virtual Network host
**What runs on it:**
- Mininet (creates virtual switches and links) — **runs on bare metal, not in Docker**
- os-ken SDN controller (the brain of the network) — **runs in a Docker container**
- iPerf3 (generates test traffic) — runs inside Mininet hosts

**Why it's here:** You don't have physical OpenFlow switches. Mininet solves this by creating a
full software-simulated network that os-ken controls exactly as it would control real hardware.
Mininet lets you create 10, 20, 50 virtual switches and links on one machine.

**Why Mininet on bare metal, controller in Docker:** Mininet uses Linux network namespaces,
needs `--privileged` mode, requires root, and depends on kernel modules (Open vSwitch). Running
it in Docker is possible but introduces sharp networking edges that consume days of debugging
time. Running it directly on the Linux PC host avoids all of that. The os-ken controller is a pure
Python TCP service — it containerizes cleanly and connects to host-mode Mininet via
`--network host`.

---

### Jetson TX2
**Role:** AI Inference Engine + Edge-Inference Integration Layer + MQTT Broker
**What runs on it (all containerized):**
- Mosquitto (MQTT message broker — receives all ESP32 telemetry)
- FastAPI server (REST API that os-ken calls to get AI insights)
- Python telemetry processor (cleans and formats incoming data)
- AI model (PyTorch or Scikit-learn — detects anomalies, predicts failures)

**Why the Jetson specifically:** The Jetson TX2 has a GPU that can run neural network inference
efficiently. Running the AI model here — close to the data source — rather than in the cloud is
the whole point of "edge AI." It keeps latency low and means the system still works if internet
connectivity is disrupted.

**Container base image note:** Use `nvcr.io/nvidia/l4t-pytorch` (NVIDIA's official L4T-compatible
PyTorch image) as the base for the inference container. This avoids fighting JetPack version
mismatches. The TX2 is on JetPack 4.x — confirm your installed JetPack version before
selecting the exact image tag.

---

### ESP32 #1 — Gateway Node
**Role:** Edge aggregator and WiFi bridge
**What it does:**
- Communicates with ESP32 #2–5 using **ESP-NOW** (a fast peer-to-peer protocol that doesn't
  need a WiFi router — ESP32s talk directly to each other)
- Aggregates telemetry from all other ESP32s
- Connects to the WiFi network and publishes aggregated data to the Jetson's MQTT broker

**Why a dedicated gateway:** ESP-NOW is faster and more reliable for ESP32-to-ESP32
communication than having each one connect to WiFi individually. In a real network, this mirrors
how edge field devices often relay data through a local aggregation point.

---

### ESP32 #2, #3, #4, #5 — Sensor/Telemetry Nodes
**Role:** Network condition monitors
**What they do:**
- Continuously ping each other and the gateway to measure **round-trip latency**
- Report **RSSI** (received signal strength — a proxy for link quality)
- Count **packet loss** (how many pings don't get a reply)
- Report their own **uptime/reachability** status
- Send all this to ESP32 #1 via ESP-NOW every 2–5 seconds

**What they represent in the real world:** Each ESP32 represents a monitoring agent installed
at a network node in an ISP's infrastructure — a base station, a data centre rack, a fibre
exchange point. In your prototype, their real measurements of WiFi link quality stand in for what
would be real fibre/copper link telemetry.

---

### Physical-to-Virtual Topology Mapping (Critical)

A common examiner question: "Why does an ESP32 WiFi degradation cause os-ken to reroute a
Mininet flow that has nothing to do with it?"

The answer must be designed in deliberately, not improvised. Build an explicit **mapping table**
where the ESP32 physical topology is a *scale model* of the Mininet virtual topology:

| Physical (ESP32) | Virtual (Mininet) | Represents |
|---|---|---|
| ESP32 #2 ↔ #3 link | s2 ↔ s3 link | Harare ↔ Bulawayo backbone |
| ESP32 #3 ↔ #4 link | s3 ↔ s4 link | Bulawayo ↔ Mutare backbone |
| ESP32 #2 ↔ #4 link | s2 ↔ s4 link | Harare ↔ Mutare redundant path |
| ESP32 #4 ↔ #5 link | s4 ↔ s5 link | Mutare ↔ Masvingo spur |

When the AI flags `link 02↔03 degrading`, the controller knows it must reroute the Mininet
flow on `s2↔s3`. Document this mapping in your thesis methodology section.

---

### Windows PCs (Optional — Demo Only)
**Role:** Optional traffic clients for demonstration purposes
**What they do (if used):**
- Run iPerf3 as clients generating bulk TCP traffic
- Run custom UDP scripts simulating VoIP traffic
- Connect to Mininet's virtual network through a bridge interface

**Recommendation:** Do NOT use external Windows PCs for thesis measurements. Use
**Mininet hosts internally** — they can run iPerf3 and custom UDP traffic generators directly,
which is sufficient to demonstrate AQoSRM. Skipping the bridge interface removes the single
trickiest piece of networking in the project. Reserve external PCs for the final demo video only,
if at all.

---

### Android Phones (Optional)
**Role:** Real-time application clients for demo
**What they do:** Run actual VoIP or video apps to demonstrate user-perceptible QoS difference.
Not required for thesis measurements; useful for the defence demo.

---

## 5. How Everything Communicates

```
ESP32 #2 ──┐
ESP32 #3 ──┤  ESP-NOW   ┌─────────────┐   MQTT (WiFi)   ┌──────────────────────┐
ESP32 #4 ──┼───────────►│  ESP32 #1   │────────────────►│   Jetson TX2         │
ESP32 #5 ──┘            │  (Gateway)  │                  │                      │
                        └─────────────┘                  │ Docker:              │
                                                         │  - mosquitto         │
                                                         │  - inference-api     │
                                                         │  - telemetry-logger  │
                                                         └──────────┬───────────┘
                                                                    │
                                                          REST API (HTTP, LAN)
                                                                    │
                                                         ┌──────────▼──────────┐
                                                         │    Linux PC         │
                                                         │                     │
                                                         │ Bare metal:         │
                                                         │  - Mininet          │
                                                         │  - Open vSwitch     │
                                                         │                     │
                                                         │ Docker (host net):  │
                                                         │  - os-ken           │
                                                         └──────────┬──────────┘
                                                                    │
                                                              OpenFlow 1.3
                                                                    │
                                                    ┌───────────────▼──────────────┐
                                                    │   Virtual Switches           │
                                                    │   (Mininet topology mirrors  │
                                                    │    ESP32 physical layout)    │
                                                    └──────────────────────────────┘
```

### Communication Protocols Explained

| Link | Protocol | Why |
|---|---|---|
| ESP32 #2–5 → ESP32 #1 | ESP-NOW | Fast, no router needed, works peer-to-peer |
| ESP32 #1 → Jetson | MQTT over WiFi | Lightweight pub/sub, ideal for sensor data |
| Jetson → os-ken (Linux PC) | HTTP REST API | FastAPI server-side; requests on the controller side |
| os-ken → Virtual Switches | OpenFlow 1.3 (TCP port 6653) | The SDN standard protocol |
| Mininet hosts → Network | iPerf3 / UDP sockets | Internal Mininet traffic generation |

---

## 6. The Network Explained Simply

Imagine you are running a small telephone exchange company in Zimbabwe. You have cables
connecting several towns. At each town you have placed a tiny monitoring device (an ESP32).
Every few seconds, each device sends a signal to the others and measures how long it takes to
get a reply — this tells you if a link is slow or broken.

All those measurements flow back to a smart computer in your office (the Jetson). The smart
computer has been trained to recognise patterns — it knows what a healthy network looks like,
and it knows the early warning signs of a link about to fail (rising latency, increasing packet loss,
dropping signal strength).

When it spots something suspicious, it immediately tells your network controller (os-ken on the
Linux PC): "Link between Town A and Town B is degrading, I predict it will fail in 30 seconds."

The controller doesn't wait for the link to actually fail. It immediately recalculates the best route
avoiding that link and reprograms all your switches to use the new path. By the time the link
actually fails, all traffic has already been rerouted. A voice call happening across that link never
drops — it was seamlessly moved before the problem hit.

Meanwhile, the controller knows that the rerouted path has less capacity than the original. So it
tells the switches: "For now, voice calls get priority. Video gets second priority. File downloads
can wait." This is AQoSRM in action — and crucially, the more confident the AI is about the
fault severity, the more aggressively AQoSRM throttles low-priority traffic.

That entire detect → predict → reroute → prioritize loop should complete in well under one
second end-to-end. A traditional reactive Layer-2 learning switch would take many seconds to
recover from the same fault, with no pre-emptive action at all.

---

## 7. The AI Model — What It Does & Where to Get Data

### What the Model Does

The AI model running on the Jetson is an **anomaly detection model**. It watches a continuous
stream of telemetry values from the ESP32s:

- Latency (ms) between each pair of nodes
- RSSI (dBm) at each node
- Packet loss rate (%)
- Timestamp

It learns what "normal" looks like. When values deviate significantly from normal patterns, it
raises an alert and classifies the type of anomaly:

| Anomaly Type | Signature | ZAN Response |
|---|---|---|
| Link degradation | Latency rising gradually | Pre-emptive reroute |
| Sudden link failure | Latency spike + 100% packet loss | Emergency reroute |
| Congestion | Latency rising, RSSI stable | AQoSRM prioritization (severity-weighted) |
| Node failure | No response from node | Remove from topology |

### Recommended Model Architecture

For your prototype, use one of these — in order of recommendation:

**Option 1 — Isolation Forest (Best starting point — do this first)**
- Unsupervised, so you don't need labelled "fault" data to train it
- Scikit-learn, runs fast on Jetson CPU
- Trains on 10–15 minutes of normal network operation data you collect yourself
- Very explainable — easy to justify in your thesis
- **Get this working end-to-end before considering anything else.**

**Option 2 — LSTM Autoencoder (Better, more publishable)**
- Learns the time-series pattern of normal telemetry
- Reconstruction error spikes when anomaly occurs
- PyTorch, can use Jetson GPU
- Requires more training data but performs better on gradual degradation

**Option 3 — Random Forest Classifier (If you can get labelled data)**
- Classifies fault type directly
- Fastest inference time
- Needs labelled dataset (see below)

### Where to Get Training Data

You have three practical options — use all three for the best result:

#### Option A — Generate Your Own (Recommended, do this first)
Run your ESP32 network for 30–60 minutes in a normal healthy state and log all telemetry.
Then deliberately introduce faults using **a controlled, repeatable protocol** (see below).

#### Option B — Public Network Anomaly Datasets

| Dataset | What It Contains | Where to Get It |
|---|---|---|
| **CAIDA** | Real internet traffic traces with anomalies | https://www.caida.org/catalog/datasets/ |
| **KDD Cup 1999** | Network intrusion/anomaly data, labelled | http://kdd.ics.uci.edu/databases/kddcup99/ |
| **UNSW-NB15** | Modern network traffic with 9 attack/anomaly types | https://research.unsw.edu.au/projects/unsw-nb15-dataset |
| **CIC-IDS-2017** | Intrusion detection with realistic background traffic | https://www.unb.ca/cic/datasets/ids-2017.html |
| **ToN_IoT** | IoT network telemetry with anomaly labels | https://research.unsw.edu.au/projects/toniot-datasets |

> **Best choice from this list:** ToN_IoT — it's IoT-specific (closest to your ESP32 setup)
> and UNSW-NB15 for a well-cited benchmark dataset to validate your model.

> **Cross-dataset validation:** Train on one source, test on a different held-out source. This
> directly addresses the "circular validation" weakness and strengthens your methodology.

#### Option C — Synthetic Data Generation
Use Python to generate synthetic telemetry streams with injected fault patterns. Useful for
training the LSTM before real data is available, and for augmenting your real dataset.

```python
# Simple example of synthetic telemetry generation
import numpy as np, pandas as pd

def generate_telemetry(n_samples=5000, inject_faults=True):
    t = np.arange(n_samples)
    latency = 20 + 5*np.sin(t/50) + np.random.normal(0, 2, n_samples)  # normal ~20ms
    rssi = -65 + np.random.normal(0, 3, n_samples)                      # normal ~-65dBm
    packet_loss = np.clip(np.random.normal(0.02, 0.01, n_samples), 0, 1) # normal ~2%
    labels = np.zeros(n_samples)

    if inject_faults:
        # Link degradation event at sample 2000
        latency[2000:2200] = np.linspace(20, 200, 200) + np.random.normal(0,5,200)
        packet_loss[2000:2200] = np.linspace(0.02, 0.8, 200)
        labels[2000:2200] = 1

        # Sudden failure at sample 3500
        latency[3500:3600] = 999
        packet_loss[3500:3600] = 1.0
        labels[3500:3600] = 1

    return pd.DataFrame({'latency': latency, 'rssi': rssi,
                         'packet_loss': packet_loss, 'label': labels})
```

### Controlled Fault-Injection Protocol

Reviewers will ask "is this reproducible?" Don't improvise faults — script them:

- **Distance protocol:** Mark physical positions on the floor with tape (P1, P2, P3 at known
  distances). Move ESP32 from P1 → P3, hold for N seconds, move back. Same procedure each trial.
- **Interference protocol:** Use a known interferer (microwave oven on 2.4 GHz, or a separate
  ESP32 spamming the channel) at a fixed distance for a fixed duration.
- **Power-cycle protocol:** Scripted via USB relay if available, otherwise stopwatch with
  consistent timing.
- **Trial count:** Run **at least 5 trials per fault type per scenario** and report mean ±
  standard deviation, not single-shot numbers.

### Data Pipeline (ESP32 → Jetson → Model)

```
ESP32 sends JSON every 2s:
{
  "node_id": "esp32_02",
  "target_node": "esp32_03",
  "latency_ms": 24.3,
  "rssi_dbm": -67,
  "packet_loss_pct": 0.02,
  "timestamp": 1711900000
}
         │
         ▼ MQTT topic: zan/telemetry/esp32_02
Jetson Mosquitto container receives,
inference-api container subscribes, buffers last 30 readings (sliding window)
         │
         ▼ Feature vector: [mean_latency, std_latency, mean_rssi, packet_loss, trend]
AI model scores the window → anomaly score 0.0–1.0
         │
         ▼ If score > 0.75:
POST http://linux-pc:8080/zan/insight
{ "type": "LINK_DEGRADATION", "nodes": ["esp32_02","esp32_03"], "confidence": 0.91 }
         │
         ▼
os-ken receives insight → recalculates path → pushes OpenFlow rules
         AND adjusts AQoSRM queue weights proportional to confidence
```

---

## 8. Software Stack Summary

### Linux PC (Ubuntu 22.04 LTS recommended)
| Software | Version | Purpose | Where it runs |
|---|---|---|---|
| Mininet | 2.3.1b4+ | Virtual network | **Bare metal**, root |
| Open vSwitch | 2.17+ | Mininet backend | **Bare metal**, root |
| os-ken | latest | SDN controller | **Docker container**, `--network host` |
| Python | 3.10 / 3.11 | Controller apps | Inside container |
| iPerf3 | 3.x | Traffic generation | Inside Mininet hosts |
| Docker Engine | 24+ | Container runtime | Bare metal |
| docker-compose | v2 | Orchestration | Bare metal |

### Jetson TX2 (JetPack 4.x, Ubuntu 18.04)
| Software | Version | Purpose | Where it runs |
|---|---|---|---|
| Docker | 20+ | Container runtime | Bare metal, `--runtime nvidia` available |
| Mosquitto | 2.x | MQTT broker | **Docker:** `eclipse-mosquitto:2.0.18` |
| Paho MQTT | 1.6 | Python MQTT client | Inside inference container |
| FastAPI + uvicorn | 0.100+ | REST API server | Inside inference container |
| PyTorch | L4T build | AI model | Base image: `nvcr.io/nvidia/l4t-pytorch` |
| Scikit-learn | 1.3 | Isolation Forest | Inside inference container |
| NumPy/Pandas | latest | Data processing | Inside inference container |

### ESP32 (Arduino IDE or PlatformIO)
| Library | Purpose |
|---|---|
| `esp_now.h` | ESP-NOW peer-to-peer comms |
| `WiFi.h` | WiFi connection (gateway only) |
| `PubSubClient` | MQTT client (gateway only) |
| `ArduinoJson` | JSON serialization |

---

## 9. Docker Architecture & Deployment

### Why Docker (and where the line is drawn)

Docker gives you reproducibility, dependency isolation, and one-command bring-up of the entire
software stack — critical for a thesis that needs to be demonstrable months after you build it.
But Docker is the right tool for *application services*, not for kernel-level networking
infrastructure. Hence:

- **Containerize:** os-ken controller, Mosquitto, FastAPI inference server, telemetry logger,
  optional metrics stack (Prometheus/Grafana).
- **Do NOT containerize:** Mininet. It needs `--privileged` mode, kernel modules, root, and
  Linux network namespaces. Running it on bare metal on the Linux PC removes a class of
  "weird networking issues" that would otherwise cost days.

### File Layout

```
zan/
├── linux-pc/
│   ├── docker-compose.yml          # controller stack
│   ├── controller/
│   │   ├── Dockerfile
│   │   ├── requirements.txt        # os-ken, requests, etc.
│   │   └── app/
│   │       ├── zan_controller.py   # main os-ken app
│   │       ├── aqosrm.py           # adaptive QoS logic
│   │       └── topology_map.py     # ESP32 ↔ Mininet mapping
│   └── mininet/
│       └── zan_topology.py         # Mininet topology script (bare metal)
│
├── jetson/
│   ├── docker-compose.yml          # broker + inference stack
│   ├── mosquitto/
│   │   └── mosquitto.conf
│   ├── inference-api/
│   │   ├── Dockerfile              # FROM nvcr.io/nvidia/l4t-pytorch:...
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py             # FastAPI entrypoint
│   │       ├── model.py            # anomaly model load + inference
│   │       └── mqtt_subscriber.py
│   └── telemetry-logger/
│       ├── Dockerfile
│       └── logger.py               # MQTT → CSV
│
└── esp32/
    ├── gateway/                    # ESP32 #1 firmware
    └── sensor/                     # ESP32 #2–5 firmware
```

### Docker Best Practices for This Project

- **Use docker-compose, not raw `docker run`.** One compose file per machine. Reproducibility
  becomes "two YAML files" in your thesis appendix.
- **Pin versions.** `python:3.11-slim` not `python:latest`. `eclipse-mosquitto:2.0.18` not
  `eclipse-mosquitto:latest`. Docker Hub moves on; your thesis must remain reproducible.
- **`--network host` for the controller container** on the Linux PC. The os-ken container needs
  to reach Mininet's switches at `127.0.0.1:6653`. Host networking makes this trivial. Bridge
  networking forces you into `host.docker.internal` workarounds that behave differently on Linux.
- **Volume-mount code during development.** `./controller/app:/app` lets you edit Python and
  restart the container without rebuilding. Bake code into the image only for the final thesis build.
- **Environment variables for IPs, not hardcoding.** The Jetson's IP, the Linux PC's IP, MQTT
  topics — all in `.env` files referenced by docker-compose.
- **Jetson CUDA passthrough:** any container that needs GPU must run with `--runtime nvidia`
  and use an L4T base image matching your JetPack version. Test `nvidia-smi` (or
  `tegrastats`) inside the container to confirm GPU is visible.

### Sample docker-compose snippet (Linux PC)

```yaml
services:
  controller:
    build: ./controller
    network_mode: host
    volumes:
      - ./controller/app:/app
    environment:
      - JETSON_API_URL=http://192.168.1.50:8000
      - OPENFLOW_PORT=6653
    restart: unless-stopped
```

### Sample docker-compose snippet (Jetson TX2)

```yaml
services:
  mosquitto:
    image: eclipse-mosquitto:2.0.18
    ports:
      - "1883:1883"
    volumes:
      - ./mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf

  inference-api:
    build: ./inference-api
    runtime: nvidia
    ports:
      - "8000:8000"
    depends_on:
      - mosquitto
    environment:
      - MQTT_BROKER=mosquitto
      - LINUX_PC_URL=http://192.168.1.20:8080
    volumes:
      - ./inference-api/app:/app
      - ./inference-api/models:/models
```

---

## 10. Development Roadmap — Step by Step

Work through these phases in order. Do not skip phases. Each phase validates the foundation
the next phase depends on.

---

### PHASE 0 — Environment & Docker Setup
**Goal:** Get a clean, reproducible container environment on both machines.
**Duration:** ~1 week
**Why first:** Spending a day on Docker now saves a week of dependency hell later.

**Steps:**
1. Install Docker Engine + docker-compose v2 on Linux PC
2. Install Docker on Jetson TX2 with `nvidia-container-toolkit` for GPU passthrough
3. Verify GPU visibility: `docker run --runtime nvidia ... nvidia-smi` inside an L4T image
4. Write skeleton Dockerfiles for: controller, inference-api, telemetry-logger
5. Write `docker-compose.yml` for both machines (with placeholder services)
6. Verify `docker compose up` succeeds with hello-world containers on both
7. Confirm the Linux PC's controller container can reach the Jetson's port 8000 over the LAN

**Deliverable:** Both machines bringing up their compose stacks cleanly with `docker compose up -d`.

---

### PHASE 1 — ESP32 Telemetry Pipeline
**Goal:** Get real data flowing from ESP32s into the Jetson's containerized stack.
**Duration:** ~1 week
**Why second:** Everything downstream depends on having live telemetry.

**Steps:**
1. Flash ESP32 #2–5 with sensor firmware:
   - Continuously ping each other via ESP-NOW (every 2 seconds)
   - Measure round-trip latency and packet loss
   - Measure RSSI to each peer
   - Send results to ESP32 #1 via ESP-NOW
2. Flash ESP32 #1 (gateway) with aggregator firmware:
   - Receive from all peers via ESP-NOW
   - Connect to your WiFi network
   - Connect to Mosquitto **container** on the Jetson
   - Publish JSON telemetry to `zan/telemetry/<node_id>`
3. Bring up Mosquitto container on Jetson via docker-compose
4. Bring up telemetry-logger container that subscribes and writes CSV to a mounted volume

**Deliverable:** A CSV file of real network telemetry from your ESP32s, written from inside a
container, updating every 2 seconds.

---

### PHASE 2 — Mininet + os-ken Control Plane
**Goal:** Get a working virtual SDN network with a containerized os-ken controlling it.
**Duration:** ~1 week

**Steps:**
1. Install Mininet and Open vSwitch on Linux PC (bare metal)
2. Build the controller Docker image with os-ken + your app code
3. Write a Mininet topology script that **mirrors your ESP32 physical layout**:
   - 5 switches representing the 5 ESP32 nodes
   - Link costs and structure matching your physical mapping table (Section 4)
   - Host nodes on each switch representing clients
4. Write a basic os-ken controller app (essentially identical to a Ryu app):
   - Discovers topology using LLDP
   - Installs shortest-path flow rules using Dijkstra
   - Implements basic OpenFlow 1.3 packet-in handling
5. Start the controller container with `--network host`
6. Start Mininet pointing at controller `127.0.0.1:6653`
7. Test basic connectivity: `h1 ping h6` should work
8. Add QoS queues to Mininet links (bandwidth limits per queue)
9. Implement AQoSRM in the controller:
   - Classify traffic by IP protocol / port number (UDP port 5060 = VoIP, TCP bulk = low priority)
   - Assign flows to appropriate queues
   - **Expose hooks for dynamic queue weight adjustment** (used in Phase 4)

**Deliverable:** A Mininet network where you can run iPerf and observe that VoIP-simulated UDP
traffic gets lower latency than bulk TCP traffic under congestion.

---

### PHASE 3 — AI Model Development
**Goal:** Train an anomaly detection model that can classify network faults.
**Duration:** ~1.5 weeks

**Steps:**
1. Run your Phase 1 setup for 1–2 hours to collect baseline "normal" telemetry
2. Run controlled fault-injection trials (per protocol in Section 7) and label fault periods
3. Download ToN_IoT or UNSW-NB15 dataset to supplement your data
4. Feature engineer your telemetry:
   - Rolling mean latency (window=10)
   - Rolling std latency (window=10)
   - Latency trend (slope over last 10 samples)
   - Packet loss rate
   - RSSI drop rate
5. Train an Isolation Forest model on normal data only
6. Optionally train an LSTM Autoencoder on the full time series
7. Evaluate using **cross-dataset validation**: train on one, test on a held-out other
8. Report precision/recall with mean ± std over multiple random seeds
9. Export model to ONNX or pickle, copy into the inference-api image's `/models` volume
10. Write a real-time inference module inside the inference-api container that:
    - Subscribes to MQTT topics
    - Maintains a sliding window of the last 30 telemetry readings
    - Runs inference every time a new reading arrives
    - Outputs anomaly type and confidence score

**Deliverable:** Inference-api container running on the Jetson, correctly flagging introduced
faults in real time, with reproducibility metrics (mean ± std across seeds).

---

### PHASE 4 — Edge-Inference Integration Layer
**Goal:** Connect the Jetson AI engine to the os-ken controller.
**Duration:** ~1 week

**Steps:**
1. Add FastAPI endpoints to the inference-api container:
   - `GET /zan/status` — returns current network health
   - Outbound POST to the controller's `/zan/insight` endpoint when anomalies detected
2. Use **push** model: Jetson POSTs to controller's REST endpoint when anomaly detected
3. Add a REST endpoint inside the os-ken controller container (`POST /zan/insight`) that:
   - Receives an insight: `{"type": "LINK_DEGRADATION", "nodes": ["02","03"], "confidence": 0.91}`
   - Looks up the physical→virtual mapping table
   - Recalculates shortest path excluding degraded link
   - Pushes new flow rules via OpenFlow
   - **Adjusts AQoSRM queue weights proportional to confidence**
4. Test end-to-end:
   - Move an ESP32 to cause latency spike (per controlled protocol)
   - Watch Jetson container log the anomaly
   - Watch controller container reroute Mininet traffic AND tighten low-priority queue
   - Measure time from anomaly start to reroute completion (your MTTR)

**Deliverable:** End-to-end automated rerouting AND severity-weighted QoS adjustment,
triggered by real ESP32 telemetry, with all software running in containers.

---

### PHASE 5 — AQoSRM Full Integration & Measurement
**Goal:** Demonstrate measurable QoS improvement and collect results for your thesis.
**Duration:** ~1 week

**Steps:**
1. Set up traffic generators **inside Mininet hosts**:
   - Mininet host 1: iPerf3 UDP, 100kbps, 20ms packet interval (VoIP simulation)
   - Mininet host 2: iPerf3 TCP, max bandwidth (bulk download simulation)
   - Both running simultaneously through Mininet
2. Measure baseline (no QoS, no AI):
   - VoIP latency, jitter, packet loss
   - Bulk transfer throughput
3. Enable AQoSRM (static port-based only, no AI input):
   - Measure same metrics
4. Enable full ZAN (AQoSRM + AI severity weighting):
   - Measure same metrics — should be best of all
5. Introduce link fault (power off an ESP32 per protocol):
   - Measure MTTR with full ZAN vs. baseline (reactive L2 learning switch in Mininet)
   - **Note:** baseline is the L2 learning switch, NOT a textbook OSPF "30–60s" claim — that
     number is dated and easily challenged
6. **Run a negative-result experiment:** test ZAN on a fault type the model wasn't trained on.
   Report honestly. Examiners trust honest evaluation.
7. Run **5+ trials of each scenario**, report mean ± std
8. Record all measurements in a table for your thesis

**Deliverable:** Data tables showing latency reduction, MTTR improvement, QoS performance,
AND a documented limitation (the negative-result experiment) — the evidence for your H1 and
H2 hypotheses.

---

## 11. How You Prove Your Objectives

### Objective 1 — AQoSRM
**Experiment:** Run VoIP + bulk traffic simultaneously through Mininet with congestion.
**Measure:** Latency and packet loss for VoIP stream WITHOUT AQoSRM, WITH static AQoSRM,
and WITH AI-coupled adaptive AQoSRM.
**Expected result:** Substantial reduction in VoIP latency under congestion (per H1 in your paper),
with the AI-coupled version outperforming static AQoSRM.

### Objective 2 — ZAN Hybrid Framework
**Experiment:** Introduce a controlled link failure (power off ESP32 node per protocol).
**Measure:** Time from failure detection to successful reroute (MTTR).
**Baseline:** Mininet with reactive L2 learning switch (no AI, no pre-emptive routing).
**Expected result:** MTTR for ZAN substantially lower than reactive baseline. Report actual
numbers with mean ± std over ≥5 trials. Avoid the "vs OSPF 30–60s" framing — modern OSPF
converges in 1–3s with sub-second hellos, and you cannot run real OSPF in this setup anyway.

### Objective 3 — Edge-Inference Integration Layer
**Experiment:** Inject gradual link degradation per controlled distance protocol.
**Measure:** Time from degradation start to anomaly alert from Jetson container.
**Also measure:** False positive rate during normal operation periods.
**Expected result:** Anomaly detected and reroute triggered before complete link failure, with
false positive rate documented honestly.

---

## 12. Common Pitfalls to Avoid

**ESP-NOW range:** ESP-NOW range indoors is typically 10–50m. Keep ESP32s within range
during testing and note the range in your methodology.

**Don't containerize Mininet.** Mininet on bare metal, controller in Docker. People who try
otherwise lose days to namespace and `--privileged` debugging.

**`--network host` for the controller container.** Bridge networking on Linux requires
`--add-host=host.docker.internal:host-gateway` workarounds that behave inconsistently. Save
yourself the pain.

**Use os-ken, not Ryu.** Ryu is unmaintained and pinned to Python 3.6–3.8 (both EOL). os-ken
has the same API and supports modern Python. All Ryu tutorials still apply.

**JetPack version pinning on Jetson.** TX2 is on JetPack 4.x. Your `nvcr.io/nvidia/l4t-pytorch`
tag must match. Check `cat /etc/nv_tegra_release` on the Jetson before picking a tag.

**MQTT broker hostname.** ESP32 firmware should target the Jetson's LAN IP, not `localhost`.
Inside the Jetson's docker network, services reach Mosquitto by service name (`mosquitto`), but
ESP32s on the WiFi need the host IP and port 1883 forwarded (which the compose file does).

**AI model overfitting:** If you train only on your own ESP32 data, your model may be too
specific to your lab environment. Use the public datasets to add diversity, and **validate
cross-dataset** to prove generalization.

**Pin all Docker image tags.** `latest` will betray you six months from now during your defence.

**Thesis positioning:** Your paper explicitly states ZAN is different from purely
simulation-based work. When writing your methodology, clearly state: "Physical telemetry is
collected from real ESP32 hardware nodes; the SDN control plane is demonstrated using Mininet
as a software emulation layer due to hardware constraints, which is a widely accepted approach
in SDN research prototyping. The physical ESP32 topology is mapped 1:1 to the Mininet virtual
topology to ensure measurements on the emulated data plane are driven by real-world link
conditions."

**Measurement timing:** Use Python's `time.perf_counter()` (not `time.time()`) for
sub-millisecond MTTR measurements. Log timestamps at both the anomaly detection event and
the flow rule installation confirmation. Note that timestamps cross machines (Jetson → Linux PC),
so consider running NTP on both for clock alignment, and report end-to-end MTTR as
`controller_install_time − jetson_detect_time`.

**Avoid the "30–60s OSPF" baseline claim.** It's dated and any examiner with networking
background will challenge it. Use the Mininet L2 learning switch as your honest baseline.

---

*This guide covers the full scope of the ZAN prototype. Implement one phase at a time,
validate each phase before proceeding, and keep logs of all measurements from Phase 5 onwards.*

---
**Project:** ZAN — Zimbabwe Adaptive Network
**Student:** Tanaka Keith Mashoko (H220325F)
**Institution:** Harare Institute of Technology
**Module:** HIT 400

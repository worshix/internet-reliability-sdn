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
9. [Development Roadmap — Step by Step](#9-development-roadmap--step-by-step)
10. [How You Prove Your Objectives](#10-how-you-prove-your-objectives)
11. [Common Pitfalls to Avoid](#11-common-pitfalls-to-avoid)

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

**Ryu** is the SDN controller framework. It's a Python library that handles all the OpenFlow
communication. You write your routing logic in Python using Ryu's APIs.

---

## 3. What Is the ZAN Framework?

ZAN (Zimbabwe Adaptive Network) is the name for the complete system you are building. It has
four layers that work together:

### Layer 1 — Data Plane (Infrastructure Layer)
The actual network paths that carry traffic. In your prototype, this is Mininet running virtual
OpenFlow switches on your Linux PC. In a real deployment, these would be physical switches at
ISP exchange points.

### Layer 2 — Control Plane (SDN Controller Layer)
The Ryu controller running on your Linux PC. It holds the network map, computes best paths,
and pushes flow rules to the switches. It also implements **AQoSRM** (explained below).

### Layer 3 — Intelligence Layer (Edge Devices)
Your 5 ESP32 boards. These are the "sensors" of the network. They continuously measure
real-world network conditions — latency between nodes, signal strength (RSSI), packet loss —
and stream that data to the Jetson. They represent edge nodes in a real ISP network (think: a
small device installed at a base station or exchange point that monitors what's happening there).

### Layer 4 — Edge-Inference Integration Layer
Running on your Jetson TX2. This is the bridge between the sensors and the controller. It receives
raw telemetry from the ESP32s, runs it through an AI model to detect anomalies and predict
failures, and then sends actionable insights to the Ryu controller via REST API. The controller
then acts on those insights.

### What is AQoSRM?
**Adaptive QoS Routing Mechanism** is the name for your intelligent traffic prioritization
algorithm. It runs inside the Ryu controller and classifies incoming traffic into priority tiers:

| Priority | Traffic Type | Example |
|---|---|---|
| Highest | Real-time voice | VoIP calls |
| High | Real-time video | Telemedicine, video conferencing |
| Medium | Interactive | Web browsing, online banking |
| Low | Bulk transfer | File downloads, backups |

When the network is congested or recovering from a fault, AQoSRM ensures high-priority
traffic gets through first. Low-priority traffic is delayed, not dropped entirely.

---

## 4. Your Hardware & What Each Device Does

### Linux PC
**Role:** SDN Controller + Virtual Network  
**What runs on it:**
- Mininet (creates virtual switches and links)
- Ryu SDN controller (the brain of the network)
- iPerf3 (generates test traffic)

**Why it's here:** You don't have physical OpenFlow switches. Mininet solves this by creating a
full software-simulated network that Ryu controls exactly as it would control real hardware.
Mininet lets you create 10, 20, 50 virtual switches and links on one machine.

---

### Jetson TX2
**Role:** AI Inference Engine + Edge-Inference Integration Layer + MQTT Broker  
**What runs on it:**
- Mosquitto (MQTT message broker — receives all ESP32 telemetry)
- FastAPI server (REST API that Ryu calls to get AI insights)
- Python telemetry processor (cleans and formats incoming data)
- AI model (PyTorch or Scikit-learn — detects anomalies, predicts failures)

**Why the Jetson specifically:** The Jetson TX2 has a GPU that can run neural network inference
efficiently. Running the AI model here — close to the data source — rather than in the cloud is
the whole point of "edge AI." It keeps latency low and means the system still works if internet
connectivity is disrupted.

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

### Windows PCs
**Role:** Traffic clients and load generators  
**What they do:**
- Run iPerf3 as clients generating bulk TCP traffic (simulating file downloads)
- Run custom UDP scripts simulating VoIP traffic (small packets, constant rate, time-sensitive)
- Connect to Mininet's virtual network through a bridge interface

---

### Android Phones
**Role:** Real-time application clients  
**What they do:**
- Run actual VoIP or video streaming apps to generate genuine real-time traffic
- Demonstrate that QoS prioritization produces a measurable difference in call quality

---

## 5. How Everything Communicates

```
ESP32 #2 ──┐
ESP32 #3 ──┤  ESP-NOW   ┌─────────────┐   MQTT (WiFi)   ┌──────────────────┐
ESP32 #4 ──┼───────────►│  ESP32 #1   │────────────────►│   Jetson TX2     │
ESP32 #5 ──┘            │  (Gateway)  │                  │  (MQTT Broker +  │
                        └─────────────┘                  │   AI Engine +    │
                                                         │   FastAPI)       │
                                                         └────────┬─────────┘
                                                                  │
                                                           REST API (HTTP)
                                                                  │
                                                         ┌────────▼─────────┐
                                                         │    Linux PC      │
                                                         │  (Ryu Controller │
                                                         │   + Mininet)     │
                                                         └────────┬─────────┘
                                                                  │
                                                            OpenFlow
                                                                  │
                                                    ┌─────────────▼──────────────┐
                                                    │   Virtual Switches         │
                                                    │   (Mininet topology)       │
                                                    └─────────────┬──────────────┘
                                                                  │
                                                    Windows PCs / Android Phones
                                                    (iPerf, VoIP clients)
```

### Communication Protocols Explained

| Link | Protocol | Why |
|---|---|---|
| ESP32 #2–5 → ESP32 #1 | ESP-NOW | Fast, no router needed, works peer-to-peer |
| ESP32 #1 → Jetson | MQTT over WiFi | Lightweight pub/sub, ideal for sensor data |
| Jetson → Ryu (Linux PC) | HTTP REST API | Simple, Ryu already has REST support built in |
| Ryu → Virtual Switches | OpenFlow (TCP port 6633) | The SDN standard protocol |
| Windows PCs → Network | iPerf3 / UDP sockets | Standard traffic generation |

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

When it spots something suspicious, it immediately tells your network controller (Ryu on the
Linux PC): "Link between Town A and Town B is degrading, I predict it will fail in 30 seconds."

The controller doesn't wait for the link to actually fail. It immediately recalculates the best route
avoiding that link and reprograms all your switches to use the new path. By the time the link
actually fails, all traffic has already been rerouted. A voice call happening across that link never
drops — it was seamlessly moved before the problem hit.

Meanwhile, the controller knows that the rerouted path has less capacity than the original. So it
tells the switches: "For now, voice calls get priority. Video gets second priority. File downloads
can wait." This is AQoSRM in action.

That entire process — detect, predict, reroute, prioritize — happens in under 50 milliseconds.
A traditional OSPF network would take 30–60 seconds to do the same thing, if it managed it at all.

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
| Congestion | Latency rising, RSSI stable | AQoSRM prioritization |
| Node failure | No response from node | Remove from topology |

### Recommended Model Architecture

For your prototype, use one of these — in order of recommendation:

**Option 1 — Isolation Forest (Best starting point)**
- Unsupervised, so you don't need labelled "fault" data to train it
- Scikit-learn, runs fast on Jetson CPU
- Trains on 10–15 minutes of normal network operation data you collect yourself
- Very explainable — easy to justify in your thesis

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
Then deliberately introduce faults:
- Physically move an ESP32 far away (simulate link degradation)
- Power off an ESP32 (simulate node failure)
- Run heavy WiFi traffic from other devices (simulate congestion)
- Block ESP-NOW channel briefly (simulate link fault)

Log everything with labels. This gives you real data from your exact hardware.

#### Option B — Public Network Anomaly Datasets
These are well-known datasets used in networking research:

| Dataset | What It Contains | Where to Get It |
|---|---|---|
| **CAIDA** | Real internet traffic traces with anomalies | https://www.caida.org/catalog/datasets/ |
| **KDD Cup 1999** | Network intrusion/anomaly data, labelled | http://kdd.ics.uci.edu/databases/kddcup99/ |
| **UNSW-NB15** | Modern network traffic with 9 attack/anomaly types | https://research.unsw.edu.au/projects/unsw-nb15-dataset |
| **CIC-IDS-2017** | Intrusion detection with realistic background traffic | https://www.unb.ca/cic/datasets/ids-2017.html |
| **ToN_IoT** | IoT network telemetry with anomaly labels | https://research.unsw.edu.au/projects/toniot-datasets |

> **Best choice from this list:** ToN_IoT — it's IoT-specific (closest to your ESP32 setup)
> and UNSW-NB15 for a well-cited benchmark dataset to validate your model.

#### Option C — Synthetic Data Generation
Use Python to generate synthetic telemetry streams with injected fault patterns. This is useful
for training the LSTM before you have real data, and for augmenting your real dataset.

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
Jetson receives, buffers last 30 readings (sliding window)
         │
         ▼ Feature vector: [mean_latency, std_latency, mean_rssi, packet_loss, trend]
AI model scores the window → anomaly score 0.0–1.0
         │
         ▼ If score > 0.75:
POST http://linux-pc:8080/zan/insight
{ "type": "LINK_DEGRADATION", "nodes": ["esp32_02","esp32_03"], "confidence": 0.91 }
         │
         ▼
Ryu receives insight → recalculates path → pushes OpenFlow rules
```

---

## 8. Software Stack Summary

### Linux PC
| Software | Version | Purpose | Install |
|---|---|---|---|
| Mininet | 2.3.x | Virtual network | `sudo apt install mininet` |
| Ryu | 4.34 | SDN controller | `pip install ryu` |
| iPerf3 | 3.x | Traffic generation | `sudo apt install iperf3` |
| Python | 3.10+ | Ryu apps | System |
| Open vSwitch | 2.x | Mininet backend | `sudo apt install openvswitch-switch` |

### Jetson TX2 (Ubuntu 18.04/20.04)
| Software | Version | Purpose | Install |
|---|---|---|---|
| Mosquitto | 2.x | MQTT broker | `sudo apt install mosquitto` |
| Paho MQTT | 1.6 | Python MQTT client | `pip install paho-mqtt` |
| FastAPI | 0.100+ | REST API server | `pip install fastapi uvicorn` |
| PyTorch | JetPack build | AI model | From NVIDIA JetPack SDK |
| Scikit-learn | 1.3 | Isolation Forest | `pip install scikit-learn` |
| NumPy/Pandas | latest | Data processing | `pip install numpy pandas` |

### ESP32 (Arduino IDE or PlatformIO)
| Library | Purpose |
|---|---|
| `esp_now.h` | ESP-NOW peer-to-peer comms |
| `WiFi.h` | WiFi connection (gateway only) |
| `PubSubClient` | MQTT client (gateway only) |
| `ArduinoJson` | JSON serialization |

---

## 9. Development Roadmap — Step by Step

Work through these phases in order. Do not skip phases. Each phase validates the foundation
the next phase depends on.

---

### PHASE 1 — ESP32 Telemetry Pipeline
**Goal:** Get real data flowing from ESP32s to Jetson.  
**Duration:** ~1 week  
**Why first:** Everything else depends on having live telemetry. Validate this works before
building anything on top of it.

**Steps:**
1. Flash ESP32 #2–5 with sensor firmware:
   - Continuously ping each other via ESP-NOW (every 2 seconds)
   - Measure round-trip latency and packet loss
   - Measure RSSI to each peer
   - Send results to ESP32 #1 via ESP-NOW
2. Flash ESP32 #1 (gateway) with aggregator firmware:
   - Receive from all peers via ESP-NOW
   - Connect to your WiFi network
   - Connect to Mosquitto on the Jetson
   - Publish JSON telemetry to `zan/telemetry/<node_id>`
3. Install and run Mosquitto on Jetson
4. Write a Python subscriber on the Jetson that logs all incoming MQTT messages to CSV

**Deliverable:** A CSV file of real network telemetry from your ESP32s, updating every 2 seconds.

---

### PHASE 2 — Mininet + Ryu Control Plane
**Goal:** Get a working virtual SDN network with Ryu controlling it.  
**Duration:** ~1 week  
**Why second:** The control plane is the core of SDN. Validate routing and flow control works
in isolation before connecting it to the AI layer.

**Steps:**
1. Install Mininet and Open vSwitch on Linux PC
2. Write a Mininet topology script:
   - 6 switches representing ISP nodes
   - Multiple redundant links with different costs
   - Host nodes on each switch representing clients
3. Write a basic Ryu controller app:
   - Discovers topology using LLDP
   - Installs shortest-path flow rules using Dijkstra
   - Implements basic OpenFlow packet-in handling
4. Test basic connectivity: `h1 ping h6` should work
5. Add QoS queues to Mininet links (bandwidth limits per queue)
6. Implement AQoSRM in Ryu:
   - Classify traffic by IP protocol / port number (UDP port 5060 = VoIP, TCP bulk = low priority)
   - Assign flows to appropriate queues

**Deliverable:** A Mininet network where you can run iPerf and observe that VoIP-simulated
UDP traffic gets lower latency than bulk TCP traffic under congestion.

---

### PHASE 3 — AI Model Development
**Goal:** Train an anomaly detection model that can classify network faults.  
**Duration:** ~1.5 weeks  
**Why third:** You need the data pipeline from Phase 1 working before you can collect
training data.

**Steps:**
1. Run your Phase 1 setup for 1–2 hours to collect baseline "normal" telemetry
2. Deliberately introduce faults (move ESP32s, power cycle them, cause interference)
   and label the fault periods in your CSV
3. Download ToN_IoT or UNSW-NB15 dataset to supplement your data
4. Feature engineer your telemetry:
   - Rolling mean latency (window=10)
   - Rolling std latency (window=10)
   - Latency trend (slope over last 10 samples)
   - Packet loss rate
   - RSSI drop rate
5. Train an Isolation Forest model on normal data only
6. Optionally train an LSTM Autoencoder on the full time series
7. Evaluate: measure precision/recall on your labelled fault events
8. Export model to ONNX or pickle for deployment on Jetson
9. Write a real-time inference script that:
   - Maintains a sliding window of the last 30 telemetry readings
   - Runs inference every time a new reading arrives
   - Outputs anomaly type and confidence score

**Deliverable:** A model running on the Jetson that correctly flags introduced faults in real time.

---

### PHASE 4 — Edge-Inference Integration Layer
**Goal:** Connect the Jetson AI engine to the Ryu controller.  
**Duration:** ~1 week  
**Why fourth:** Only build this bridge once both ends (AI model and Ryu controller) are
independently working.

**Steps:**
1. Write a FastAPI app on the Jetson with two endpoints:
   - `GET /zan/status` — returns current network health
   - `POST /zan/insight` — Ryu polls this, or Jetson pushes to Ryu
2. Decide on push vs poll:
   - **Push (recommended):** Jetson POSTs to Ryu's REST API when anomaly detected
   - **Poll:** Ryu queries Jetson every 500ms
3. Add a REST client to your Ryu controller that:
   - Receives an insight: `{"type": "LINK_DEGRADATION", "nodes": ["A","B"], "confidence": 0.91}`
   - Maps the physical node IDs to Mininet switch DPIDs
   - Recalculates shortest path excluding degraded link
   - Pushes new flow rules via OpenFlow
4. Test end-to-end:
   - Move an ESP32 to cause latency spike
   - Watch Jetson detect anomaly
   - Watch Ryu reroute Mininet traffic
   - Measure time from anomaly start to reroute completion (your MTTR)

**Deliverable:** End-to-end automated rerouting triggered by real ESP32 telemetry.

---

### PHASE 5 — AQoSRM Full Integration & Measurement
**Goal:** Demonstrate measurable QoS improvement and collect results for your thesis.  
**Duration:** ~1 week  
**Why last:** This is your results/validation phase. Everything must be working before
you can measure anything meaningful.

**Steps:**
1. Set up iPerf3 on Windows PCs:
   - Client 1: iPerf3 UDP, 100kbps, 20ms packet interval (VoIP simulation)
   - Client 2: iPerf3 TCP, max bandwidth (bulk download simulation)
   - Both running simultaneously through Mininet
2. Measure baseline (no QoS, no AI):
   - VoIP latency, jitter, packet loss
   - Bulk transfer throughput
3. Enable AQoSRM:
   - Measure same metrics — VoIP should be dramatically better
4. Introduce link fault (power off an ESP32):
   - Measure MTTR with ZAN vs without (OSPF-like convergence)
5. Record all measurements in a table for your thesis
6. Run 5+ trials of each scenario for statistical validity

**Deliverable:** Data tables showing latency reduction, MTTR improvement, and QoS
performance — the evidence for your H1 and H2 hypotheses.

---

## 10. How You Prove Your Objectives

### Objective 1 — AQoSRM
**Experiment:** Run VoIP + bulk traffic simultaneously through Mininet with congestion.  
**Measure:** Latency and packet loss for VoIP stream WITH and WITHOUT AQoSRM.  
**Expected result:** >70% reduction in VoIP latency under congestion (per H1 in your paper).

### Objective 2 — ZAN Hybrid Framework
**Experiment:** Introduce a simulated link failure (power off ESP32 node).  
**Measure:** Time from failure detection to successful reroute (MTTR).  
**Expected result:** MTTR < 50ms for ZAN vs 30–60 seconds for OSPF convergence.

### Objective 3 — Edge-Inference Integration Layer
**Experiment:** Inject gradual link degradation (slowly move ESP32 further away).  
**Measure:** Time from degradation start to anomaly alert from Jetson.  
**Also measure:** False positive rate — does it trigger on normal variation?  
**Expected result:** Anomaly detected and reroute triggered before complete link failure.

---

## 11. Common Pitfalls to Avoid

**ESP-NOW range:** ESP-NOW range indoors is typically 10–50m. Keep ESP32s within range
during testing and note the range in your methodology.

**Mininet and physical bridging:** Getting Mininet to pass traffic from/to real Windows PCs
requires a bridge interface on the Linux PC. Plan this carefully — it is the trickiest networking
step in the whole project.

**Ryu version:** Ryu 4.34 is the last stable version and requires Python 3.6–3.8. Use a
virtualenv to avoid conflicts with newer Python on your Linux PC.

**MQTT on the same WiFi as ESP32s:** If your Linux PC and Jetson are on the same WiFi
network as the ESP32s, use the Jetson's IP address (not `localhost`) in the ESP32 MQTT
configuration. Use `mosquitto -v` to debug connection issues.

**AI model overfitting:** If you train only on your own ESP32 data, your model may be too
specific to your lab environment. Use the public datasets to add diversity to your training data.

**Thesis positioning:** Your paper explicitly states ZAN is different from purely
simulation-based work. When writing your methodology, clearly state: "Physical telemetry is
collected from real ESP32 hardware nodes; the SDN control plane is demonstrated using Mininet
as a software emulation layer due to hardware constraints, which is a widely accepted approach
in SDN research prototyping."

**Measurement timing:** Use Python's `time.perf_counter()` (not `time.time()`) for
sub-millisecond MTTR measurements. Log timestamps at both the anomaly detection event and
the flow rule installation confirmation.

---

*This guide covers the full scope of the ZAN prototype. Implement one phase at a time,
validate each phase before proceeding, and keep logs of all measurements from Phase 5 onwards.*

---
**Project:** ZAN — Zimbabwe Adaptive Network  
**Student:** Tanaka Keith Mashoko (H220325F)  
**Institution:** Harare Institute of Technology  
**Module:** HIT 400
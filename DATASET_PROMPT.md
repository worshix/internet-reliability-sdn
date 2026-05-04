# ZAN Telemetry Dataset Generation Prompt

## Hardware Architecture

The ZAN network has **5 ESP32 boards total**:
- **4 sensor nodes**: `esp32_01`, `esp32_02`, `esp32_03`, `esp32_04`
  - Each node pings every other node via ESP-NOW every **2 seconds**
  - Every **5 seconds** it flushes averaged stats to the gateway as a `TelemetryPkt`
  - Pong timeout: **500 ms** (pings with no reply within 500 ms count as lost)
- **1 gateway** (5th board): receives `TelemetryPkt` from nodes over ESP-NOW,
  publishes them to MQTT on topic `zan/telemetry/esp32_0N`.
  **The gateway is NOT a sensor node** — it never appears as `node_id` or
  `target_node` in the dataset.

The physical mesh is **fully connected**: every pair among the 4 nodes pings each other.

---

## Firmware-Derived Measurement Semantics

These constraints come directly from the node firmware and must be preserved:

| Property | Detail |
|---|---|
| `latency_ms` | **One-way** latency = RTT / 2. Computed as average over pongs received in the 5 s window. When **all** pings to a peer are lost: `latency_ms = 999.0`. |
| `rssi_dbm` | Average RSSI of all pong frames received from the peer in the 5 s window. When all pings lost: `rssi_dbm = -127`. |
| `packet_loss_pct` | `(pings_sent − pongs_received) / pings_sent`. With PING_INTERVAL=2 s and TELEMETRY_INTERVAL=5 s, approximately **2–3 pings** are sent per peer per window. Valid values: `0.0000` (0/3), `0.3333` (1/3), `0.5000` (1/2), `0.6667` (2/3), `1.0000` (3/3 or 2/2). |
| `uptime_s` | `millis() / 1000` on the **sensor node**. Monotonically increasing per node. Resets to ~5 after a reboot. |
| `timestamp` | `millis() / 1000` on the **gateway**. Reflects gateway uptime, not node uptime — can have ±1 s jitter within a batch. |

---

## Real Observed Data (ground truth for calibration)

Captured from the live MQTT broker. Use these to calibrate value ranges and noise.

```
node_id    target_node  latency_ms  rssi_dbm  packet_loss_pct  uptime_s  timestamp
esp32_01   esp32_02     6.8         -25       0.0000           5         4
esp32_01   esp32_03     11.5        -28       0.0000           5         5
esp32_01   esp32_04     9.8         -25       0.0000           5         5
esp32_02   esp32_01     10.5        -26       0.0000           5         5
esp32_02   esp32_03     9.8         -30       0.0000           5         5
esp32_02   esp32_04     7.0         -32       0.0000           5         5
esp32_03   esp32_01     13.5        -30       0.0000           5         5
esp32_03   esp32_02     10.8        -33       0.0000           5         5
esp32_03   esp32_04     11.5        -20       0.0000           5         5
esp32_04   esp32_01     12.5        -30       0.0000           5         5
esp32_04   esp32_02     10.3        -34       0.0000           5         5
esp32_04   esp32_03     12.3        -21       0.0000           5         5
esp32_02   esp32_01     12.0        -33       0.3333           10        10
esp32_02   esp32_03     15.5        -32       0.3333           10        10
esp32_04   esp32_01     5.0         -31       0.3333           10        10
esp32_04   esp32_03     19.0        -22       0.3333           10        10
esp32_01   esp32_02     12.5        -23       0.3333           10        10
esp32_03   esp32_04     15.5        -22       0.3333           10        10
esp32_01   esp32_02     10.7        -26       0.0000           15        14
esp32_04   esp32_02     13.7        -35       0.0000           15        15
esp32_03   esp32_04     12.8        -22       0.0000           15        15
esp32_01   esp32_02     2.8         -24       0.3333           20        20
esp32_01   esp32_03     7.5         -34       0.3333           20        20
esp32_03   esp32_04     13.0        -25       0.3333           20        20
esp32_01   esp32_02     6.7         -25       0.0000           25        24
esp32_04   esp32_02     15.2        -34       0.0000           25        25
esp32_02   esp32_04     16.5        -28       0.0000           25        25
```

---

## Output Format

Generate a **CSV file** named `zan_telemetry_dataset.csv` with the following columns
in this exact order:

```
timestamp,node_id,target_node,latency_ms,rssi_dbm,packet_loss_pct,uptime_s,anomaly_label,anomaly_type
```

| Column | Type | Description |
|---|---|---|
| `timestamp` | int | Gateway seconds since boot. Increments ~5 per batch with ±1 s jitter. |
| `node_id` | string | Reporting sensor node: `esp32_01` … `esp32_04` only. |
| `target_node` | string | Peer being pinged. Always different from `node_id`. `esp32_01`–`esp32_04` only. |
| `latency_ms` | float (1 dp) | One-way latency in ms. 999.0 when all pings lost. |
| `rssi_dbm` | int | Average RSSI in dBm. Always negative. -127 when all pings lost. |
| `packet_loss_pct` | float (4 dp) | Fraction of pings lost. See valid values above. |
| `uptime_s` | int | Node uptime in seconds. Monotone per node, resets after reboot. |
| `anomaly_label` | int | **0** = normal, **1** = anomaly |
| `anomaly_type` | string | `normal`, `packet_loss`, `high_latency`, `rf_interference`, `node_degrading`, `node_down` |

---

## Dataset Size and Class Balance

- **Total rows**: 4500
- **Normal rows** (`anomaly_label=0`): ~3700 (~82%)
- **Anomaly rows** (`anomaly_label=1`): ~800 (~18%)

Anomaly breakdown:

| Anomaly type | Approx. rows | Notes |
|---|---|---|
| `packet_loss` | 250 | Most common fault in ESP-NOW |
| `high_latency` | 180 | CPU/relay contention bursts |
| `rf_interference` | 160 | WiFi channel overlap, obstacles |
| `node_degrading` | 120 | Gradual multi-batch worsening |
| `node_down` | 90 | Complete outage + recovery rows |

---

## Normal Behaviour Specification

**Batch structure**: each batch (every ~5 simulated seconds) produces up to **12 rows**
(4 nodes × 3 peers each). Drop ~15% of rows randomly within a batch to simulate
ESP-NOW scheduling jitter and missed telemetry flushes. Never drop all rows for a
given `node_id` in a batch unless `node_down`.

**Normal value ranges** (apply Gaussian noise within bounds):

| Field | Normal range | Noise σ |
|---|---|---|
| `latency_ms` | 4.0 – 19.0 ms | ±1.5 ms |
| `rssi_dbm` | -20 to -36 dBm | ±2 dBm |
| `packet_loss_pct` | 0.0000 | — |
| `uptime_s` | monotone +5/batch | — |

**Per-pair RSSI and latency baselines** (derived from real data; add noise):

| Pair | latency_ms | rssi_dbm |
|---|---|---|
| esp32_01 ↔ esp32_02 | 6 – 11 ms | -23 to -27 |
| esp32_01 ↔ esp32_03 | 10 – 14 ms | -28 to -34 |
| esp32_01 ↔ esp32_04 | 9 – 14 ms | -25 to -33 |
| esp32_02 ↔ esp32_03 | 9 – 15 ms | -28 to -33 |
| esp32_02 ↔ esp32_04 | 7 – 16 ms | -30 to -35 |
| esp32_03 ↔ esp32_04 | 11 – 16 ms | -20 to -27 |

**Symmetry rule**: A→B and B→A rows in the same batch must be correlated:
latency within ±2 ms of each other, RSSI within ±3 dBm.

---

## Anomaly Type Specifications

### 1. `packet_loss`
ESP-NOW channel congestion or interference causing dropped pings.
- `packet_loss_pct`: 0.3333, 0.5000, or 0.6667
- `latency_ms`: the **average of pongs that did arrive** — may appear lower than usual
  because only the fastest replies are received; or up to +30% above normal
- `rssi_dbm`: within normal range (RF is fine — it is a congestion issue)
- Both A→B and B→A rows on the affected link should show correlated loss
- Duration: 1–4 consecutive batches, then recovers to 0.0000
- `anomaly_label`: 1

### 2. `high_latency`
Latency spike with no packet loss (CPU overload, relay queuing, ping-flood collision).
- `packet_loss_pct`: 0.0000
- `latency_ms`: 30 – 150 ms (firmware cap at 999.0 for total loss, so stay below)
- `rssi_dbm`: normal range
- Duration: 1–3 batches, then recovers
- `anomaly_label`: 1

### 3. `rf_interference`
RF degradation (WiFi channel collision, physical obstruction, reflections).
- `rssi_dbm`: -55 to -85 dBm (well below normal floor of -36)
- `packet_loss_pct`: correlated with RSSI — worse signal → more loss:
  - RSSI -55 to -65: 0.3333
  - RSSI -65 to -75: 0.6667
  - RSSI below -75: 1.0000 (latency_ms = 999.0, rssi_dbm = -127)
- `latency_ms`: +40–100% above normal when some pongs arrive; 999.0 if all lost
- Affects **one specific link** for 2–6 consecutive batches; gradually worsens then
  recovers or abruptly clears
- `anomaly_label`: 1

### 4. `node_degrading`
Gradual hardware failure — all links to/from one node degrade simultaneously
(antenna loosening, power-supply noise, thermal throttling).
- Over 5–10 batches, for **all peers of the affected node**:
  - RSSI decreases by -4 to -6 dBm per batch
  - `latency_ms` increases by +2–4 ms per batch
  - `packet_loss_pct` steps: 0 → 0.3333 → 0.6667 → 1.0000
- `anomaly_label`: 0 while values are still within normal range; 1 once any field
  exits the normal band
- After the peak, either node reboots (triggers `node_down` briefly) or recovers

### 5. `node_down`
Complete node outage — the node stops sending pings and the gateway receives nothing
from it (node has crashed or lost power).
- During outage: **no rows with that `node_id`** appear in the batch.
  Rows where other nodes have that node as `target_node` should also be absent
  (the target is unreachable — no pong possible, so no telemetry row is emitted for
  that pair by any node, per firmware: `if (p.pings_sent == 0) continue;`).
- Outage duration: 3–8 consecutive batches
- On recovery: the node reappears with `uptime_s` reset to ~5, `packet_loss_pct`
  may be 0.3333 on the first batch as it re-syncs
- `anomaly_label`: 1 — mark the **last batch** before disappearance and the **first
  two batches** after recovery as anomaly
- Other nodes continue operating normally during the outage

---

## Temporal Structure

- Simulate **375 batches** (timestamp 5 to 1875, step ~5, ±1 s jitter).
- `uptime_s` per node ≈ `timestamp` value (both count from boot); introduce ±1 s
  of independent jitter per node to reflect firmware timing drift.
- **First 40 batches** (timestamps 5–200): entirely normal. This is the Isolation
  Forest training window.
- **Last 25 batches** (timestamps ~1750–1875): entirely normal. Allows clean
  end-of-run validation.
- Inject anomalies between batches 41–350. Do **not** distribute them uniformly —
  cluster faults realistically:
  - At least 2 instances where `rf_interference` on one link coincides with
    `packet_loss` on an adjacent link (fault cascade)
  - At least 1 `node_degrading` episode that ends in a `node_down` reboot
  - At least 4 isolated clean windows (≥ 8 normal batches) between anomaly clusters

---

## CSV Header and Example Rows

```csv
timestamp,node_id,target_node,latency_ms,rssi_dbm,packet_loss_pct,uptime_s,anomaly_label,anomaly_type
5,esp32_01,esp32_02,6.8,-25,0.0000,5,0,normal
5,esp32_01,esp32_03,11.5,-28,0.0000,5,0,normal
5,esp32_01,esp32_04,9.8,-25,0.0000,5,0,normal
5,esp32_02,esp32_01,10.5,-26,0.0000,5,0,normal
5,esp32_02,esp32_03,9.8,-30,0.0000,5,0,normal
5,esp32_02,esp32_04,7.0,-32,0.0000,5,0,normal
5,esp32_03,esp32_01,13.5,-30,0.0000,5,0,normal
5,esp32_03,esp32_02,10.8,-33,0.0000,5,0,normal
5,esp32_03,esp32_04,11.5,-20,0.0000,5,0,normal
5,esp32_04,esp32_01,12.5,-30,0.0000,5,0,normal
5,esp32_04,esp32_02,10.3,-34,0.0000,5,0,normal
5,esp32_04,esp32_03,12.3,-21,0.0000,5,0,normal
240,esp32_02,esp32_04,18.3,-31,0.3333,240,1,packet_loss
240,esp32_04,esp32_02,21.1,-33,0.3333,240,1,packet_loss
480,esp32_03,esp32_01,9.8,-68,0.6667,480,1,rf_interference
480,esp32_01,esp32_03,10.2,-71,0.6667,480,1,rf_interference
720,esp32_02,esp32_03,87.4,-31,0.0000,720,1,high_latency
960,esp32_04,esp32_01,21.3,-48,0.3333,960,1,node_degrading
960,esp32_04,esp32_02,23.7,-52,0.3333,960,1,node_degrading
960,esp32_04,esp32_03,25.1,-49,0.3333,960,1,node_degrading
1100,esp32_01,esp32_04,999.0,-127,1.0000,1100,1,node_down
```

---

## Output Instructions for the AI

1. Output the complete CSV — **do not truncate, summarise, or use ellipsis**.
2. Only use `node_id` and `target_node` values from `{esp32_01, esp32_02, esp32_03, esp32_04}`.
3. `packet_loss_pct` must be exactly one of: `0.0000`, `0.3333`, `0.5000`, `0.6667`, `1.0000`.
4. When `packet_loss_pct = 1.0000`: set `latency_ms = 999.0` and `rssi_dbm = -127`.
5. `latency_ms` must be to **1 decimal place**; `rssi_dbm` must be a **negative integer**.
6. `uptime_s` must never decrease for a node within its current boot lifecycle.
7. Respect the symmetry rule — A→B and B→A must appear in the same batch with
   correlated values whenever both nodes are operational.
8. `anomaly_type` must be exactly one of: `normal`, `packet_loss`, `high_latency`,
   `rf_interference`, `node_degrading`, `node_down`.
9. `anomaly_label` must be `0` when `anomaly_type` is `normal`, and `1` otherwise.

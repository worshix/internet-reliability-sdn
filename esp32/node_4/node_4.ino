/*
 * ZAN — Zimbabwe Adaptive Network
 * Sensor Node Firmware  |  ESP32 #5  (node_id = 5)
 *
 * Responsibilities:
 *   - Ping every peer node via ESP-NOW every 2 s to measure RTT
 *   - Record RSSI per peer from incoming ESP-NOW frames
 *   - Track packet loss (pings without pong within timeout)
 *   - Send a TelemetryPkt to the gateway every 5 s
 *
 * Required: Arduino-ESP32 core >= 3.0.0
 * Libraries: none beyond the ESP32 board package
 */

#include <esp_now.h>
#include <WiFi.h>

// ================================================================
//  NODE CONFIGURATION
// ================================================================
#define THIS_NODE_ID  5   // unique ID for this board (5 = ESP32 #5)

// ================================================================
//  MAC ADDRESSES
//  Run the MAC-discovery sketch on each board first (see README).
//  Replace the placeholder bytes below with the real MAC addresses.
// ================================================================
uint8_t GATEWAY_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
uint8_t NODE2_MAC[6]   = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
uint8_t NODE3_MAC[6]   = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
uint8_t NODE4_MAC[6]   = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
uint8_t NODE5_MAC[6]   = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// ================================================================
//  TIMING
// ================================================================
#define PING_INTERVAL_MS      2000
#define TELEMETRY_INTERVAL_MS 5000
#define PONG_TIMEOUT_MS        500

// ================================================================
//  PACKET DEFINITIONS  (must match gateway firmware exactly)
// ================================================================
#define PKT_PING      0x01
#define PKT_PONG      0x02
#define PKT_TELEMETRY 0x03

typedef struct __attribute__((packed)) {
    uint8_t  pkt_type;
    uint8_t  src_node;
    uint16_t ping_id;
    uint32_t sent_ms;
} PingPkt;

typedef struct __attribute__((packed)) {
    uint8_t  pkt_type;
    uint8_t  src_node;
    uint16_t ping_id;
    uint32_t sent_ms;
} PongPkt;

typedef struct __attribute__((packed)) {
    uint8_t  pkt_type;
    uint8_t  src_node;
    uint8_t  target_node;
    float    latency_ms;
    int8_t   rssi_dbm;
    float    packet_loss_pct;
    uint32_t uptime_s;
} TelemetryPkt;

// ================================================================
//  PEER TABLE
// ================================================================
struct PeerStats {
    uint8_t  node_id;
    uint8_t  mac[6];

    uint16_t ping_id_counter;
    uint16_t pending_ping_id;
    uint32_t pending_sent_ms;
    bool     ping_pending;

    volatile uint32_t pings_sent;
    volatile uint32_t pongs_received;
    volatile float    latency_sum_ms;
    volatile int32_t  rssi_sum;
    volatile uint16_t rssi_count;
};

static PeerStats peers[4];
static int       peer_count = 0;

void buildPeerList() {
    struct { uint8_t id; uint8_t *mac; } all[] = {
        {2, NODE2_MAC},
        {3, NODE3_MAC},
        {4, NODE4_MAC},
        {5, NODE5_MAC},
    };
    peer_count = 0;
    for (int i = 0; i < 4; i++) {
        if (all[i].id == THIS_NODE_ID) continue;
        PeerStats &p = peers[peer_count++];
        p.node_id         = all[i].id;
        memcpy(p.mac, all[i].mac, 6);
        p.ping_id_counter = 0;
        p.ping_pending    = false;
        p.pings_sent      = 0;
        p.pongs_received  = 0;
        p.latency_sum_ms  = 0;
        p.rssi_sum        = 0;
        p.rssi_count      = 0;
    }
}

int peerIdxById(uint8_t id) {
    for (int i = 0; i < peer_count; i++)
        if (peers[i].node_id == id) return i;
    return -1;
}

// ================================================================
//  ESP-NOW CALLBACKS
// ================================================================
void onDataSent(const uint8_t *mac, esp_now_send_status_t status) {}

void onDataRecv(const esp_now_recv_info_t *recv_info,
                const uint8_t *data, int len) {
    if (len < 1) return;
    int8_t rssi = recv_info->rx_ctrl->rssi;

    switch (data[0]) {

    case PKT_PING: {
        if (len < (int)sizeof(PingPkt)) return;
        const PingPkt *ping = (const PingPkt*)data;
        PongPkt pong;
        pong.pkt_type = PKT_PONG;
        pong.src_node = THIS_NODE_ID;
        pong.ping_id  = ping->ping_id;
        pong.sent_ms  = ping->sent_ms;
        esp_now_send((uint8_t*)recv_info->src_addr,
                     (uint8_t*)&pong, sizeof(pong));
        break;
    }

    case PKT_PONG: {
        if (len < (int)sizeof(PongPkt)) return;
        const PongPkt *pong = (const PongPkt*)data;
        int idx = peerIdxById(pong->src_node);
        if (idx < 0) return;

        PeerStats &p = peers[idx];
        if (p.ping_pending && p.pending_ping_id == pong->ping_id) {
            uint32_t rtt = millis() - pong->sent_ms;
            p.ping_pending = false;
            p.pongs_received++;
            p.latency_sum_ms += rtt / 2.0f;
            p.rssi_sum  += rssi;
            p.rssi_count++;
        }
        break;
    }

    default: break;
    }
}

// ================================================================
//  PING
// ================================================================
void sendPing(int idx) {
    PeerStats &p = peers[idx];
    if (p.ping_pending &&
        millis() - p.pending_sent_ms > PONG_TIMEOUT_MS) {
        p.ping_pending = false;
    }
    if (p.ping_pending) return;

    p.ping_id_counter++;
    PingPkt ping;
    ping.pkt_type = PKT_PING;
    ping.src_node = THIS_NODE_ID;
    ping.ping_id  = p.ping_id_counter;
    ping.sent_ms  = millis();

    p.pending_ping_id = p.ping_id_counter;
    p.pending_sent_ms = ping.sent_ms;
    p.ping_pending    = true;
    p.pings_sent++;

    esp_now_send(p.mac, (uint8_t*)&ping, sizeof(ping));
}

// ================================================================
//  TELEMETRY FLUSH
// ================================================================
void sendTelemetry() {
    for (int i = 0; i < peer_count; i++) {
        PeerStats &p = peers[i];
        if (p.pings_sent == 0) continue;

        TelemetryPkt tel;
        tel.pkt_type = PKT_TELEMETRY;
        tel.src_node = THIS_NODE_ID;
        tel.target_node = p.node_id;

        tel.latency_ms = (p.pongs_received > 0)
                         ? p.latency_sum_ms / p.pongs_received
                         : 999.0f;

        tel.rssi_dbm = (p.rssi_count > 0)
                       ? (int8_t)(p.rssi_sum / p.rssi_count)
                       : -127;

        tel.packet_loss_pct =
            (float)(p.pings_sent - p.pongs_received) / p.pings_sent;

        tel.uptime_s = millis() / 1000;

        esp_now_send(GATEWAY_MAC, (uint8_t*)&tel, sizeof(tel));

        Serial.printf("[TEL] node%d→node%d  lat=%.1fms  rssi=%d  loss=%.2f\n",
                      tel.src_node, tel.target_node,
                      tel.latency_ms, tel.rssi_dbm, tel.packet_loss_pct);

        p.pings_sent     = 0;
        p.pongs_received = 0;
        p.latency_sum_ms = 0;
        p.rssi_sum       = 0;
        p.rssi_count     = 0;
    }
}

// ================================================================
//  SETUP
// ================================================================
void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.printf("\n[ZAN] Sensor node %d starting\n", THIS_NODE_ID);

    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    Serial.printf("[ZAN] MAC: %s\n", WiFi.macAddress().c_str());

    if (esp_now_init() != ESP_OK) {
        Serial.println("[ZAN] ESP-NOW init FAILED — restarting");
        delay(1000);
        ESP.restart();
    }

    esp_now_register_send_cb(onDataSent);
    esp_now_register_recv_cb(onDataRecv);

    buildPeerList();

    esp_now_peer_info_t peer_info = {};
    peer_info.channel = 0;
    peer_info.encrypt = false;

    memcpy(peer_info.peer_addr, GATEWAY_MAC, 6);
    esp_now_add_peer(&peer_info);

    for (int i = 0; i < peer_count; i++) {
        memcpy(peer_info.peer_addr, peers[i].mac, 6);
        esp_now_add_peer(&peer_info);
    }

    Serial.printf("[ZAN] Node %d ready — %d peer(s) registered\n",
                  THIS_NODE_ID, peer_count + 1);
}

// ================================================================
//  LOOP
// ================================================================
static uint32_t last_ping_ms      = 0;
static uint32_t last_telemetry_ms = 0;

void loop() {
    uint32_t now = millis();

    for (int i = 0; i < peer_count; i++) {
        PeerStats &p = peers[i];
        if (p.ping_pending &&
            now - p.pending_sent_ms > PONG_TIMEOUT_MS) {
            p.ping_pending = false;
        }
    }

    if (now - last_ping_ms >= PING_INTERVAL_MS) {
        last_ping_ms = now;
        for (int i = 0; i < peer_count; i++) sendPing(i);
    }

    if (now - last_telemetry_ms >= TELEMETRY_INTERVAL_MS) {
        last_telemetry_ms = now;
        sendTelemetry();
    }
}

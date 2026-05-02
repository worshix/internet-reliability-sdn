/*
 * ZAN — Zimbabwe Adaptive Network
 * Gateway Node Firmware  |  ESP32 #1  (node_id = 1)
 *
 * Responsibilities:
 *   - Receive TelemetryPkt messages from sensor nodes via ESP-NOW
 *   - Connect to WiFi network "internet-sdn"
 *   - Publish JSON telemetry to Mosquitto MQTT broker on Jetson TX2
 *   - Topic format: zan/telemetry/esp32_0<N>
 *
 * Required: Arduino-ESP32 core >= 3.0.0
 * Libraries: PubSubClient, ArduinoJson  (install via Library Manager)
 *
 * IMPORTANT — channel note:
 *   ESP-NOW uses the same WiFi channel as the connected router.
 *   Sensor nodes run in STA mode (no WiFi connection) and default
 *   to channel 1. If telemetry is not arriving, set ESPNOW_CHANNEL
 *   on all boards to match your router's channel (typically 1, 6, or 11).
 *   Check your router admin page for the channel number.
 */

#include <esp_now.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "freertos/queue.h"

// ================================================================
//  WIFI CONFIGURATION
// ================================================================
const char* WIFI_SSID     = "internetSdn";
const char* WIFI_PASSWORD = "internetSdn";

// ================================================================
//  MQTT CONFIGURATION
//  Set MQTT_BROKER to the Jetson TX2's IP address on your network.
//  To find it: run  hostname -I  in a terminal on the Jetson.
// ================================================================
const char* MQTT_BROKER    = "10.127.239.85";
const int   MQTT_PORT      = 1883;
const char* MQTT_CLIENT_ID = "zan_gateway";

// ================================================================
//  MAC ADDRESSES
//  Run the MAC-discovery sketch on each board first (see README).
//  Replace the placeholder bytes below with the real MAC addresses.
// ================================================================
uint8_t NODE1_MAC[6] = {0xB4, 0xBF, 0xE9, 0x33, 0xA5, 0x60};
uint8_t NODE2_MAC[6] = {0xD4, 0xE9, 0xF4, 0xC5, 0x3E, 0x54};
uint8_t NODE3_MAC[6] = {0xE0, 0x8C, 0xFE, 0x31, 0xEB, 0x0C};
uint8_t NODE4_MAC[6] = {0xD4, 0xE9, 0xF4, 0xC4, 0x40, 0xBC};

// ================================================================
//  PACKET DEFINITION  (must match sensor node firmware exactly)
// ================================================================
#define PKT_TELEMETRY 0x03

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
//  THREAD-SAFE QUEUE
//  ESP-NOW callback runs in the WiFi FreeRTOS task.
//  MQTT publish must happen in the main Arduino task.
//  A FreeRTOS queue bridges the two safely.
// ================================================================
#define QUEUE_DEPTH 20
static QueueHandle_t telemetry_q = nullptr;

// ================================================================
//  ESP-NOW CALLBACK  (WiFi task context)
// ================================================================
void onDataRecv(const esp_now_recv_info_t *recv_info,
                const uint8_t *data, int len) {
    if (len < 1) return;
    if (data[0] == PKT_TELEMETRY && len == sizeof(TelemetryPkt)) {
        xQueueSend(telemetry_q, data, 0);   // non-blocking; drop if full
    }
}

// ================================================================
//  WIFI
// ================================================================
void connectWiFi() {
    if (WiFi.status() == WL_CONNECTED) return;

    Serial.printf("[ZAN] Connecting to WiFi: %s\n", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
        delay(500);
        Serial.print(".");
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[ZAN] WiFi connected  IP=%s\n",
                      WiFi.localIP().toString().c_str());
    } else {
        Serial.println("\n[ZAN] WiFi connection failed — will retry");
    }
}

// ================================================================
//  MQTT
// ================================================================
WiFiClient   wifi_client;
PubSubClient mqtt_client(wifi_client);

void connectMQTT() {
    if (WiFi.status() != WL_CONNECTED) { connectWiFi(); return; }
    if (mqtt_client.connected()) return;

    Serial.printf("[ZAN] Connecting to MQTT %s:%d\n",
                  MQTT_BROKER, MQTT_PORT);

    if (mqtt_client.connect(MQTT_CLIENT_ID)) {
        Serial.println("[ZAN] MQTT connected");
        mqtt_client.publish("zan/status", "{\"gateway\":\"online\"}");
    } else {
        Serial.printf("[ZAN] MQTT failed rc=%d\n", mqtt_client.state());
    }
}

// ================================================================
//  PUBLISH
// ================================================================
void publishTelemetry(const TelemetryPkt *pkt) {
    // topic: zan/telemetry/esp32_01 … esp32_04
    char topic[48];
    snprintf(topic, sizeof(topic), "zan/telemetry/esp32_0%d", pkt->src_node);

    // JSON payload matching the schema in overview.md §7
    StaticJsonDocument<256> doc;
    char node_id_str[12], target_str[12];
    snprintf(node_id_str, sizeof(node_id_str), "esp32_0%d", pkt->src_node);
    snprintf(target_str,  sizeof(target_str),  "esp32_0%d", pkt->target_node);

    doc["node_id"]         = node_id_str;
    doc["target_node"]     = target_str;
    doc["latency_ms"]      = round(pkt->latency_ms * 10.0f) / 10.0f;
    doc["rssi_dbm"]        = pkt->rssi_dbm;
    doc["packet_loss_pct"] = round(pkt->packet_loss_pct * 10000.0f) / 10000.0f;
    doc["uptime_s"]        = pkt->uptime_s;
    doc["timestamp"]       = millis() / 1000UL;

    char payload[256];
    serializeJson(doc, payload);

    bool ok = mqtt_client.publish(topic, payload, /*retain=*/false);
    Serial.printf("[ZAN] %s → %s  [%s]\n", topic, payload, ok ? "OK" : "FAIL");
}

// ================================================================
//  SETUP
// ================================================================
void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("\n[ZAN] Gateway starting");

    telemetry_q = xQueueCreate(QUEUE_DEPTH, sizeof(TelemetryPkt));
    if (!telemetry_q) {
        Serial.println("[ZAN] Queue creation FAILED");
        ESP.restart();
    }

    // AP_STA: allows ESP-NOW on the same channel as the WiFi connection
    WiFi.mode(WIFI_AP_STA);
    Serial.printf("[ZAN] Gateway MAC: %s\n", WiFi.macAddress().c_str());

    if (esp_now_init() != ESP_OK) {
        Serial.println("[ZAN] ESP-NOW init FAILED — restarting");
        delay(1000);
        ESP.restart();
    }

    esp_now_register_recv_cb(onDataRecv);

    // register sensor node peers
    esp_now_peer_info_t peer_info = {};
    peer_info.channel = 0;
    peer_info.encrypt = false;

    uint8_t *macs[] = {NODE1_MAC, NODE2_MAC, NODE3_MAC, NODE4_MAC};
    for (int i = 0; i < 4; i++) {
        memcpy(peer_info.peer_addr, macs[i], 6);
        esp_now_add_peer(&peer_info);
    }

    // connect WiFi + MQTT
    connectWiFi();
    mqtt_client.setServer(MQTT_BROKER, MQTT_PORT);
    mqtt_client.setKeepAlive(30);
    mqtt_client.setBufferSize(512);
    connectMQTT();

    Serial.println("[ZAN] Gateway ready — listening for telemetry");
}

// ================================================================
//  LOOP
// ================================================================
static uint32_t last_reconnect_ms = 0;

void loop() {
    // maintain MQTT connection
    if (!mqtt_client.connected()) {
        uint32_t now = millis();
        if (now - last_reconnect_ms >= 5000) {
            last_reconnect_ms = now;
            connectMQTT();
        }
    } else {
        mqtt_client.loop();
    }

    // drain telemetry queue and publish
    TelemetryPkt pkt;
    while (xQueueReceive(telemetry_q, &pkt, 0) == pdTRUE) {
        if (mqtt_client.connected()) {
            publishTelemetry(&pkt);
        }
        // if not connected, packet is dropped; reconnect handles next batch
    }
}

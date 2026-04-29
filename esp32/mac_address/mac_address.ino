#include <WiFi.h>
void setup() {
    Serial.begin(115200);
    WiFi.mode(WIFI_STA);
    delay(100);
    Serial.println("Wifi MAC_ADDRESS");
    Serial.println(WiFi.macAddress());
}
void loop() {}
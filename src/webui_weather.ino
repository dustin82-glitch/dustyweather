#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <SPIFFS.h>
#include <ArduinoOTA.h>
#include <RadioLib.h>

#include "webfiles.h"   // INDEX_HTML and GAUGE_JS

// ----------------- WiFi config -----------------
const char* ssid     = "Jarvis";
const char* password = "Maloo317";

// ----------------- Web server ------------------
WebServer server(80);

// ----------------- Cloud API config ------------
// Keep token out of source control in real deployments.
const char* cloudIngestUrl  = "https://weather-api.dustin-popp82.workers.dev/api/ingest";
const char* cloudDeviceToken = "Extasea10007!";
const char* cloudDeviceId   = "ws-01";

// ----------------- Sensor state ----------------
uint32_t latestSensorId   = 0;
bool     latestBattery    = false;
float    latestTemp       = 0.0f;
uint8_t  latestHumidity   = 0;
float    latestWindGust   = 0.0f;   // m/s
float    latestWindAvg    = 0.0f;   // m/s
uint16_t latestWindDir    = 0;      // degrees
float    latestRain       = 0.0f;   // mm

// ----------------- Cloud upload state ----------
bool cloudUploadPending = false;
unsigned long nextCloudUploadAttemptMs = 0;
uint32_t cloudUploadBackoffMs = 10000;  // 10s initial backoff

// ----------------- Radio / CC1101 --------------
CC1101 radio = new Module(5, 4, 2, 15);   // <-- adjust pins to your wiring

// ----------------- Logging helper --------------
void logMsg(const String& s) {
  Serial.println(s);
}

// ----------------- WiFi setup ------------------
void setup_wifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("WiFi connected, IP: ");
  Serial.println(WiFi.localIP());
}

// ----------------- Install web files into SPIFFS ------------------
void installWebFiles() {
  File index = SPIFFS.open("/index.html", FILE_WRITE);
  if (index) {
    index.print(INDEX_HTML);
    index.close();
    Serial.println("Installed /index.html");
  } else {
    Serial.println("Failed to write /index.html");
  }

  File gauge = SPIFFS.open("/gauge.min.js", FILE_WRITE);
  if (gauge) {
    gauge.print(GAUGE_JS);
    gauge.close();
    Serial.println("Installed /gauge.min.js");
  } else {
    Serial.println("Failed to write /gauge.min.js");
  }
}

// ----------------- HTTP handlers ------------------
void handleRoot() {
  File f = SPIFFS.open("/index.html", FILE_READ);
  if (!f) {
    server.send(500, "text/plain", "index.html missing");
    return;
  }
  server.streamFile(f, "text/html");
  f.close();
}

void handleGaugeJs() {
  File f = SPIFFS.open("/gauge.min.js", FILE_READ);
  if (!f) {
    server.send(500, "text/plain", "gauge.min.js missing");
    return;
  }
  server.streamFile(f, "application/javascript");
  f.close();
}

void handleData() {
  float gustKnots = latestWindGust * 1.94384f;
  float avgKnots  = latestWindAvg  * 1.94384f;

  String json = "{";
  json += "\"sid\":\"" + String(latestSensorId, HEX) + "\",";
  json += "\"bat\":\"" + String(latestBattery ? "Yes" : "No") + "\",";
  json += "\"temp\":" + String(latestTemp, 1) + ",";
  json += "\"hum\":" + String(latestHumidity) + ",";
  json += "\"avg\":" + String(avgKnots, 1) + ",";
  json += "\"gust\":" + String(gustKnots, 1) + ",";
  json += "\"dir\":" + String(latestWindDir) + ",";
  json += "\"rain\":" + String(latestRain, 1);
  json += "}";
  Serial.println("Serving /data: " + json);
  server.send(200, "application/json", json);
}

// ----------------- Cloud upload ----------------
void queueCloudUpload() {
  cloudUploadPending = true;
}

String buildCloudPayload() {
  // Keep cloud payload aligned with local /data names so fields are easy to trace.
  float gustKnots = latestWindGust * 1.94384f;
  float avgKnots  = latestWindAvg  * 1.94384f;
  String json = "{";
  json += "\"sid\":\"" + String(latestSensorId, HEX) + "\",";
  json += "\"bat\":\"" + String(latestBattery ? "Yes" : "No") + "\",";
  json += "\"temp\":" + String(latestTemp, 1) + ",";
  json += "\"hum\":" + String(latestHumidity) + ",";
  json += "\"avg\":" + String(avgKnots, 1) + ",";
  json += "\"gust\":" + String(gustKnots, 1) + ",";
  json += "\"dir\":" + String(latestWindDir) + ",";
  json += "\"rain\":" + String(latestRain, 1);
  Serial.println("Built cloud payload: " + json);
  json += "}";  
  return json;
}

void tryCloudUpload() {
  if (!cloudUploadPending) {
    return;
  }

  if (millis() < nextCloudUploadAttemptMs) {
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    nextCloudUploadAttemptMs = millis() + cloudUploadBackoffMs;
    return;
  }

  if (String(cloudDeviceToken) == "CHANGE_ME_DEVICE_TOKEN") {
    static bool warned = false;
    if (!warned) {
      Serial.println("[Cloud] Set cloudDeviceToken before uploading.");
      warned = true;
    }
    return;
  }

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  if (!http.begin(client, cloudIngestUrl)) {
    nextCloudUploadAttemptMs = millis() + cloudUploadBackoffMs;
    return;
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", cloudDeviceToken);

  String payload = buildCloudPayload();
  int code = http.POST(payload);
  http.end();

  if (code >= 200 && code < 300) {
    cloudUploadPending = false;
    cloudUploadBackoffMs = 10000;
    nextCloudUploadAttemptMs = 0;
    Serial.println("[Cloud] Upload OK");
    return;
  }

  cloudUploadBackoffMs = min<uint32_t>(cloudUploadBackoffMs * 2, 300000);
  nextCloudUploadAttemptMs = millis() + cloudUploadBackoffMs;
  Serial.printf("[Cloud] Upload failed, HTTP=%d, retry in %lu ms\n", code, static_cast<unsigned long>(cloudUploadBackoffMs));
}

// ----------------- Web server task (Core 0) ------------------
void WebServerTask(void *pvParameters) {
  for (;;) {
    server.handleClient();
    vTaskDelay(1);   // yield to WiFi stack
  }
}

// ----------------- Bresser 6-in-1 decoder ------------------
uint16_t lfsrDigest16(const uint8_t* data, size_t length, uint16_t gen, uint16_t key) {
  uint16_t sum = 0;
  for (size_t k = 0; k < length; ++k) {
    uint8_t byteVal = data[k];
    for (int i = 7; i >= 0; --i) {
      if ((byteVal >> i) & 1) {
        sum ^= key;
      }
      key = (key >> 1) ^ (key & 1 ? gen : 0);
    }
  }
  return sum;
}

int addBytes(const uint8_t* data, size_t length) {
  int result = 0;
  for (size_t i = 0; i < length; i++) {
    result += data[i];
  }
  return result;
}

bool decodeBresser6In1Full(const uint8_t* msg, size_t len) {
  if (len < 18) {
    return false;
  }

  uint16_t providedDigest = (msg[0] << 8) | msg[1];
  uint16_t calcDigest = lfsrDigest16(&msg[2], 15, 0x8810, 0x5412);
  if (providedDigest != calcDigest) {
    return false;
  }

  if ((addBytes(&msg[2], 16) & 0xFF) != 0xFF) {
    return false;
  }

  uint32_t id = (msg[2] << 24) | (msg[3] << 16) | (msg[4] << 8) | msg[5];
  bool batteryOk = (msg[13] & 0x02) != 0;

  bool tempOk = (msg[12] <= 0x99) && ((msg[13] & 0xF0) <= 0x90);
  int tempRaw = ((msg[12] >> 4) * 100) + ((msg[12] & 0x0F) * 10) + (msg[13] >> 4);
  bool tempSign = (msg[13] >> 3) & 1;
  float tempC = tempRaw * 0.1f;
  if (tempSign) {
    tempC = (tempRaw - 1000) * 0.1f;
  }

  int humidity = (msg[14] >> 4) * 10 + (msg[14] & 0x0F);

  uint8_t w7 = msg[7] ^ 0xFF;
  uint8_t w8 = msg[8] ^ 0xFF;
  uint8_t w9 = msg[9] ^ 0xFF;
  bool windOk = (w7 <= 0x99) && (w8 <= 0x99) && (w9 <= 0x99);
  float windGust = 0.0f;
  float windAvg = 0.0f;
  int windDir = 0;

  if (windOk) {
    int gustRaw = ((w7 >> 4) * 100) + ((w7 & 0x0F) * 10) + (w8 >> 4);
    windGust = gustRaw * 0.1f;

    int wavgRaw = ((w9 >> 4) * 100) + ((w9 & 0x0F) * 10) + (w8 & 0x0F);
    windAvg = wavgRaw * 0.1f;

    windDir = ((msg[10] & 0xF0) >> 4) * 100 + (msg[10] & 0x0F) * 10 + ((msg[11] & 0xF0) >> 4);
  }

  uint8_t r12 = msg[12] ^ 0xFF;
  uint8_t r13 = msg[13] ^ 0xFF;
  uint8_t r14 = msg[14] ^ 0xFF;
  float rainMm = 0.0f;
  bool rainOk = (msg[16] & 1) && (r12 <= 0x99) && (r13 <= 0x99) && (r14 <= 0x99);
  if (rainOk) {
    int rainRaw = ((r12 >> 4) * 100000) + ((r12 & 0x0F) * 10000) +
                  ((r13 >> 4) * 1000) + ((r13 & 0x0F) * 100) +
                  ((r14 >> 4) * 10) + (r14 & 0x0F);
    rainMm = rainRaw * 0.1f;
  }

  // Update sensor state used by /data endpoint.
  latestSensorId = id;
  latestBattery = batteryOk;
  if (tempOk) {
    latestTemp = tempC;
    latestHumidity = static_cast<uint8_t>(humidity);
  }
  if (windOk) {
    latestWindGust = windGust;
    latestWindAvg = windAvg;
    latestWindDir = static_cast<uint16_t>(windDir);
  }
  if (rainOk) {
    latestRain = rainMm;
  }

  queueCloudUpload();
 

  return true;
}

bool autoFindBresserSliceNoID(const uint8_t* recvData, size_t len) {
  for (int offset = 0; offset <= 9; offset++) {
    if (offset + 18 > static_cast<int>(len)) {
      break;
    }

    uint8_t msg[18];
    memcpy(msg, &recvData[offset], 18);
    if (decodeBresser6In1Full(msg, 18)) {
      return true;
    }
  }
  return false;
}


// ----------------- Radio / decode task (Core 1, optional) ------------------
// If you want, you can move your CC1101 receive/decoding into this task
// ----------------- Radio / decode task (Core 1) ------------------
void RadioTask(void *pvParameters) {
  uint8_t buf[27];

    for (;;) {

        // Non-blocking receive
    int state = radio.receive(buf, sizeof(buf));

        if (state == RADIOLIB_ERR_NONE) {
      autoFindBresserSliceNoID(buf, sizeof(buf));
    } else if (state != RADIOLIB_ERR_RX_TIMEOUT) {
      logMsg("[CC1101] Receive failed: " + String(state));
        }

        // Yield to keep system responsive
        vTaskDelay(1);
    }
}

// ----------------- Setup ------------------
void setup() {
  Serial.begin(115200);
  delay(200);

  // ---------------- WiFi ----------------
  setup_wifi();

  // ---------------- SPIFFS + Web Files ----------------
  if (!SPIFFS.begin(true)) {
    Serial.println("SPIFFS mount failed");
  } else {
    installWebFiles();   // auto-install index.html + gauge.min.js
  }

  // ---------------- OTA ----------------
  ArduinoOTA.setHostname("bresser-6in1");
  ArduinoOTA.begin();
  Serial.println("OTA ready");

  // ---------------- CC1101 Radio Init ----------------
  int state = radio.begin(917.0, 8.22, 57.136417, 270.0, 10, 32);
  if (state != RADIOLIB_ERR_NONE) {
    logMsg("[CC1101] Init failed: " + String(state));
    while (true) {
      delay(1000);
    }
  }

  radio.setCrcFiltering(false);
  radio.fixedPacketLengthMode(27);
  radio.setSyncWord(0xAA, 0x2D, 0, false);
  logMsg("[CC1101] Initialized");

  // ---------------- Web Routes ----------------
  server.on("/", handleRoot);
  server.on("/gauge.min.js", handleGaugeJs);
  server.on("/data", handleData);

  server.begin();
  Serial.println("Web server started on port 80");

  // ---------------- Web Server Task (Core 0) ----------------
  xTaskCreatePinnedToCore(
    WebServerTask,
    "WebServerTask",
    4096,
    NULL,
    1,
    NULL,
    0   // Core 0
  );

  // ---------------- Radio Task (Core 1) ----------------
  xTaskCreatePinnedToCore(
    RadioTask,
    "RadioTask",
    4096,
    NULL,
    1,
    NULL,
    1   // Core 1
  );
}


// ----------------- Loop ------------------
void loop() {
  // Keep loop light; heavy work is in tasks
  ArduinoOTA.handle();
  tryCloudUpload();

  // If you don't use RadioTask, you can put your radio loop here instead.
}

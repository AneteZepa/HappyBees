# HappyBees System Architecture

## 1. Overview

HappyBees is a distributed IoT system for real-time beehive monitoring using edge machine learning. The system captures acoustic data from beehives, processes it on-device using a trained neural network, and reports results to a central server for visualization and alerting.

### 1.1 Design Goals

1. **Edge-first processing**: Run ML inference on the microcontroller to minimize bandwidth and latency
2. **Low power operation**: Support battery-powered deployment in remote apiaries
3. **Robust connectivity**: Handle intermittent WiFi with local buffering
4. **Accurate detection**: Identify swarming/piping events before colony loss
5. **Simple deployment**: Single binary firmware, containerized backend

### 1.2 High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              HAPPYBEES SYSTEM                              │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│   ┌─────────────────┐          HTTP/JSON           ┌──────────────────┐    │
│   │   EDGE NODE     │ ────────────────────────────>│  CENTRAL SERVER  │    │
│   │  (Pico 2 W)     │<──────────────────────────── │    (FastAPI)     │    │
│   └────────┬────────┘       Command Polling        └────────┬─────────┘    │
│            │                                                │              │
│   ┌────────┴────────┐                              ┌────────┴─────────┐    │
│   │    SENSORS      │                              │    TIMESCALEDB   │    │
│   │  - MEMS Mic     │                              │  (Time-series)   │    │
│   │  - SHT20 T/H    │                              └────────┬─────────┘    │
│   └─────────────────┘                                       │              │
│                                                    ┌────────┴─────────┐    │
│                                                    │    DASHBOARD     │    │
│                                                    │     (Dash)       │    │
│                                                    └──────────────────┘    │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Architecture

### 2.1 Edge Node (Firmware)

The edge node runs on a Raspberry Pi Pico 2 W (RP2350 + CYW43439 WiFi). We chose this platform for several reasons:

**Why RP2350 (Pico 2 W)?**
- 520KB SRAM: Sufficient for 192KB audio buffer + ML inference
- Dual-core ARM Cortex-M33: Adequate compute for real-time DSP
- Native WiFi: CYW43439 with lwIP stack
- Low cost: ~$6 USD at volume
- Wide availability and community support
- PIO for precise timing (future I2S microphone support)

**Why not ESP32?**
- ESP32 has only 320KB SRAM, insufficient for our 192KB audio buffer plus inference overhead
- ESP32-S3 would work but has less community tooling for ML deployment
- Pico SDK is cleaner and better documented than ESP-IDF

**Component Diagram:**

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           PICO 2 W FIRMWARE                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌───────────┐ │
│  │   SERIAL    │    │    WiFi     │    │   FLASH     │    │  SENSORS  │ │
│  │  INTERFACE  │    │   CLIENT    │    │   CONFIG    │    │  DRIVER   │ │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └─────┬─────┘ │
│         │                  │                  │                 │       │
│         └────────┬─────────┴────────┬─────────┴────────┬────────┘       │
│                  │                  │                  │                │
│                  ▼                  ▼                  ▼                │
│         ┌────────────────────────────────────────────────────────┐      │
│         │                   MAIN LOOP                            │      │
│         │  - Parse serial commands                               │      │
│         │  - Poll server for commands                            │      │
│         │  - Execute background sampling                         │      │
│         └────────────────────────────────────────────────────────┘      │
│                                    │                                    │
│                                    ▼                                    │
│         ┌────────────────────────────────────────────────────────┐      │
│         │                 AUDIO PIPELINE                         │      │
│         │                                                        │      │
│         │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │      │
│         │  │   ADC    │─>│   DMA    │─>│   DSP    │─>│  FFT   │  │      │
│         │  │ Capture  │  │  Buffer  │  │ Filters  │  │Extract │  │      │
│         │  └──────────┘  └──────────┘  └──────────┘  └────────┘  │      │
│         │                                                        │      │
│         └────────────────────────────────────────────────────────┘      │
│                                    │                                    │
│                                    ▼                                    │
│         ┌────────────────────────────────────────────────────────┐      │
│         │                 ML INFERENCE                           │      │
│         │                                                        │      │
│         │  ┌──────────┐  ┌──────────┐  ┌──────────┐              │      │
│         │  │ Feature  │─>│ TFLite   │─>│  Result  │              │      │
│         │  │  Vector  │  │ Interp.  │  │ Handler  │              │      │
│         │  └──────────┘  └──────────┘  └──────────┘              │      │
│         │                                                        │      │
│         └────────────────────────────────────────────────────────┘      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Backend Server

**Why FastAPI?**
- Async-native: Handles concurrent device connections efficiently
- Automatic OpenAPI docs: Self-documenting API
- Pydantic validation: Type-safe request/response handling
- Python ecosystem: Easy integration with data science tools

**Why TimescaleDB?**
- PostgreSQL compatibility: Familiar SQL, robust ecosystem
- Hypertables: Automatic time-based partitioning for telemetry
- Compression: 10-20x storage reduction for time-series data
- Continuous aggregates: Pre-computed rollups for dashboard queries

**Alternative considered**: InfluxDB
- Rejected because: Less familiar query language, weaker ecosystem, licensing concerns

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            BACKEND SERVER                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                         FastAPI App                             │    │
│  ├─────────────────────────────────────────────────────────────────┤    │
│  │                                                                 │    │
│  │   ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐    │    │
│  │   │/telemetry │  │/inference │  │ /commands │  │   /logs   │    │    │
│  │   │           │  │           │  │           │  │           │    │    │
│  │   │ POST: add │  │ POST: add │  │ POST: add │  │ POST: add │    │    │
│  │   │ GET: list │  │ GET: last │  │ GET: pend │  │ GET: list │    │    │
│  │   └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘    │    │
│  │         │              │              │              │          │    │
│  │         └──────────────┴──────────────┴──────────────┘          │    │
│  │                                │                                │    │
│  │                                ▼                                │    │
│  │                    ┌───────────────────────┐                    │    │
│  │                    │   SQLAlchemy Async    │                    │    │
│  │                    │   Session Manager     │                    │    │
│  │                    └───────────┬───────────┘                    │    │
│  │                                │                                │    │
│  └────────────────────────────────┼────────────────────────────────┘    │
│                                   │                                     │
│                                   ▼                                     │
│                    ┌─────────────────────────────┐                      │
│                    │        TimescaleDB          │                      │
│                    ├─────────────────────────────┤                      │
│                    │  telemetry (hypertable)     │                      │
│                    │  inference_results (hyper)  │                      │
│                    │  commands                   │                      │
│                    │  device_logs                │                      │
│                    │  nodes                      │                      │
│                    └─────────────────────────────┘                      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Dashboard

**Why Dash/Plotly?**
- Python-native: Single language for backend and frontend
- Real-time capable: Interval-based updates without WebSocket complexity
- Interactive charts: Plotly provides rich visualization out of the box
- Rapid development: No need for separate React/Vue frontend

**Alternative considered**: Grafana
- Rejected because: Adds deployment complexity, less customizable UI, separate auth system

---

## 3. Data Flow

### 3.1 Telemetry Upload Sequence

```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│   Pico   │          │  FastAPI │          │Timescale │          │Dashboard │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │  POST /telemetry/   │                     │                     │
     │  {node_id, temp,    │                     │                     │
     │   humidity, ...}    │                     │                     │
     │────────────────────>│                     │                     │
     │                     │                     │                     │
     │                     │  INSERT INTO        │                     │
     │                     │  telemetry          │                     │
     │                     │────────────────────>│                     │
     │                     │                     │                     │
     │                     │  OK                 │                     │
     │                     │<────────────────────│                     │
     │                     │                     │                     │
     │  {"status": "ok"}   │                     │                     │
     │<────────────────────│                     │                     │
     │                     │                     │                     │
     │                     │                     │  GET /telemetry/    │
     │                     │                     │  (every 2s)         │
     │                     │<──────────────────────────────────────────│
     │                     │                     │                     │
     │                     │  SELECT FROM        │                     │
     │                     │  telemetry          │                     │
     │                     │────────────────────>│                     │
     │                     │                     │                     │
     │                     │  [rows]             │                     │
     │                     │<────────────────────│                     │
     │                     │                     │                     │
     │                     │  JSON response      │                     │
     │                     │──────────────────────────────────────────>│
     │                     │                     │                     │
```

### 3.2 Command Queue Pattern

We use a pull-based command queue rather than push-based WebSockets for several reasons:

**Why polling instead of WebSockets?**
1. Simpler firmware: lwIP's WebSocket support is limited
2. NAT traversal: Polling works through firewalls without port forwarding
3. Power efficiency: Device can sleep between polls
4. Reliability: No persistent connection to maintain

**Trade-off**: 2-second latency for commands (acceptable for our use case)

```
┌──────────┐          ┌──────────┐          ┌──────────┐          ┌──────────┐
│   User   │          │Dashboard │          │  FastAPI │          │   Pico   │
└────┬─────┘          └────┬─────┘          └────┬─────┘          └────┬─────┘
     │                     │                     │                     │
     │  Click "Run         │                     │                     │
     │  Inference"         │                     │                     │
     │────────────────────>│                     │                     │
     │                     │                     │                     │
     │                     │  POST /commands/    │                     │
     │                     │  {node_id,          │                     │
     │                     │   type: RUN_INFER}  │                     │
     │                     │────────────────────>│                     │
     │                     │                     │                     │
     │                     │                     │ (stored as pending) │
     │                     │                     │                     │
     │                     │                     │  GET /commands/     │
     │                     │                     │  pending            │
     │                     │                     │  (every 2s)         │
     │                     │                     │<────────────────────│
     │                     │                     │                     │
     │                     │                     │  [{type: RUN_INFER}]│
     │                     │                     │────────────────────>│
     │                     │                     │                     │
     │                     │                     │                     │ Execute
     │                     │                     │                     │ locally
     │                     │                     │                     │
     │                     │                     │  POST /inference/   │
     │                     │                     │  {result: Normal}   │
     │                     │                     │<────────────────────│
     │                     │                     │                     │
```

---

## 4. DSP Pipeline Design

### 4.1 Signal Flow

```
┌───────────────────────────────────────────────────────────────────────────┐
│                            DSP PIPELINE                                   │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │
│  │ SPW2430 │    │  Op-Amp │    │   ADC   │    │   DMA   │    │  Buffer │  │
│  │   Mic   │───>│  x22    │───>│  12-bit │───>│ Transfer│───>│  96000  │  │
│  │         │    │ TLC272  │    │         │    │         │    │ samples │  │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘    └────┬────┘  │
│                                                                   │       │
│       ┌───────────────────────────────────────────────────────────┘       │
│       │                                                                   │
│       ▼                                                                   │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │
│  │   DC    │    │  Gain   │    │Highpass │    │ Lowpass │    │   FFT   │  │
│  │ Removal │───>│  Comp   │───>│  100Hz  │───>│  6kHz   │───>│  512pt  │  │
│  │ -2048   │    │  x0.35  │    │  2nd    │    │  3rd    │    │ Hanning │  │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘    └────┬────┘  │
│                                                                   │       │
│       ┌───────────────────────────────────────────────────────────┘       │
│       │                                                                   │
│       ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                     FEATURE EXTRACTION                              │  │
│  │                                                                     │  │
│  │   Average 187 FFT windows -> Extract bins 4-19 (125-594 Hz)         │  │
│  │   Calculate RMS density -> Compute spike ratio vs history           │  │
│  │                                                                     │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Design Decisions

**Why 16kHz sample rate?**
- Nyquist frequency of 8kHz covers bee acoustic range (100-600 Hz with harmonics)
- Lower than typical audio (44.1kHz) to reduce memory and compute requirements
- Matches Edge Impulse training data

**Why 6-second capture?**
- Long enough to capture cyclical piping patterns (~1-2 second cycles)
- Short enough for responsive detection
- Produces 187 FFT windows for robust averaging

**Why DMA-based capture?**
- CPU-free data transfer from ADC to memory
- Consistent timing without interrupt jitter
- Enables simultaneous processing if needed

**Why Butterworth filters?**
- Maximally flat passband (no ripple)
- Predictable phase response
- Easy to implement as biquad cascade

**Why gain compensation?**
- Op-amp provides ~22x voltage gain for weak microphone signal
- This produces ADC values 3-4x higher than Mac training data
- Gain compensation (0.35) normalizes to training distribution
- Calibratable per-device via serial command

---

## 5. ML Model Architecture

### 5.1 Model Design

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         SUMMER MODEL (TFLite)                              │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│   INPUT LAYER (20 features)                                                │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │ [temp, humidity, hour, spike_ratio, bin4, bin5, ... bin19]         │   │
│   └────────────────────────────────────────────────────────────────────┘   │
│                                    │                                       │
│                                    ▼                                       │
│   DENSE LAYER 1 (64 units, ReLU)                                           │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │ ████████████████████████████████████████████████████████████████   │   │
│   └────────────────────────────────────────────────────────────────────┘   │
│                                    │                                       │
│                                    ▼                                       │
│   DENSE LAYER 2 (32 units, ReLU)                                           │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │ ████████████████████████████████                                   │   │
│   └────────────────────────────────────────────────────────────────────┘   │
│                                    │                                       │
│                                    ▼                                       │
│   OUTPUT LAYER (2 units, Softmax)                                          │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │ [Normal probability, Event probability]                            │   │
│   └────────────────────────────────────────────────────────────────────┘   │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Feature Importance Discovery

Through systematic testing, we discovered the model's actual behavior:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        FEATURE SENSITIVITY                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   SPIKE RATIO (f[3])                                                        │
│   ████████████████████████████████████████████████████  95% impact          │
│                                                                             │
│   HOUR (f[2])                                                               │
│   ████                                                   3% impact          │
│                                                                             │
│   TEMPERATURE (f[0])                                                        │
│   █                                                      1% impact          │
│                                                                             │
│   HUMIDITY (f[1])                                                           │
│   █                                                      <1% impact         │
│                                                                             │
│   FFT BINS (f[4-19])                                                        │
│                                                          <1% impact         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key insight**: The model was trained to detect changes in acoustic activity, not absolute sound levels. The spike ratio (current energy / rolling average) is the primary feature.

**Implications**:
1. Fresh boot always predicts "Event" (spike = 1.0, no history)
2. Need 5-12 readings to build meaningful history
3. FFT magnitude calibration matters less than we initially thought
4. Background sampling is essential for production deployment

---

## 6. Database Schema

### 6.1 Entity Relationship Diagram

```
┌───────────────────────────────────────────────────────────────────────────┐
│                           DATABASE SCHEMA                                 │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   ┌─────────────────┐                                                     │
│   │      nodes      │                                                     │
│   ├─────────────────┤                                                     │
│   │ node_id (PK)    │◄─────────────────────────────────────────────┐      │
│   │ name            │                                              │      │
│   │ firmware_version│                                              │      │
│   │ last_seen_at    │                                              │      │
│   │ is_active       │                                              │      │
│   └─────────────────┘                                              │      │
│                                                                    │      │
│   ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐   │
│   │    telemetry    │      │inference_results│      │    commands     │   │
│   │  (hypertable)   │      │  (hypertable)   │      │                 │   │
│   ├─────────────────┤      ├─────────────────┤      ├─────────────────┤   │
│   │ time (PK)       │      │ time (PK)       │      │ command_id (PK) │   │
│   │ node_id (PK,FK) │──────│ node_id (PK,FK) │──────│ node_id (FK)    │───┤
│   │ temperature_c   │      │ model_type      │      │ command_type    │   │
│   │ humidity_pct    │      │ classification  │      │ params (JSONB)  │   │
│   │ battery_mv      │      │ confidence      │      │ status          │   │
│   │ rssi_dbm        │      │ anomaly_score   │      │ created_at      │   │
│   │ error_flags     │      │ raw_outputs     │      │ sent_at         │   │
│   └─────────────────┘      └─────────────────┘      │ completed_at    │   │
│                                                     └─────────────────┘   │
│                                                                           │
│   ┌─────────────────┐                                                     │
│   │   device_logs   │                                                     │
│   ├─────────────────┤                                                     │
│   │ log_id (PK)     │                                                     │
│   │ node_id (FK)    │─────────────────────────────────────────────────────┘
│   │ message         │                                                     │
│   │ created_at      │                                                     │
│   └─────────────────┘                                                     │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Hypertable Design

Telemetry and inference_results use TimescaleDB hypertables for efficient time-series storage:

```sql
-- Automatic partitioning by time (7-day chunks)
SELECT create_hypertable('telemetry', 'time', 
    chunk_time_interval => INTERVAL '7 days');

-- Compression policy (compress chunks older than 7 days)
ALTER TABLE telemetry SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'node_id'
);

SELECT add_compression_policy('telemetry', INTERVAL '7 days');

-- Retention policy (drop data older than 1 year)
SELECT add_retention_policy('telemetry', INTERVAL '1 year');
```

---

## 7. Security Considerations

### 7.1 Current State (Development)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     CURRENT SECURITY MODEL                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────┐         HTTP (plaintext)          ┌─────────────┐             │
│   │  Pico   │ ─────────────────────────────────>│   Server    │             │
│   └─────────┘         No authentication         └─────────────┘             │
│                                                                             │
│   Assumptions:                                                              │
│   - Local network only                                                      │
│   - Trusted environment                                                     │
│   - Development/testing use                                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Production Recommendations

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   RECOMMENDED SECURITY MODEL                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────┐         HTTPS (TLS 1.3)           ┌─────────────┐             │
│   │  Pico   │ ─────────────────────────────────>│   Server    │             │
│   │(mbedtls)│         + API Key Header          │  (nginx)    │             │
│   └─────────┘                                   └─────────────┘             │
│                                                                             │
│   Implementation:                                                           │
│   1. Enable mbedtls in firmware for TLS                                     │
│   2. Generate per-device API keys during provisioning                       │
│   3. Store API key in flash alongside WiFi credentials                      │
│   4. Backend validates X-API-Key header on all requests                     │
│   5. Use nginx reverse proxy for TLS termination                            │
│   6. Rate limit by API key (prevent DoS)                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Deployment Architecture

### 8.1 Container Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CONTAINER DEPLOYMENT                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Host Machine (podman-compose)                                             │
│   ┌────────────────────────────────────────────────────────────────────┐    │
│   │                                                                    │    │
│   │   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐  │    │
│   │   │   timescaledb   │   │     backend     │   │    dashboard    │  │    │
│   │   │                 │   │                 │   │                 │  │    │
│   │   │  PostgreSQL 16  │   │    FastAPI      │   │      Dash       │  │    │
│   │   │  + TimescaleDB  │   │    Uvicorn      │   │                 │  │    │
│   │   │                 │   │                 │   │                 │  │    │
│   │   │    Port 5432    │   │    Port 8000    │   │    Port 8050    │  │    │
│   │   └────────┬────────┘   └────────┬────────┘   └────────┬────────┘  │    │
│   │            │                     │                     │           │    │
│   │            │      postgresql://  │       http://       │           │    │
│   │            └─────────────────────┘                     │           │    │
│   │                                                        │           │    │
│   │   ┌────────────────────────────────────────────────────┘           │    │
│   │   │ http://backend:8000/api/v1                                     │    │
│   │   │                                                                │    │
│   └───┼────────────────────────────────────────────────────────────────┘    │
│       │                                                                     │
│   ────┴────────────────────────────────────────────────────────────────     │
│        Volume: happybees_pgdata (persistent database storage)               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Scaling Considerations

For multi-hive deployments:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SCALED DEPLOYMENT                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────┐  ┌──────┐  ┌──────┐                                              │
│   │Hive 1│  │Hive 2│  │Hive N│    Edge Nodes (N devices)                    │
│   └──┬───┘  └──┬───┘  └──┬───┘                                              │
│      │         │         │                                                  │
│      └─────────┼─────────┘                                                  │
│                │                                                            │
│                ▼                                                            │
│   ┌─────────────────────────┐                                               │
│   │      Load Balancer      │   (nginx, HAProxy, or cloud LB)               │
│   └────────────┬────────────┘                                               │
│                │                                                            │
│      ┌─────────┼─────────┐                                                  │
│      │         │         │                                                  │
│      ▼         ▼         ▼                                                  │
│   ┌──────┐  ┌──────┐  ┌──────┐                                              │
│   │API 1 │  │API 2 │  │API 3 │   Backend replicas (stateless)               │
│   └──┬───┘  └──┬───┘  └──┬───┘                                              │
│      │         │         │                                                  │
│      └─────────┼─────────┘                                                  │
│                │                                                            │
│                ▼                                                            │
│   ┌─────────────────────────┐                                               │
│   │  TimescaleDB (Primary)  │   Single writer, read replicas optional       │
│   └─────────────────────────┘                                               │
│                                                                             │
│   Capacity: ~1000 devices with single backend instance                      │
│   Bottleneck: Database write throughput (~10k inserts/sec)                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Error Handling Strategy

### 9.1 Firmware Error Handling

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      FIRMWARE ERROR HANDLING                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Error Type          │ Handling Strategy              │ Recovery           │
│   ────────────────────┼────────────────────────────────┼──────────────────  │
│   WiFi disconnect     │ Retry with exponential backoff │ Auto-reconnect     │
│   HTTP timeout        │ Log locally, retry next cycle  │ Continue sampling  │
│   Sensor failure      │ Set error flag, use mock data  │ Alert via log      │
│   ADC overflow        │ Clip values, log warning       │ Continue           │
│   Flash write fail    │ Retry once, then skip          │ Use RAM config     │
│   ML inference fail   │ Report error, skip result      │ Continue sampling  │
│   Watchdog timeout    │ (Future) System reset          │ Auto-restart       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 9.2 Backend Error Handling

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       BACKEND ERROR HANDLING                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Error Type          │ HTTP Status │ Response                              │
│   ────────────────────┼─────────────┼────────────────────────────────────   │
│   Invalid JSON        │ 422         │ Pydantic validation error details     │
│   Unknown node_id     │ 200         │ Auto-register node, proceed           │
│   Database timeout    │ 503         │ {"error": "database unavailable"}     │
│   Rate limit exceeded │ 429         │ {"error": "too many requests"}        │
│   Internal error      │ 500         │ {"error": "internal server error"}    │
│                                                                             │
│   Design decision: Auto-register unknown nodes to simplify provisioning     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Future Roadmap

### 10.1 Planned Enhancements

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ROADMAP                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Phase 1 (Current)                                                         │
│   ✓ Basic telemetry and inference                                           │
│   ✓ Serial configuration                                                    │
│   ✓ Dashboard visualization                                                 │
│   ✓ Command queue                                                           │
│                                                                             │
│   Phase 2 (Next)                                                            │
│   ○ Deep sleep mode for battery operation                                   │
│   ○ OTA firmware updates                                                    │
│   ○ HTTPS/TLS with mbedtls                                                  │
│   ○ Multi-node dashboard view                                               │
│                                                                             │
│   Phase 3 (Future)                                                          │
│   ○ I2S microphone support (better audio quality)                           │
│   ○ LoRa connectivity for remote apiaries                                   │
│   ○ Mobile app for configuration                                            │
│   ○ Swarm prediction (not just detection)                                   │
│   ○ Integration with hive scale data                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. References

- [Raspberry Pi Pico 2 W Datasheet](https://datasheets.raspberrypi.com/picow/pico-w-datasheet.pdf)
- [Edge Impulse Documentation](https://docs.edgeimpulse.com/)
- [TimescaleDB Documentation](https://docs.timescale.com/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [lwIP Documentation](https://www.nongnu.org/lwip/2_1_x/index.html)

---

Document Version: 1.0
Last Updated: November 2025

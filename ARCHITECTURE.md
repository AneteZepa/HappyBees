# BeeWatch System Architecture

## Overview

BeeWatch is a distributed IoT system for monitoring beehives using acoustic analysis and environmental sensors. The architecture follows a star topology with edge devices reporting to a central server.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           BEEWATCH ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│    ┌──────────────┐         WiFi/HTTP          ┌──────────────────────┐    │
│    │  HIVE NODE   │ ◄─────────────────────────► │    CENTRAL SERVER    │    │
│    │  (Pico 2 W)  │                             │    (FastAPI)         │    │
│    └──────────────┘                             └──────────────────────┘    │
│          │                                               │                   │
│          │                                               │                   │
│    ┌─────▼─────┐                                   ┌─────▼─────┐            │
│    │  SENSORS  │                                   │  DATABASE │            │
│    │  SHT20    │                                   │ TimescaleDB│           │
│    │  MEMS Mic │                                   └───────────┘            │
│    └───────────┘                                         │                   │
│                                                          │                   │
│                                                    ┌─────▼─────┐            │
│                                                    │ DASHBOARD │            │
│                                                    │   (Dash)  │            │
│                                                    └───────────┘            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Edge Node (Pico 2 W)

**Hardware:**
- Raspberry Pi Pico 2 W (RP2350 + CYW43439 WiFi)
- MEMS Microphone (INMP441 or similar)
- TLC272CP Op-Amp (22x gain)
- SHT20 Temperature/Humidity Sensor

**Firmware Features:**
- DMA-based audio capture at 16kHz
- Real-time DSP (HP/LP filters, FFT)
- On-device ML inference (Edge Impulse TFLite)
- WiFi connectivity with command polling
- Flash-based configuration storage

**Data Flow:**
```
Microphone → ADC → DMA Buffer → DSP Pipeline → Feature Extraction → ML Inference → HTTP Upload
```

### 2. Backend Server (FastAPI)

**Endpoints:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/telemetry/` | POST | Store sensor readings |
| `/api/v1/telemetry/` | GET | Retrieve history |
| `/api/v1/inference/` | POST | Store ML results |
| `/api/v1/inference/latest` | GET | Get latest prediction |
| `/api/v1/commands/` | POST | Queue command for device |
| `/api/v1/commands/pending` | GET | Get pending commands |
| `/api/v1/logs/` | POST/GET | Device logging |

**Database (TimescaleDB):**
- `telemetry` - Time-series sensor data (hypertable)
- `inference_results` - ML predictions (hypertable)
- `commands` - Command queue
- `device_logs` - Device messages
- `nodes` - Device registry

### 3. Dashboard (Dash/Plotly)

**Features:**
- Real-time temperature/humidity graphs
- Command transmission panel
- Live device log terminal
- Retro-futuristic UI theme

---

## Communication Protocol

### Command Queue Pattern

The Pico polls the server every 2 seconds for pending commands:

```
┌──────────┐                    ┌──────────┐                    ┌──────────┐
│   USER   │                    │  SERVER  │                    │   PICO   │
└────┬─────┘                    └────┬─────┘                    └────┬─────┘
     │                               │                               │
     │ Click "Run Inference"         │                               │
     │──────────────────────────────►│                               │
     │                               │                               │
     │                               │ INSERT INTO commands          │
     │                               │ (status='pending')            │
     │                               │                               │
     │                               │◄──────────────────────────────│
     │                               │ GET /commands/pending         │
     │                               │                               │
     │                               │──────────────────────────────►│
     │                               │ JSON: [{type: RUN_INFERENCE}] │
     │                               │                               │
     │                               │                               │ Execute
     │                               │                               │ locally
     │                               │                               │
     │                               │◄──────────────────────────────│
     │                               │ POST /inference/              │
     │                               │ {classification: "Normal"}    │
     │                               │                               │
     │◄──────────────────────────────│                               │
     │ Dashboard updates             │                               │
     │                               │                               │
```

### JSON Payloads

**Telemetry:**
```json
{
    "node_id": "pico-hive-001",
    "timestamp": "2025-11-29T10:00:00Z",
    "temperature_c": 21.5,
    "humidity_pct": 45.0,
    "battery_mv": 4200,
    "error_flags": 0
}
```

**Inference Result:**
```json
{
    "node_id": "pico-hive-001",
    "model_type": "summer",
    "classification": "Normal",
    "confidence": 0.985,
    "timestamp": "2025-11-29T10:00:00Z"
}
```

**Command:**
```json
{
    "node_id": "pico-hive-001",
    "command_type": "RUN_INFERENCE",
    "params": {"model": "summer"}
}
```

---

## Firmware State Machine

```
                                    ┌─────────────┐
                                    │   STARTUP   │
                                    └──────┬──────┘
                                           │
                                           ▼
                                    ┌─────────────┐
                                    │ WIFI_CONNECT│
                                    └──────┬──────┘
                                           │
                 ┌─────────────────────────┼─────────────────────────┐
                 │                         │                         │
                 ▼                         ▼                         ▼
          ┌─────────────┐          ┌─────────────┐          ┌─────────────┐
          │  POLL_NET   │◄────────►│ PARSE_SERIAL│◄────────►│  BACKGROUND │
          └──────┬──────┘          └──────┬──────┘          │   SAMPLE    │
                 │                         │                 └─────────────┘
                 └────────────┬────────────┘
                              │
                              ▼
                       ┌─────────────┐
                       │  CMD_QUEUE  │
                       └──────┬──────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
       ┌───────────┐   ┌───────────┐   ┌───────────┐
       │  CAPTURE  │   │   READ    │   │   PING    │
       │   AUDIO   │   │  CLIMATE  │   │           │
       └─────┬─────┘   └───────────┘   └───────────┘
             │
             ▼
       ┌───────────┐
       │    DSP    │
       │ PROCESSING│
       └─────┬─────┘
             │
             ▼
       ┌───────────┐
       │    ML     │
       │ INFERENCE │
       └─────┬─────┘
             │
             ▼
       ┌───────────┐
       │   UPLOAD  │
       │  RESULTS  │
       └───────────┘
```

---

## Deployment Options

### Option 1: Local Development

```bash
# Terminal 1: Database
podman run -d -p 5432:5432 \
    -e POSTGRES_PASSWORD=beewatch_dev \
    timescale/timescaledb:latest-pg16

# Terminal 2: Backend
cd backend && uv run uvicorn app.main:app --reload

# Terminal 3: Dashboard
cd backend && uv run python -m dashboard.app --node pico-hive-001
```

### Option 2: Container Compose

```bash
podman-compose up -d
```

### Option 3: Cloud Deployment

- Deploy TimescaleDB to managed service (Timescale Cloud, AWS RDS)
- Deploy backend to container platform (Fly.io, Railway, AWS ECS)
- Configure firewall to allow Pico connections

---

## Security Considerations

### Current (Development)
- Plain HTTP communication
- No authentication
- Local network only

### Production Recommendations
1. **Enable HTTPS/TLS** - Use mbedtls on Pico
2. **Add API authentication** - JWT or API keys
3. **Network segmentation** - IoT VLAN
4. **Rate limiting** - Prevent DoS
5. **Input validation** - Sanitize all inputs

---

## Performance Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| Audio capture | 6 seconds | 96,000 samples |
| DSP processing | ~500ms | 187 FFT windows |
| ML inference | ~50ms | TFLite quantized |
| Total cycle | ~8 seconds | Including upload |
| Idle power | ~40mA | WiFi polling active |
| Peak power | ~120mA | During transmission |

---

## Extensibility

### Adding New Sensors
1. Add I2C/SPI driver in firmware
2. Extend telemetry schema
3. Update dashboard display

### Adding New ML Models
1. Train in Edge Impulse
2. Export C++ library
3. Add to firmware as new model slot
4. Add API model_type parameter

### Multi-Node Support
1. Each Pico has unique node_id
2. Server already supports multiple nodes
3. Dashboard can filter by node_id
4. Future: multi-node overview page

---

*Document Version: 1.0*
*Last Updated: November 2025*

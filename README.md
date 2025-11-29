# HappyBees: Distributed IoT Beehive Monitoring System

<p align="center">
  <img src="assets/beewatch_logo.png" alt="BeeWatch Logo" width="200">
</p>

**HappyBees** is a distributed acoustic monitoring system for beehives. It uses edge ML on a Raspberry Pi Pico 2 W to detect swarming events and uploads telemetry to a central server with a real-time dashboard.

##  Features

- **On-device ML inference** using Edge Impulse TFLite models
- **Acoustic analysis** with configurable DSP pipeline
- **Environmental monitoring** (temperature, humidity via SHT20)
- **WiFi connectivity** with command queue polling
- **Real-time dashboard** with retro-futuristic UI
- **Mock device mode** for development without hardware

##  Project Structure

```
beewatch/
├── firmware/                    # Pico 2 W firmware (C++)
│   ├── source/
│   │   ├── main.cpp            # Main application
│   │   ├── config.h            # Hardware configuration
│   │   ├── flash_config.h      # WiFi credential storage
│   │   └── lwipopts.h          # TCP/IP stack config
│   ├── mode_summer/            # Summer ML model (Edge Impulse)
│   ├── model_winter/           # Winter ML model (Edge Impulse)
│   ├── edge-impulse-sdk/       # Edge Impulse SDK
│   └── CMakeLists.txt          # Build configuration
│
├── backend/                     # Python backend server
│   ├── app/
│   │   ├── main.py             # FastAPI entry point
│   │   ├── database.py         # TimescaleDB connection
│   │   ├── models.py           # SQLAlchemy models
│   │   ├── schemas.py          # Pydantic schemas
│   │   └── api/                # REST endpoints
│   │       ├── telemetry.py
│   │       ├── inference.py
│   │       ├── commands.py
│   │       └── logs.py
│   ├── dashboard/
│   │   └── app.py              # Dash frontend
│   ├── scripts/
│   │   ├── mock_stream.py      # Mock device simulator
│   │   └── configure_device.py # WiFi provisioning
│   └── assets/                 # CSS, fonts, images
│
├── tools/                       # Diagnostic utilities
│   ├── mac_shim.py             # Reference ML implementation
│   ├── audio_capture.py        # Pico audio streaming
│   ├── parity_diagnostic.py    # DSP verification
│   └── test_features.py        # Direct model testing
│
├── docs/                        # Documentation
│   ├── ML_MODEL_GUIDE.md       # Deep dive on the ML model
│   └── ARCHITECTURE.md         # System architecture
│
├── podman-compose.yml          # Container orchestration
├── Containerfile.backend       # Backend container
└── README.md                   # This file
```

---

##  Quick Start

### Prerequisites

- **Python 3.11+** with `uv` package manager
- **Podman** or Docker (for database)
- **Pico SDK 2.0+** (for firmware development)
- **CMake 3.20+** and ARM GCC toolchain

### 1. Start the Database

```bash
# Start TimescaleDB
podman-compose up -d timescaledb

# Verify it's running
podman ps
```

### 2. Start the Backend Server

```bash
cd backend

# Create virtual environment and install deps
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Start the API server
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Start the Dashboard

```bash
# In a new terminal, from backend/
source .venv/bin/activate
uv run python -m dashboard.app --node pico-hive-001

# Open browser to http://localhost:8050
```

### 4. Connect a Device

**Option A: Real Pico Hardware**

```bash
# Build and flash firmware (see Firmware section)
# Configure WiFi credentials via serial:
tio -b 115200 /dev/tty.usbmodem*

> wifi YOUR_SSID YOUR_PASSWORD
> server YOUR_SERVER_IP
```

**Option B: Mock Device (for development)**

```bash
cd backend
uv run python scripts/mock_stream.py --node pico-hive-001
```

---

##  Firmware Development

### Building the Firmware

```bash
cd firmware

# Set Pico SDK path
export PICO_SDK_PATH=/path/to/pico-sdk

# Build
mkdir build && cd build
cmake .. -DPICO_BOARD=pico2_w
make -j4

# Flash (hold BOOTSEL, plug in USB)
cp beewatch_firmware.uf2 /Volumes/RP2350/
```

### Serial Console Commands

| Command | Description |
|---------|-------------|
| `s` | Run Summer model inference |
| `w` | Run Winter model inference |
| `t` | Read temperature/humidity |
| `a` | Stream raw audio to PC |
| `m` | Toggle mock sensor mode |
| `c` | Clear rolling history |
| `d` | Debug feature dump |
| `p` | Ping (connectivity test) |
| `g0.35` | Set gain compensation |
| `wifi SSID PASS` | Configure WiFi |
| `server IP` | Configure server IP |

### Gain Calibration

The microphone circuit gain affects ML predictions. Calibrate for your hardware:

```bash
tio -b 115200 /dev/tty.usbmodem*

> m          # Enable mock mode
> c          # Clear history
> s          # Run inference, check FFT bins

# Target: Bins[4-7] should be 0.02-0.06 for quiet room
> g0.35      # Adjust gain (lower = smaller bins)
> s          # Test again
```

---

##  Backend API

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/telemetry/` | Store sensor data |
| `GET` | `/api/v1/telemetry/?node_id=X` | Get telemetry history |
| `POST` | `/api/v1/inference/` | Store ML results |
| `GET` | `/api/v1/inference/latest?node_id=X` | Get latest inference |
| `POST` | `/api/v1/commands/` | Queue command for device |
| `GET` | `/api/v1/commands/pending?node_id=X` | Get pending commands |
| `POST` | `/api/v1/logs/` | Store device log |
| `GET` | `/api/v1/logs/?node_id=X` | Get log history |

### Database Schema

```sql
-- TimescaleDB hypertables for time-series data

telemetry (time, node_id, temperature_c, humidity_pct, battery_mv)
inference_results (time, node_id, model_type, classification, confidence)
commands (command_id, node_id, command_type, params, status)
device_logs (log_id, node_id, message, created_at)
nodes (node_id, name, firmware_version, last_seen_at)
```

---

##  Testing & Verification

### Verifying DSP Parity

The `tools/` directory contains utilities to verify firmware matches the reference implementation:

```bash
cd tools

# 1. Capture audio from Pico
python audio_capture.py -d /dev/tty.usbmodem2101 -o pico_audio.wav

# 2. Analyze FFT values
python parity_diagnostic.py pico_audio.wav --find-gain

# 3. Compare with MacOS/Python script reference implementation (i.e. use your Mac's mic to test the model)
python mac_shim.py --model summer --verbose
```

### Direct Model Testing

Test specific feature vectors against the TFLite model:

```bash
cd tools

# Test exact Pico features
python test_features.py

# Sweep all feature sensitivities
python test_humidity.py
```

---

##  ML Model Details

The Summer model detects swarming/piping events. Key characteristics:

- **Input**: 20-element float32 vector
- **Output**: 2 classes (Normal, Event)
- **Primary feature**: Spike ratio (current/rolling audio energy)
- **Frequency range**: 125-594 Hz (bee communication frequencies)

**See [docs/ML_MODEL_GUIDE.md](docs/ML_MODEL_GUIDE.md) for complete technical documentation.**

### Why "Spike Ratio" Matters

The model was trained to detect **changes** in hive activity:

| Spike Ratio | Meaning | Prediction |
|-------------|---------|------------|
| < 0.7 | Activity decreasing | Normal |
| ≈ 1.0 | Steady state | Ambiguous (defaults to Event) |
| > 1.3 | Activity increasing | Event |

A freshly-booted device has no history, so spike = 1.0 → always predicts Event.
After several readings, the rolling average stabilizes and predictions become meaningful.

---

##  Container Deployment

### Using Podman Compose

```bash
# Start all services
podman-compose up -d

# View logs
podman-compose logs -f backend

# Stop all
podman-compose down
```

### Building Images

```bash
# Backend
podman build -t beewatch-backend -f Containerfile.backend .

# Run standalone
podman run -p 8000:8000 beewatch-backend
```

---

##  Hardware Setup

### Bill of Materials

| Component | Part Number | Notes |
|-----------|-------------|-------|
| MCU | Raspberry Pi Pico 2 W | RP2350 + WiFi |
| Microphone | INMP441/SPW2430 or similar | I2S MEMS/Analog mic |
| Op-Amp | TLC272CP | ~22x gain |
| Temp/Humidity | SHT20 | I2C sensor |

### Wiring

```
Mic → Op-Amp (TLC272CP) → Pico GPIO26 (ADC0)
SHT20 SDA → Pico GPIO4
SHT20 SCL → Pico GPIO5
```

---

##  Configuration

### Environment Variables

```bash
# Backend
DATABASE_URL=postgresql+psycopg://postgres:beewatch_dev@localhost:5432/beewatch

# Dashboard
API_URL=http://localhost:8000/api/v1
NODE_ID=pico-hive-001
```

### Firmware Configuration

Edit `firmware/source/config.h`:

```cpp
#define SAMPLE_RATE_HZ       16000
#define CAPTURE_SECONDS      6
#define HISTORY_SIZE         12
#define DEFAULT_GAIN         0.35f
```

---

##  Roadmap

- [ ] **Deep Sleep Mode**: Reduce power from 40mA to μA for battery operation
- [ ] **OTA Updates**: Download firmware updates over WiFi
- [ ] **HTTPS/TLS**: Secure communication with mbedtls
- [ ] **Multi-node Dashboard**: Monitor multiple hives simultaneously
- [ ] **Background Sampling**: Continuous audio monitoring with configurable interval

---

##  Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open a Pull Request

---

##  License

This project is licensed under the BSD 3 License - see [LICENSE](LICENSE) file for details.

Edge Impulse SDK components are subject to Edge Impulse terms of service.

---

##  Acknowledgments

- Edge Impulse for the ML training platform
- Raspberry Pi Foundation for the Pico 2 W
- The beekeeping community for domain expertise

---

*Built with 🐝 by the HappyBees Team*

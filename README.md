# HappyBees: Distributed IoT Beehive Monitoring System

<p align="center">
  <img src="assets/beewatch_logo.png" alt="BeeWatch Logo" width="200">
</p>

HappyBees is a distributed IoT beehive monitoring system. It uses edge ML on a Raspberry Pi Pico 2 W to detect swarming events via acoustic analysis and uploads telemetry to a central server with a real-time dashboard.

## Project Structure

```
happybees/
├── firmware/           # Pico 2 W firmware (C++)
│   ├── source/         # Application code
│   ├── mode_summer/    # Summer ML model (Edge Impulse)
│   ├── model_winter/   # Winter ML model (Edge Impulse)
│   └── edge-impulse-sdk/  # EI SDK 
├── backend/            # Python server and dashboard
│   ├── app/            # FastAPI application
│   ├── dashboard/      # Dash frontend
│   ├── scripts/        # Utilities (mock device, provisioning)
│   └── assets/         # CSS, fonts, images
├── tools/              # Diagnostic and verification utilities
└── docs/               # Technical documentation
```

## Prerequisites

- Python 3.11+ with [uv](https://github.com/astral-sh/uv) package manager
- Podman or Docker (for TimescaleDB)
- Pico SDK 2.0+ (for firmware development)
- CMake 3.20+ and ARM GCC toolchain

## Quick Start

### 1. Clone and Setup Environment

```bash
git clone git@github.com:AneteZepa/HappyBees.git
cd HappyBees

# Create virtual environment and install all dependencies
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
```

### 2. Start the Database

```bash
podman run -d --name happybees-db \
    -p 5432:5432 \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=happybees_dev \
    -e POSTGRES_DB=happybees \
    timescale/timescaledb:latest-pg16
```

### 3. Start the Backend Server

```bash
# From project root with venv activated
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify: http://localhost:8000/health should return `{"status": "healthy"}`

### 4. Start the Dashboard

```bash
# In a new terminal, from project root with venv activated
python -m backend.dashboard.app --node pico-hive-001
```

Open http://localhost:8050 in your browser.

### 5. Connect a Device

**Option A: Mock Device (no hardware required)**

```bash
# In a third terminal, from project root with venv activated
python backend/scripts/mock_stream.py --node pico-hive-001
```

**Option B: Real Pico Hardware**

See the Firmware section below.

---

## Firmware

### Building

```bash
cd firmware

# Set Pico SDK path
export PICO_SDK_PATH=/path/to/pico-sdk

# Build
mkdir build && cd build
cmake .. -DPICO_BOARD=pico2_w
make -j4
```

### Flashing

1. Hold BOOTSEL button on Pico
2. Plug in USB cable
3. Copy `happybees_firmware.uf2` to the mounted RP2350 drive

### Configuration

Connect via serial to configure WiFi:

```bash
tio -b 115200 /dev/tty.usbmodem*

> wifi YOUR_SSID YOUR_PASSWORD
> server 192.168.0.100
> p   # Ping to verify
```

### Serial Commands

| Command | Description |
|---------|-------------|
| `s` | Run Summer model inference |
| `w` | Run Winter model inference |
| `t` | Read temperature/humidity |
| `a[N]` | Stream N seconds of audio (default 6) |
| `d` | Debug dump (show all 20 features) |
| `m` | Toggle mock sensor mode |
| `c` | Clear rolling history |
| `g[N.NN]` | Show/set gain compensation (e.g., `g0.35`) |
| `b` | Toggle background sampling |
| `p` | Ping (show version and status) |
| `h` | Show help |

---

## Verification and Testing

### Testing the ML Model

The model can be tested independently of the firmware:

```bash
# Run feature sensitivity sweep
python tools/test_features.py --sweep

# Test specific features from Pico output
python tools/test_features.py
```

### Verifying DSP Parity

Capture audio from the Pico and verify FFT calculations match the reference:

```bash
# Capture audio from Pico
python tools/audio_capture.py -d /dev/tty.usbmodem2101 -o pico_audio.wav

# Analyze and find optimal gain
python tools/parity_diagnostic.py pico_audio.wav --find-gain

# Compare with Mac reference
python tools/mac_shim.py --model summer --verbose
```

### Running the Mac Reference Implementation

The mac_shim.py provides a reference implementation using the Mac's microphone:

```bash
python tools/mac_shim.py --model summer --verbose
# Press Enter to record 6 seconds and run inference
```

---

## Understanding the ML Model

The Summer model detects swarming/piping events based on acoustic analysis. Key points:

1. **Primary Feature: Spike Ratio** - The model primarily uses the ratio of current audio energy to historical average. A spike > 1.3 indicates increasing activity (potential swarm), while < 0.7 indicates decreasing activity (normal settling).

2. **Why "Always Swarming" on Fresh Start** - With no history, spike ratio = 1.0 (steady state), which the model treats as potentially concerning. After 5-6 readings, the rolling average stabilizes.

3. **Gain Calibration** - Different microphone circuits require different gain compensation. Default is 0.35 for TLC272CP op-amp. Adjust with `g` command until FFT bins are 0.02-0.06 for a quiet room.

For complete technical details, see [docs/ML_MODEL_GUIDE.md](docs/ML_MODEL_GUIDE.md).

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/telemetry/` | Store sensor readings |
| GET | `/api/v1/telemetry/?node_id=X` | Get telemetry history |
| POST | `/api/v1/inference/` | Store ML results |
| GET | `/api/v1/inference/latest?node_id=X` | Get latest inference |
| POST | `/api/v1/commands/` | Queue command for device |
| GET | `/api/v1/commands/pending?node_id=X` | Get pending commands |
| POST | `/api/v1/logs/` | Store device log |
| GET | `/api/v1/logs/?node_id=X` | Get log history |

---

## Container Deployment

For production deployment using containers:

```bash
podman-compose up -d
```

This starts TimescaleDB, the backend API, and the dashboard.

---

## Troubleshooting

**Dashboard shows "--" for values**
- Verify backend is running: `curl localhost:8000/health`
- Check device is connected (look for POST requests in backend logs)

**Pico won't connect to WiFi**
- Verify SSID/password spelling
- Ensure 2.4GHz network (Pico doesn't support 5GHz)

**Always predicts "Swarming"**
- Normal on fresh start - run inference 5-6 times to build history
- Or make noise during one capture, then go quiet (spike will drop)

**FFT bins too high/low**
- Adjust gain: `g0.25` (lower) or `g0.50` (higher)
- Target: bins 0.02-0.06 for quiet room

---

## License

BSD 3-Clause License. See [LICENSE](LICENSE) for details.

Edge Impulse SDK components are subject to Edge Impulse Terms of Service.

# HappyBees Quick Start Guide

This guide gets you from zero to a running HappyBees system in 15 minutes.

## Prerequisites

- Python 3.11+ with `uv` package manager
- Podman or Docker
- (For firmware) Pico SDK 2.0+, CMake, ARM GCC

---

## Step 1: Start the Database (2 min)

```bash
# Using Podman
podman run -d --name beewatch-db \
    -p 5432:5432 \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=beewatch_dev \
    -e POSTGRES_DB=beewatch \
    timescale/timescaledb:latest-pg16

# Verify it's running
podman ps
```

---

## Step 2: Start the Backend (3 min)

```bash
cd backend

# Create virtual environment
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
uv pip install -r requirements.txt

# Start the server
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

Test it: http://localhost:8000/health should return `{"status": "healthy"}`

---

## Step 3: Start the Dashboard (1 min)

```bash
# In a new terminal, from backend/
source .venv/bin/activate

# Start dashboard
uv run python -m dashboard.app --node pico-hive-001
```

Open http://localhost:8050 in your browser.

---

## Step 4: Connect a Device

### Option A: Mock Device (No Hardware Required)

```bash
# In a third terminal, from backend/
source .venv/bin/activate

uv run python scripts/mock_stream.py --node pico-hive-001
```

You'll see temperature/humidity data appear on the dashboard!

### Option B: Real Pico Hardware

#### Build the Firmware

```bash
cd firmware

# Set SDK path
export PICO_SDK_PATH=/path/to/pico-sdk

# Build
mkdir build && cd build
cmake .. -DPICO_BOARD=pico2_w
make -j4
```

#### Flash the Firmware

1. Hold BOOTSEL button on Pico
2. Plug in USB
3. Copy `beewatch_firmware.uf2` to the mounted drive

#### Configure WiFi

```bash
# Connect to Pico serial
tio -b 115200 /dev/tty.usbmodem*

# Set credentials
> wifi YOUR_SSID YOUR_PASSWORD
> server 192.168.0.100  # Your computer's IP
```

The Pico will connect and appear on the dashboard!

---

## Step 5: Test the System

From the dashboard, click these buttons:

1. **T | READ SENSORS** - Should show temperature/humidity
2. **S | SUMMER INFER** - Runs ML inference
3. **P | PING DEVICE** - Tests connectivity

---

## Troubleshooting

### Dashboard shows "--" for values
- Check if backend is running (`curl localhost:8000/health`)
- Check if device is connected (look for POST requests in backend logs)

### Pico won't connect to WiFi
- Double-check SSID/password spelling
- Ensure 2.4GHz network (Pico doesn't support 5GHz)
- Check router allows new devices

### Always predicts "Swarming"
- This is normal on fresh start (no history)
- Run inference 5-6 times to build up rolling average
- Or make noise during one capture, then go quiet

---

## Next Steps

1. Read [ML_MODEL_GUIDE.md](docs/ML_MODEL_GUIDE.md) to understand the model
2. Read [ARCHITECTURE.md](docs/ARCHITECTURE.md) for system design
3. Calibrate gain for your microphone hardware
4. Deploy to actual beehive!

---

## Commands Reference

| Serial | Dashboard Button | Action |
|--------|------------------|--------|
| `s` | S \| SUMMER INFER | Run Summer model |
| `w` | W \| WINTER INFER | Run Winter model |
| `t` | T \| READ SENSORS | Read temp/humidity |
| `a` | A \| AUDIO STREAM | Stream raw audio |
| `m` | M \| TOGGLE MOCK | Toggle mock mode |
| `c` | C \| CLEAR HIST | Clear rolling average |
| `d` | D \| DEBUG DUMP | Show all features |
| `p` | P \| PING DEVICE | Show status |
| `g0.35` | - | Set gain compensation |
| `b` | - | Toggle background sampling |
| `h` | - | Show help |

---

*Happy beekeeping! 🐝*

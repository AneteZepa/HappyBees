# HappyBees: Distributed IoT Beehive Monitoring System

<p align="center">
  <img src="assets/beewatch_logo.png" alt="BeeWatch Logo" width="200">
</p>

HappyBees is a distributed IoT beehive monitoring system. It uses edge ML on a Raspberry Pi Pico 2 W to detect swarming events via acoustic analysis and uploads telemetry to a central server with a real-time dashboard.

## Project Structure

```text
HappyBees/
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

* Python 3.11+ with `uv` [package manager](https://docs.astral.sh/uv/getting-started/installation/)
* [Podman](https://podman.io/docs/installation) or [Docker](https://docs.docker.com/engine/install/) (for [TimescaleDB](https://www.tigerdata.com/docs/self-hosted/latest/install))
* [Pico SDK 2.0+](https://github.com/raspberrypi/pico-sdk) (for firmware development)
* [CMake 3.20+](https://cmake.org/download/) and [ARM GCC toolchain](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads)
* [tio](https://github.com/tio/tio) serial device I/O tool

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

> **Note:** If using Podman on macOS or Windows, you must initialize the VM first:
>
> ```bash
> podman machine init
> podman machine start
> ```

Run the database container:

```bash
podman run -d --name happybees-db \
    -p 5432:5432 \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=happybees_dev \
    -e POSTGRES_DB=happybees \
    timescale/timescaledb:latest-pg16
```

### 3. Start the Backend Server

From project root with venv activated:

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify: `http://localhost:8000/health` should return `{"status": "healthy"}`

### 4. Start the Dashboard

In a new terminal (without forgetting to activate your environment `source .venv/bin/activate`), from project root with venv activated:

```bash
python -m backend.dashboard.app --node pico-hive-001
```

Open [http://localhost:8050](http://localhost:8050) in your browser.

### 5. Connect a Device

**Option A: Mock Device (no hardware required)**

In a third terminal (without forgetting to `source .venv/bin/activate`), from project root with venv activated:

```bash
python backend/scripts/mock_stream.py --node pico-hive-001
```

**Option B: Real Pico Hardware**

**Note:** if you ran the mock device above, you will first need to stop all traffic and processes related to it before attempting to connect the real device.

To stop the mock, wipe and reset the database:
```bash
# Kill processes on port 8000 (Backend) and 8050 (Dashboard)
lsof -ti:8000,8050 | xargs kill -9
# 1. Stop the container
podman stop happybees-db

# 2. Remove the container (This WIPES the data because no volume was mapped)
podman rm happybees-db

# 3. (Optional) Prune anonymous volumes to be absolutely sure
podman volume prune -f
```

Now that the "bad" state is cleared, restart the components: start the database, backend, and dashboard.

See the *Firmware* section below.

---

## Firmware

### Building

```bash
cd firmware

# 1. Download the required CMake helper
curl -o pico_sdk_import.cmake https://raw.githubusercontent.com/raspberrypi/pico-sdk/master/external/pico_sdk_import.cmake

# 2. Install Pico SDK to home directory (temporarily switch context)
pushd ~
git clone https://github.com/raspberrypi/pico-sdk.git
cd pico-sdk
git submodule update --init
popd

# 3. Build with explicit SDK path
mkdir -p build && cd build
cmake .. -DPICO_BOARD=pico2_w -DPICO_SDK_PATH=~/pico-sdk
make -j4
```

### Flashing

1.  Hold **BOOTSEL** button on Pico.
2.  Plug in USB cable.
3.  Copy `beewatch_firmware.uf2` to the mounted RP2350 drive.

### Configuration

**1. Find your Server's Local IP Address**

Since the Pico needs to send data to your computer, you must tell it your computer's IP address on the local network.

* **macOS**: Run `ipconfig getifaddr en0` (WiFi) or check System Settings > Wi-Fi > Details.
* **Linux**: Run `hostname -I`
* **Windows**: Run `ipconfig` and look for "IPv4 Address".

**2. Configure the Device**

Connect via serial to configure WiFi:

```bash
tio -b 115200 /dev/tty.usbmodem*
```

Enter the following commands in the serial console:

```text
> wifi YOUR_SSID YOUR_PASSWORD
> server YOUR_IP
> p   # Ping to verify
```
Now you can go to [http://localhost:8050](http://localhost:8050) and press `T|READ SENSORS` button to start collecting time-series temperature and humidity data and `S|SUMMER INFER` to run the summer model inference.
### Serial Commands

| Command | Description |
| :--- | :--- |
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

### Running the MacOS Reference Implementation

The `mac_shim.py` provides a reference implementation using your Mac's microphone:

```bash
python tools/mac_shim.py --model summer --verbose
# Press Enter to record 6 seconds and run inference
```

**Note:** we developed the verification shim layer using macOS but the script should be trivial to adapt to other OSes provided you pass the correct audio interface/abstraction for your specific OS.

## Understanding the ML Model

The Summer model detects swarming/piping events based on acoustic analysis. Key points:

* **Primary Feature: Spike Ratio** - The model primarily uses the ratio of current audio energy to historical average. A spike > 1.3 indicates increasing activity (potential swarm), while < 0.7 indicates decreasing activity (normal settling).
* **Why "Always Swarming" on Fresh Start** - With no history, spike ratio = 1.0 (steady state), which the model treats as potentially concerning. After 5-6 readings, the rolling average stabilizes.
* **Gain Calibration** - Different microphone circuits require different gain compensation. Default is 0.35 for TLC272CP op-amp. Adjust with `g` command until FFT bins are 0.02-0.06 for a quiet room.

For complete technical details, see `docs/ML_MODEL_GUIDE.md`.

---

## API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/api/v1/telemetry/` | Store sensor readings |
| **GET** | `/api/v1/telemetry/?node_id=X` | Get telemetry history |
| **POST** | `/api/v1/inference/` | Store ML results |
| **GET** | `/api/v1/inference/latest?node_id=X` | Get latest inference |
| **POST** | `/api/v1/commands/` | Queue command for device |
| **GET** | `/api/v1/commands/pending?node_id=X` | Get pending commands |
| **POST** | `/api/v1/logs/` | Store device log |
| **GET** | `/api/v1/logs/?node_id=X` | Get log history |

## Container Deployment

For production deployment using containers:

```bash
podman-compose up -d
```

This starts TimescaleDB, the backend API, and the dashboard.

## Troubleshooting

* **Dashboard shows "--" for values**
    * Verify backend is running: `curl localhost:8000/health`
    * Check device is connected (look for POST requests in backend logs)

* **Pico won't connect to WiFi**
    * Verify SSID/password spelling
    * Ensure 2.4GHz network (Pico doesn't support 5GHz)

* **Always predicts "Swarming"**
    * Normal on fresh start - run inference 5-6 times to build history
    * Or make noise during one capture, then go quiet (spike will drop)

* **FFT bins too high/low**
    * Adjust gain: `g0.25` (lower) or `g0.50` (higher)
    * Target: bins 0.02-0.06 for quiet room

## License

BSD 3-Clause License. See `LICENSE` for details.
Edge Impulse SDK components are subject to Edge Impulse Terms of Service.
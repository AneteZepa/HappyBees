import httpx
import time
import random
import asyncio
import argparse
import sys
from datetime import datetime

class MockDevice:
    def __init__(self, node_id, api_url):
        self.node_id = node_id
        self.api_url = api_url
        self.client = httpx.AsyncClient(timeout=5.0)
        self.mock_mode = False
        self.temp = 25.0
        self.hum = 50.0
        print(f"\n[INIT] Starting Mock Device")
        print(f"       ID:  {self.node_id}")
        print(f"       API: {self.api_url}\n")

    async def log(self, message):
        """Send a log line to the backend to appear in the terminal"""
        print(f"[LOG] {message}")
        try:
            await self.client.post(f"{self.api_url}/logs/", json={"node_id": self.node_id, "message": message})
        except Exception as e:
            print(f"Failed to push log: {e}")

    async def push_telemetry(self):
        """Send sensor data to the telemetry table"""
        # Apply drift if not in mock mode
        if not self.mock_mode:
            self.temp += random.uniform(-0.2, 0.2)
            self.hum += random.uniform(-0.5, 0.5)
            # Bound humidity
            self.hum = max(0, min(100, self.hum))
        else:
            self.temp = 25.0
            self.hum = 50.0
            
        payload = {
            "node_id": self.node_id,
            "timestamp": datetime.utcnow().isoformat(),
            "temperature_c": self.temp,
            "humidity_pct": self.hum,
            "battery_mv": 4200, 
            "error_flags": 0
        }
        try:
            await self.client.post(f"{self.api_url}/telemetry/", json=payload)
        except Exception as e:
            print(f"Failed to push telemetry: {e}")

    async def poll_commands(self):
        try:
            r = await self.client.get(f"{self.api_url}/commands/pending", params={"node_id": self.node_id})
            if r.status_code == 200:
                for cmd in r.json():
                    await self.handle_command(cmd)
        except Exception as e:
            print(f"! Poll Error: {e}")

    async def handle_command(self, cmd):
        ctype = cmd['command_type']
        params = cmd.get('params') or {}
        
        await self.log(f"CMD_RECV: {ctype}")
        await asyncio.sleep(0.5)
        
        # 1. PING (p)
        if ctype == 'PING':
            await self.log("RSP:01:OK:PONG")

        # 2. READ_CLIMATE (t)
        elif ctype == 'READ_CLIMATE':
            await self.log(f"[SENSOR] Temp: {self.temp:.2f} C, Humidity: {self.hum:.2f} %")
            await self.push_telemetry()
            
        # 3. TOGGLE_MOCK (m)
        elif ctype == 'TOGGLE_MOCK':
            self.mock_mode = not self.mock_mode
            state = "ENABLED" if self.mock_mode else "DISABLED"
            await self.log(f"[CONFIG] Mock mode {state}")
            if self.mock_mode:
                await self.log(f"  Temp: 25.0 C, Humidity: 50.0 %, Hour: 14.0")

        # 4. CLEAR_HISTORY (c)
        elif ctype == 'CLEAR_HISTORY':
            await self.log("[CONFIG] History cleared. Ready for fresh parity test.")

        # 5. DEBUG_DUMP (d)
        elif ctype == 'DEBUG_DUMP':
            await self.log("[DEBUG] Full feature dump:")
            await asyncio.sleep(0.5)
            await self.log("--- FEATURE VECTOR (20 elements) ---")
            await self.log(f"f[0] temp:      {self.temp:.4f}")
            await self.log(f"f[1] humidity:  {self.hum:.4f}")
            await self.log(f"f[2] hour:      14.0000")
            await self.log("f[3] spike:     1.0000")
            for i in range(16):
                 val = 0.15 + random.uniform(-0.02, 0.02)
                 await self.log(f"f[{i+4}] hz_bin_{i}:  {val:.6f}")
            await self.log("-----------------------------------")

        # 6. CAPTURE_AUDIO (a)
        elif ctype == 'CAPTURE_AUDIO':
            await self.log(f"[STREAM] Capturing 96000 samples...")
            await asyncio.sleep(2.0) # Simulate capture time
            await self.log(f"[STREAM] Stats: Min=1950, Max=2150, StdDev=25.3")
            await self.log("HDR:192000:96000:25.3")
            await self.log("<binary data stream not displayed in terminal>")
            await self.log("END")

        # 7. RUN_INFERENCE (s/w)
        elif ctype == 'RUN_INFERENCE':
            model = params.get('model', 'summer')
            await self.log(f"[REC] Capturing 96000 samples...")
            await asyncio.sleep(1.0)
            await self.log("[DSP] Processing audio...")
            
            density = 0.012345 if self.mock_mode else random.uniform(0.005, 0.02)
            await self.log(f"[DSP] RMS density: {density:.6f}")
            
            await self.log("[AI] Building feature vector...")
            await asyncio.sleep(0.5)
            
            # Mock result
            conf = 0.912
            label = "NORMAL"
            
            await self.log("==================== HIVE STATUS ====================")
            await self.log(f"State:           [OK] {label} STATE")
            await self.log(f"Confidence:      {conf*100:.1f}%")
            if self.mock_mode:
                 await self.log("Mode:            MOCK")
            await self.log("=====================================================")
            
            # Push inference result to DB
            try:
                await self.client.post(f"{self.api_url}/inference/", json={
                    "node_id": self.node_id,
                    "model_type": model,
                    "classification": label,
                    "confidence": conf,
                    "timestamp": datetime.utcnow().isoformat()
                })
            except: pass

    async def run(self):
        await self.log("[SYS] Mock System Online")
        while True:
            # Poll for commands
            await self.poll_commands()
            
            # Send heartbeat telemetry periodically (every loop for mock responsiveness)
            # In real firmware this is less frequent, but for UI testing we want live graphs
            await self.push_telemetry()
            
            await asyncio.sleep(2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", default="mock-node-001", help="Node ID to simulate")
    parser.add_argument("--api", default="http://localhost:8000/api/v1", help="API URL")
    args = parser.parse_args()
    
    device = MockDevice(args.node, args.api)
    try:
        asyncio.run(device.run())
    except KeyboardInterrupt:
        print("\nShutdown")

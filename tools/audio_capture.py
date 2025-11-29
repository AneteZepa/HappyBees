#!/usr/bin/env python3
"""
HappyBees Audio Capture Tool

Captures raw audio from the Pico firmware and saves as WAV file.
Uses the firmware 'a' command to stream raw ADC samples.

Usage:
    python tools/audio_capture.py -d /dev/tty.usbmodem2101 -o pico_audio.wav
    python tools/audio_capture.py --list
"""

import argparse
import struct
import time
import sys

import numpy as np
import scipy.signal
import scipy.io.wavfile

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("ERROR: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

SAMPLE_RATE = 16000


def list_ports():
    """List available serial ports."""
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No serial ports found.")
        return
    print("Available serial ports:")
    for port in ports:
        print(f"  {port.device} - {port.description}")


def capture_audio(device, duration=6, verbose=False):
    """Capture audio from Pico via serial."""
    print(f"Connecting to {device}...")

    try:
        ser = serial.Serial(device, 115200, timeout=10)
    except serial.SerialException as e:
        print(f"ERROR: Could not open {device}: {e}")
        return None

    print("Connected!")
    time.sleep(0.5)
    ser.reset_input_buffer()

    cmd = f"a{duration}\n"
    print(f"\nCapturing {duration}s of audio...")
    print("=" * 40)

    ser.write(cmd.encode())

    # Read until header
    header = None
    while True:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if verbose:
            print(f"  > {line}")

        if line.startswith("HDR:"):
            parts = line.split(":")
            if len(parts) >= 3:
                num_bytes = int(parts[1])
                num_samples = int(parts[2])
                std_dev = float(parts[3]) if len(parts) > 3 else 0
                header = (num_bytes, num_samples, std_dev)
                break

        if "ERROR" in line or "failed" in line.lower():
            print(f"ERROR: {line}")
            ser.close()
            return None

    if not header:
        print("ERROR: No header received")
        ser.close()
        return None

    num_bytes, num_samples, std_dev = header
    print(f"Receiving {num_samples} samples ({num_bytes} bytes)...")
    print("=" * 40)

    raw_data = ser.read(num_bytes)

    if len(raw_data) != num_bytes:
        print(f"WARNING: Expected {num_bytes} bytes, got {len(raw_data)}")

    # Wait for END marker
    while True:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line == "END":
            break

    ser.close()

    samples = np.frombuffer(raw_data, dtype=np.uint16)
    print(f"Received {len(samples)} samples")
    print(f"Pico reported StdDev: {std_dev}")

    return samples


def process_audio(raw_adc, verbose=False):
    """Process raw ADC data for WAV file."""
    if verbose:
        print(f"\nProcessing audio:")
        print(f"  Raw ADC: min={raw_adc.min()}, max={raw_adc.max()}, "
              f"mean={np.mean(raw_adc):.0f}")

    dc_offset = np.mean(raw_adc)
    audio = (raw_adc.astype(np.float64) - dc_offset) / 2048.0

    if verbose:
        print(f"  After normalization: std={np.std(audio):.4f}")

    # Apply filters
    sos_hp = scipy.signal.butter(2, 100, btype='high', fs=SAMPLE_RATE, output='sos')
    audio = scipy.signal.sosfilt(sos_hp, audio)

    sos_lp = scipy.signal.butter(3, 6000, btype='low', fs=SAMPLE_RATE, output='sos')
    audio = scipy.signal.sosfilt(sos_lp, audio)

    if verbose:
        print(f"  After filtering: std={np.std(audio):.4f}")

    audio = audio * 32767
    return np.clip(audio, -32768, 32767).astype(np.int16)


def main():
    parser = argparse.ArgumentParser(description="HappyBees Audio Capture")
    parser.add_argument('-d', '--device', help='Serial device')
    parser.add_argument('-o', '--output', default='pico_audio.wav', help='Output WAV file')
    parser.add_argument('-t', '--time', type=int, default=6, help='Capture duration (1-6)')
    parser.add_argument('--play', action='store_true', help='Play audio after capture')
    parser.add_argument('--list', action='store_true', help='List available ports')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    if args.list:
        list_ports()
        return

    if not args.device:
        print("ERROR: No device specified. Use -d /dev/tty.usbmodem* or --list")
        return

    raw_samples = capture_audio(args.device, args.time, args.verbose)
    if raw_samples is None:
        return

    processed = process_audio(raw_samples, args.verbose)
    scipy.io.wavfile.write(args.output, SAMPLE_RATE, processed)
    print(f"\nSaved: {args.output}")

    if args.play:
        try:
            import sounddevice as sd
            print("Playing audio...")
            sd.play(processed, SAMPLE_RATE)
            sd.wait()
        except ImportError:
            print("WARNING: sounddevice not installed for playback")


if __name__ == "__main__":
    main()

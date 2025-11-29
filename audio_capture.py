#!/usr/bin/env python3
"""
BeeWatch Audio Capture Tool

Captures raw audio from the Pico firmware and saves as WAV file.
Uses the firmware 'a' command to stream raw ADC samples.

Usage:
    python audio_capture.py -d /dev/tty.usbmodem2101 -o pico_audio.wav
    python audio_capture.py -d /dev/tty.usbmodem2101 -o test.wav --play
    python audio_capture.py --list  # List available serial ports
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
    
    # Flush any pending data
    ser.reset_input_buffer()
    
    # Send audio capture command
    cmd = f"a{duration}\n"
    print(f"\nCapturing {duration}s of audio...")
    print("=" * 40)
    
    ser.write(cmd.encode())
    
    # Read response until we get the header
    header = None
    while True:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if verbose:
            print(f"  > {line}")
        
        if line.startswith("HDR:"):
            # Parse header: HDR:bytes:samples:stddev
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
    
    # Read raw binary data
    raw_data = ser.read(num_bytes)
    
    if len(raw_data) != num_bytes:
        print(f"WARNING: Expected {num_bytes} bytes, got {len(raw_data)}")
    
    # Wait for END marker
    while True:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line == "END":
            break
        if verbose and line:
            print(f"  > {line}")
    
    ser.close()
    
    # Parse uint16_t samples
    samples = np.frombuffer(raw_data, dtype=np.uint16)
    
    print(f"Received {len(samples)} samples")
    print(f"Pico reported StdDev: {std_dev}")
    
    return samples


def process_audio_for_playback(raw_adc, verbose=False):
    """
    Process raw ADC data for WAV file.
    Applies same DSP as firmware for fair comparison.
    """
    if verbose:
        print(f"\nProcessing audio:")
        print(f"  Raw ADC: min={raw_adc.min()}, max={raw_adc.max()}, "
              f"mean={np.mean(raw_adc):.0f}, std={np.std(raw_adc):.1f}")
    
    # Convert to float and remove DC - SAME as firmware
    # Firmware: (adc - dc_offset) / 2048.0
    dc_offset = np.mean(raw_adc)
    audio = (raw_adc.astype(np.float64) - dc_offset) / 2048.0
    
    if verbose:
        print(f"  After ADC normalization: min={audio.min():.4f}, max={audio.max():.4f}, std={np.std(audio):.4f}")
    
    # Apply same filters as firmware
    # HP: 2nd order Butterworth @ 100Hz
    sos_hp = scipy.signal.butter(2, 100, btype='high', fs=SAMPLE_RATE, output='sos')
    audio = scipy.signal.sosfilt(sos_hp, audio)
    
    # LP: 3rd order Butterworth @ 6000Hz
    sos_lp = scipy.signal.butter(3, 6000, btype='low', fs=SAMPLE_RATE, output='sos')
    audio = scipy.signal.sosfilt(sos_lp, audio)
    
    if verbose:
        print(f"  After filtering: min={audio.min():.4f}, max={audio.max():.4f}, std={np.std(audio):.4f}")
    
    # Scale to int16 for WAV - use fixed gain instead of peak normalization
    # This preserves relative amplitude for comparison
    audio = audio * 32767
    
    if verbose:
        print(f"  Output: peak={np.max(np.abs(audio)):.0f}")
    
    return np.clip(audio, -32768, 32767).astype(np.int16)


def main():
    parser = argparse.ArgumentParser(description="BeeWatch Audio Capture")
    parser.add_argument('-d', '--device', help='Serial device (e.g., /dev/tty.usbmodem2101)')
    parser.add_argument('-o', '--output', default='pico_audio.wav', help='Output WAV file')
    parser.add_argument('-t', '--time', type=int, default=6, help='Capture duration (1-6 seconds)')
    parser.add_argument('--play', action='store_true', help='Play audio after capture')
    parser.add_argument('--list', action='store_true', help='List available serial ports')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    if args.list:
        list_ports()
        return
    
    if not args.device:
        print("ERROR: No device specified. Use -d /dev/tty.usbmodem* or --list to find ports.")
        return
    
    # Capture
    raw_samples = capture_audio(args.device, args.time, args.verbose)
    
    if raw_samples is None:
        return
    
    # Process
    processed = process_audio_for_playback(raw_samples, args.verbose)
    
    # Save
    scipy.io.wavfile.write(args.output, SAMPLE_RATE, processed)
    print(f"\nSaved: {args.output}")
    
    # Play
    if args.play:
        try:
            import sounddevice as sd
            print("Playing audio...")
            sd.play(processed, SAMPLE_RATE)
            sd.wait()
        except ImportError:
            print("WARNING: sounddevice not installed. Cannot play audio.")
            print("Install with: pip install sounddevice")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
HappyBees Mac Shim

Reference ML implementation that runs on Mac/PC using the computer's microphone.
Used to establish ground truth for model predictions and verify firmware parity.

Usage:
    python tools/mac_shim.py --model summer --verbose
    python tools/mac_shim.py --model winter --mock-temp 30.0
"""

import argparse
import sys
import time
import os
import numpy as np
import scipy.signal
import sounddevice as sd

try:
    import tensorflow.lite as tflite
except ImportError:
    print("ERROR: TensorFlow not installed. Run: pip install tensorflow")
    sys.exit(1)

# Constants matching firmware
SAMPLE_RATE = 16000
DURATION = 6
FFT_SIZE = 512
FFT_HOP = 512
HISTORY_SIZE = 12

SUMMER_FREQ_INDICES = list(range(4, 20))
WINTER_HEATER_INDICES = [6, 7, 8]


class State:
    """State persistence for rolling averages."""

    def __init__(self):
        self.audio_density_history = []
        self.temp_history = []

    def update_density(self, density):
        self.audio_density_history.append(density)
        if len(self.audio_density_history) > HISTORY_SIZE:
            self.audio_density_history.pop(0)

    def get_rolling_density(self):
        if not self.audio_density_history:
            return 1.0
        return np.mean(self.audio_density_history)

    def update_temp(self, temp):
        self.temp_history.append(temp)
        if len(self.temp_history) > HISTORY_SIZE:
            self.temp_history.pop(0)

    def get_temp_stability(self):
        if len(self.temp_history) < 2:
            return 0.0
        return np.var(self.temp_history)


state = State()


def get_model_path(model_type):
    """Find the model file."""
    if model_type == 'summer':
        base = "mode_summer"
    else:
        base = "model_winter"

    # Try various paths
    paths = [
        os.path.join(base, "tflite-model", "model.tflite"),
        os.path.join("firmware", base, "tflite-model", "model.tflite"),
        os.path.join("..", base, "tflite-model", "model.tflite"),
    ]

    for path in paths:
        if os.path.exists(path):
            return path

    print(f"[ERROR] Model not found. Searched: {paths}")
    sys.exit(1)


def process_audio(raw_audio, verbose=False):
    """DSP Pipeline: DC Removal -> High Pass -> Low Pass"""
    audio = raw_audio.astype(np.float64)
    audio = audio - np.mean(audio)

    if verbose:
        print(f"[DSP] After DC removal: min={audio.min():.0f}, max={audio.max():.0f}")

    # High-pass filter (100Hz)
    sos_hp = scipy.signal.butter(2, 100, btype='high', fs=SAMPLE_RATE, output='sos')
    audio = scipy.signal.sosfilt(sos_hp, audio)

    if verbose:
        print(f"[DSP] After HP filter:  min={audio.min():.0f}, max={audio.max():.0f}")

    # Low-pass filter (6000Hz)
    sos_lp = scipy.signal.butter(3, 6000, btype='low', fs=SAMPLE_RATE, output='sos')
    audio = scipy.signal.sosfilt(sos_lp, audio)

    if verbose:
        print(f"[DSP] After LP filter:  min={audio.min():.0f}, max={audio.max():.0f}")

    return audio


def compute_fft_features(audio, verbose=False):
    """Compute FFT features matching firmware."""
    window = np.hanning(FFT_SIZE)
    num_windows = (len(audio) - FFT_SIZE) // FFT_HOP + 1

    if verbose:
        print(f"[FFT] Computing {num_windows} windows ({FFT_SIZE} samples)")

    fft_accum = np.zeros(FFT_SIZE // 2 + 1)

    for i in range(num_windows):
        start = i * FFT_HOP
        segment = audio[start:start + FFT_SIZE] * window
        fft_out = np.fft.rfft(segment)
        magnitude = np.abs(fft_out)
        fft_accum += magnitude

    avg_magnitude = fft_accum / num_windows
    return avg_magnitude


def main():
    parser = argparse.ArgumentParser(description="HappyBees Mac Shim")
    parser.add_argument('--model', choices=['summer', 'winter'], default='summer')
    parser.add_argument('--mock-temp', type=float, default=25.0)
    parser.add_argument('--mock-humidity', type=float, default=50.0)
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--no-loop', action='store_true')
    args = parser.parse_args()

    model_path = get_model_path(args.model)
    print(f"Loading TFLite model: {model_path}")

    try:
        interpreter = tflite.Interpreter(model_path=model_path)
        interpreter.allocate_tensors()
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()
    except Exception as e:
        print(f"[ERROR] Failed to load model: {e}")
        sys.exit(1)

    expected_input_size = input_details[0]['shape'][1]
    print(f"Model expects input vector size: {expected_input_size}")

    print("=" * 60)
    print(f"HappyBees Mac Shim v0.1 | Model: {args.model.upper()}")
    print("=" * 60)

    while True:
        try:
            input(f"\nPress ENTER to record {DURATION}s (Ctrl+C to exit)...")

            print(f"[RECORDING] Capturing {DURATION}s...")
            recording = sd.rec(
                int(DURATION * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                blocking=True
            )
            recording = recording.flatten()

            if np.std(recording) == 0:
                print("[WARNING] Audio is silence. Check microphone permissions.")

            if args.verbose:
                print(f"[DSP] Raw stats: min={recording.min():.3f}, max={recording.max():.3f}")

            processed_audio = process_audio(recording, args.verbose)
            fft_mags = compute_fft_features(processed_audio, args.verbose)

            current_density = np.sqrt(np.mean(processed_audio ** 2))
            state.update_density(current_density)
            state.update_temp(args.mock_temp)

            # Build feature vector
            features = []

            if args.model == 'summer':
                features.append(args.mock_temp)
                features.append(args.mock_humidity)
                features.append(14.0)  # Hour

                rolling = state.get_rolling_density()
                spike = current_density / (rolling + 1e-6)
                features.append(spike)

                for idx in SUMMER_FREQ_INDICES:
                    features.append(fft_mags[idx])

                if args.verbose:
                    print("\n[FEATURES] Frequency Bins (125Hz - 594Hz):")
                    for i, idx in enumerate(SUMMER_FREQ_INDICES):
                        freq = idx * (SAMPLE_RATE / FFT_SIZE)
                        print(f"  {freq:.1f} Hz (Bin {idx}): {fft_mags[idx]:.5f}")

            elif args.model == 'winter':
                features.append(args.mock_temp)
                features.append(args.mock_humidity)
                features.append(state.get_temp_stability())
                heater_pwr = sum(fft_mags[i] for i in WINTER_HEATER_INDICES)
                features.append(heater_pwr)
                ratio = heater_pwr / (current_density + 1e-6)
                features.append(ratio)

            if len(features) != expected_input_size:
                print(f"[ERROR] Generated {len(features)} features, expected {expected_input_size}")
                continue

            # Run inference
            input_data = np.array([features], dtype=np.float32)
            interpreter.set_tensor(input_details[0]['index'], input_data)

            start_time = time.time()
            interpreter.invoke()
            end_time = time.time()

            output_data = interpreter.get_tensor(output_details[0]['index'])[0]

            # Report results
            print("\n" + "=" * 20 + " RESULT " + "=" * 20)
            print(f"Inference Time: {(end_time - start_time) * 1000:.1f} ms")

            if args.model == 'summer':
                print(f"Raw Output: {output_data}")
                class_idx = np.argmax(output_data)
                confidence = output_data[class_idx]
                labels = ["Normal", "Swarm/Piping"]
                label = labels[class_idx] if class_idx < len(labels) else "Unknown"

                print(f"Classification: {label}")
                print(f"Confidence:     {confidence * 100:.1f}%")
            else:
                mse = np.mean((input_data - output_data) ** 2)
                print(f"Reconstruction MSE: {mse:.4f}")
                if mse > 5.0:
                    print("Status: ANOMALY DETECTED")
                else:
                    print("Status: NORMAL")

            print("=" * 48)

            if args.no_loop:
                break

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
BeeWatch Parity Diagnostic Tool

Analyzes audio files (WAV or raw ADC) and shows intermediate values
at each DSP stage, helping verify firmware matches the reference implementation.

Usage:
    python parity_diagnostic.py pico_audio.wav
    python parity_diagnostic.py pico_audio.wav --gain 0.35
    python parity_diagnostic.py pico_audio.wav --find-gain
"""

import argparse
import numpy as np
import scipy.signal
import scipy.io.wavfile

# Constants matching firmware
SAMPLE_RATE = 16000
FFT_SIZE = 512
FFT_HOP = 512


def mac_shim_dsp_pipeline(audio):
    """
    Apply the same DSP pipeline as mac_shim.py and firmware.
    HP filter (100Hz) -> LP filter (6kHz)
    """
    # High-pass filter: 2nd order Butterworth @ 100Hz
    sos_hp = scipy.signal.butter(2, 100, btype='high', fs=SAMPLE_RATE, output='sos')
    audio = scipy.signal.sosfilt(sos_hp, audio)
    
    # Low-pass filter: 3rd order Butterworth @ 6kHz
    sos_lp = scipy.signal.butter(3, 6000, btype='low', fs=SAMPLE_RATE, output='sos')
    audio = scipy.signal.sosfilt(sos_lp, audio)
    
    return audio


def compute_fft_features_python(audio):
    """
    Compute FFT features matching firmware implementation.
    Uses Hanning window, non-overlapping windows, averages across all windows.
    """
    window = np.hanning(FFT_SIZE)
    num_windows = (len(audio) - FFT_SIZE) // FFT_HOP + 1
    
    # Accumulate FFT bins
    fft_accum = np.zeros(FFT_SIZE // 2 + 1)
    
    for i in range(num_windows):
        start = i * FFT_HOP
        segment = audio[start:start + FFT_SIZE] * window
        fft_out = np.fft.rfft(segment)
        magnitude = np.abs(fft_out)
        fft_accum += magnitude
    
    # Average
    avg_magnitude = fft_accum / num_windows
    return avg_magnitude


def analyze_audio(audio_data, source_name, gain_compensation=1.0):
    """
    Analyze audio data and show intermediate values at each stage.
    """
    print(f"\n{'='*60}")
    print(f"Analysis: {source_name}")
    print('='*60)
    
    # Convert to float if needed
    audio_float = audio_data.astype(np.float64)
    
    # If int16 WAV, convert back to ADC-like range first
    if np.abs(audio_float).max() > 1.0:
        # WAV was saved as: (adc - dc) / 2048 * 32767
        # Reverse: wav / 32767 gives us the ADC-normalized value
        audio_float = audio_float / 32767.0
        print(f"\n[WAV->Float] Converted from int16")
    else:
        print(f"\n[Float] Already normalized")
    
    # Apply gain compensation
    audio_float = audio_float * gain_compensation
    
    print(f"\n[INPUT] Float audio (gain={gain_compensation}):")
    print(f"  min={audio_float.min():.6f}, max={audio_float.max():.6f}")
    print(f"  mean={np.mean(audio_float):.6f}, std={np.std(audio_float):.6f}")
    
    # Run DSP pipeline
    processed = mac_shim_dsp_pipeline(audio_float)
    
    print(f"\n[DSP] After HP+LP filtering:")
    print(f"  min={processed.min():.6f}, max={processed.max():.6f}")
    print(f"  std={np.std(processed):.6f}")
    
    # RMS density
    rms_density = np.sqrt(np.mean(processed**2))
    print(f"  RMS density: {rms_density:.6f}")
    
    # FFT features
    bins = compute_fft_features_python(processed)
    
    print(f"\n[FFT] Frequency bin magnitudes (bins 4-11):")
    for i in range(4, 12):
        freq = i * SAMPLE_RATE / FFT_SIZE
        print(f"  Bin {i:2d} ({freq:6.1f} Hz): {bins[i]:.6f}")
    
    print(f"\n[SUMMARY] Key values for comparison:")
    print(f"  RMS density:  {rms_density:.6f}")
    print(f"  Bins[4-7]:    {bins[4]:.6f}, {bins[5]:.6f}, {bins[6]:.6f}, {bins[7]:.6f}")
    
    return {
        'rms_density': rms_density,
        'bins': bins,
        'processed_std': np.std(processed)
    }


def find_optimal_gain(audio_data):
    """Find gain that produces bins in the 0.02-0.06 range (Mac quiet room)."""
    print("\n" + "="*60)
    print("FINDING OPTIMAL GAIN COMPENSATION")
    print("="*60)
    print("Target: FFT bins should be ~0.02-0.06 for quiet room")
    print()
    
    best_gain = 1.0
    best_diff = float('inf')
    target = 0.04  # Middle of target range
    
    # Try different gains
    for gain in [1.0, 0.7, 0.5, 0.4, 0.35, 0.3, 0.25, 0.2, 0.15, 0.1, 0.05]:
        result = analyze_audio(audio_data, f"Gain={gain}", gain_compensation=gain)
        avg_bin = np.mean(result['bins'][4:8])
        diff = abs(avg_bin - target)
        
        if diff < best_diff:
            best_diff = diff
            best_gain = gain
        
        status = "✓ GOOD" if 0.02 <= avg_bin <= 0.08 else "✗"
        print(f"\n  >>> Gain {gain:.2f}: avg bins[4-7] = {avg_bin:.4f} {status}")
    
    print(f"\n{'='*60}")
    print(f"RECOMMENDED GAIN: {best_gain}")
    print(f"{'='*60}")
    print(f"\nSet in firmware with: g{best_gain}")
    
    return best_gain


def main():
    parser = argparse.ArgumentParser(description='BeeWatch Parity Diagnostic')
    parser.add_argument('wav_file', nargs='?', help='WAV file to analyze')
    parser.add_argument('--gain', '-g', type=float, default=1.0,
                        help='Gain compensation factor (default: 1.0, firmware default: 0.35)')
    parser.add_argument('--find-gain', action='store_true',
                        help='Find optimal gain to match Mac targets')
    
    args = parser.parse_args()
    
    if args.wav_file:
        print(f"Loading: {args.wav_file}")
        sr, audio = scipy.io.wavfile.read(args.wav_file)
        
        if sr != SAMPLE_RATE:
            print(f"Warning: Sample rate is {sr}, expected {SAMPLE_RATE}")
        
        if args.find_gain:
            find_optimal_gain(audio)
        else:
            # Single analysis with specified gain
            analyze_audio(audio, f"WAV file: {args.wav_file}", gain_compensation=args.gain)
            
            print("\n" + "-"*60)
            print("TIP: Run with --find-gain to find optimal gain compensation")
            print("     Or specify gain with -g 0.35 (firmware default)")
    
    else:
        # Show reference values
        print("\n" + "="*60)
        print("MAC SHIM REFERENCE VALUES (quiet room)")
        print("="*60)
        print("""
From mac_shim.py output, quiet room 'Normal' detection:
  Raw stats: min=-0.018, max=0.015 (amplitude ~0.02)
  Bins[4-7]: 0.023, 0.028, 0.040, 0.052

Pico output (with gain=0.35):
  ADC: Min=1950, Max=2150, Mean=~2048
  After normalization: amplitude = (2150-2048)/2048 = 0.05
  With gain 0.35: 0.05 * 0.35 = 0.0175 (close to Mac's 0.02!)

Run this with a WAV file from audio_capture.py:
  python parity_diagnostic.py pico_audio.wav --find-gain
        """)


if __name__ == "__main__":
    main()

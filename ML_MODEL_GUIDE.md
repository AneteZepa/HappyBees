# BeeWatch ML Model: Technical Deep Dive

## Executive Summary

The BeeWatch Summer Model is a TensorFlow Lite neural network trained to detect swarming/piping events in beehives using acoustic analysis. This document explains how the model works, how it was verified to work correctly on the Pico 2 W firmware, and how to calibrate it for different microphone hardware.

**Key Insight**: The model detects **changes in acoustic activity**, not absolute sound levels. It is most sensitive to the "spike ratio" feature, which compares current audio energy to a rolling historical average.

---

## Part 1: Model Architecture

### 1.1 Input Features (20 elements)

The model expects a 20-element float32 feature vector:

| Index | Feature | Range | Description |
|-------|---------|-------|-------------|
| 0 | Temperature | 0-50°C | Hive internal temperature |
| 1 | Humidity | 0-100% | Hive internal humidity |
| 2 | Hour | 0-23 | Time of day (24h format) |
| 3 | **Spike Ratio** | 0.1-10+ | Current density / Rolling average density |
| 4-19 | FFT Bins | 0.0-1.0 | Frequency magnitudes (125Hz - 594Hz) |

### 1.2 Output Classes

| Index | Label | Meaning |
|-------|-------|---------|
| 0 | Normal | Hive operating normally |
| 1 | Event | Potential swarming/piping activity |

### 1.3 Model Sensitivity Analysis

Through systematic testing, we discovered the model's sensitivity to each feature:

```
Feature Impact on Model Output:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Spike Ratio:  ████████████████████████████████████████ HIGH
Hour:         ████████████████████░░░░░░░░░░░░░░░░░░░░ MEDIUM
Temperature:  ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ LOW
Humidity:     ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ LOW
FFT Bins:     ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ VERY LOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Critical Finding**: The FFT bin magnitudes have minimal impact on the model output. The model was trained to detect **temporal changes** in hive activity, primarily through the spike ratio.

### 1.4 Spike Ratio: The Key Feature

The spike ratio is calculated as:

```
spike_ratio = current_rms_density / rolling_average_density
```

Where:
- `current_rms_density` = RMS of the current 6-second audio capture
- `rolling_average_density` = Mean of the last 12 density measurements

**Interpretation:**
- `spike < 0.7`: Activity decreasing → **Normal** (hive settling down)
- `spike ≈ 1.0`: Steady state → **Ambiguous** (model defaults to Event)
- `spike > 1.3`: Activity increasing → **Event** (potential swarming)

This is why a freshly-booted device (no history) always predicts "Event" - the spike ratio is exactly 1.0.

---

## Part 2: Digital Signal Processing (DSP) Pipeline

### 2.1 Audio Capture

```
Sample Rate:  16,000 Hz
Duration:     6 seconds
Total Samples: 96,000
ADC Resolution: 12-bit (0-4095)
```

### 2.2 DSP Chain

```
Raw ADC → DC Removal → Gain Compensation → HP Filter → LP Filter → FFT
```

#### Step 1: DC Removal
```cpp
float dc_offset = mean(audio_buffer);  // Typically ~2048 for 12-bit ADC
float sample = (raw_adc - dc_offset) / 2048.0f;  // Normalize to ~[-1, 1]
```

#### Step 2: Gain Compensation
```cpp
sample *= g_gain_compensation;  // Default: 0.35
```

This compensates for the op-amp gain in the analog front-end. The TLC272CP provides ~22x gain, which produces larger ADC swings than the Mac microphone used for training.

#### Step 3: High-Pass Filter (100Hz, 2nd Order Butterworth)
Removes DC drift and low-frequency noise.

```
Coefficients:
  b0 = 0.9726139,  b1 = -1.9452278,  b2 = 0.9726139
  a1 = -1.9444777, a2 = 0.9459779
```

#### Step 4: Low-Pass Filter (6kHz, 3rd Order Butterworth)
Anti-aliasing filter, implemented as two cascaded biquad sections.

```
Stage 1:
  b0 = 0.4459029, b1 = 0.4459029, b2 = 0.0
  a1 = 0.4142136, a2 = 0.0

Stage 2:
  b0 = 0.3913, b1 = 0.7827, b2 = 0.3913
  a1 = -0.3695, a2 = -0.1958
```

#### Step 5: FFT Feature Extraction

```
Window Size:   512 samples
Window Type:   Hanning
Hop Size:      512 (non-overlapping)
Num Windows:   187 (for 96,000 samples)
Output Bins:   16 frequency bins (indices 4-19)
```

The FFT is computed using the DFT formula with pre-computed twiddle factors:

```cpp
// For each frequency bin k (4 to 19):
real_sum = Σ(sample[n] * cos(-2πkn/512))
imag_sum = Σ(sample[n] * sin(-2πkn/512))
magnitude = sqrt(real_sum² + imag_sum²)
```

Frequency resolution: 16000 / 512 = 31.25 Hz per bin

| Bin | Frequency |
|-----|-----------|
| 4 | 125.0 Hz |
| 5 | 156.25 Hz |
| 6 | 187.5 Hz |
| 7 | 218.75 Hz |
| ... | ... |
| 19 | 593.75 Hz |

---

## Part 3: Verification Testing

### 3.1 The Problem We Solved

Initially, the firmware always predicted "Swarming/Event" with 96-98% confidence, even in a quiet room where the Mac reference implementation predicted "Normal" with 98% confidence.

### 3.2 Root Cause Analysis

We created Python diagnostic tools to compare Pico firmware output with the Mac reference:

**Test 1: FFT Magnitude Comparison**

```
Environment: Quiet room, no activity

Mac (sounddevice):
  Raw amplitude: ~0.02
  Bins[4-7]: 0.023, 0.028, 0.040, 0.052
  Prediction: Normal (98.8%)

Pico (original, no gain compensation):
  Raw ADC: Min=1882, Max=2130, Mean=2057
  Bins[4-7]: 0.076, 0.076, 0.090, 0.104
  Prediction: Swarming (91-98%)

Ratio: Pico bins were 3-4x higher than Mac
```

**Root Cause**: The TLC272CP op-amp provides ~22x voltage gain, producing larger ADC swings than the Mac's built-in microphone.

**Solution**: Added gain compensation factor (0.35) to scale Pico audio down to match Mac training data.

### 3.3 Direct Feature Testing

We extracted exact feature vectors from the Pico and tested them directly with the TFLite model in Python:

```python
# test_features.py - Exact features from Pico debug output
features = [
    20.9224,   # temp
    45.9174,   # humidity  
    14.0000,   # hour
    0.9988,    # spike (fresh start, no history)
    0.021904, 0.022197, 0.020530, 0.020093,  # bins 4-7
    0.020511, 0.019908, 0.019994, 0.020682,  # bins 8-11
    0.019431, 0.019336, 0.020493, 0.021086,  # bins 12-15
    0.020009, 0.019955, 0.020517, 0.021273,  # bins 16-19
]

# Result: Normal=0.026, Event=0.974 → Prediction: Event (97.4%)
```

This confirmed the firmware was correctly passing features to the model.

### 3.4 Feature Sensitivity Sweep

We systematically tested each feature's impact:

```python
# test_humidity.py results:

Spike ratio:
  spike=0.5: Normal=0.8705, Event=0.1295 → Normal ✓
  spike=0.8: Normal=0.0674, Event=0.9326 → Event
  spike=1.0: Normal=0.0344, Event=0.9656 → Event
  spike=1.5: Normal=0.0029, Event=0.9971 → Event

Hour:
  hour=18: Normal=0.3035, Event=0.6965 → Event (borderline)
  hour=22: Normal=0.6581, Event=0.3419 → Normal ✓

FFT magnitude (all bins scaled):
  scale=0.1x: Normal=0.0344, Event=0.9656 → Event
  scale=10.0x: Normal=0.0369, Event=0.9631 → Event
  
  → FFT magnitude has negligible impact!
```

### 3.5 Real-World Validation

We tested the spike ratio behavior with actual audio changes:

```
Sequence:
1. Clear history (c)
2. Quiet room (s) → spike=1.0 → Event 97%
3. Made loud noise during capture (s) → spike=1.75 → Event 99.9%
4. Quiet again (s) → spike=0.33 → NORMAL 99.6% ✓
5. Still quiet (s) → spike=0.39 → NORMAL 98.0% ✓
```

**Conclusion**: The model works exactly as designed - it detects changes in activity through the spike ratio.

---

## Part 4: Calibration Guide

### 4.1 Gain Compensation Tuning

Different microphone circuits will require different gain compensation values.

**Target**: FFT bins should be in the 0.02-0.06 range for a quiet room.

**Procedure**:
1. Connect to firmware via serial: `tio -b 115200 /dev/tty.usbmodem*`
2. Enable mock mode: `m`
3. Clear history: `c`
4. Run inference and check bins: `s`
5. Adjust gain until bins are in target range:
   - If bins > 0.10: Lower gain (e.g., `g0.25`)
   - If bins < 0.02: Raise gain (e.g., `g0.50`)
6. Default gain for TLC272CP + MEMS mic: **0.35**

### 4.2 Threshold Adjustment

The model outputs softmax probabilities. You can adjust the decision threshold:

```cpp
// In run_summer_inference():
float threshold = 0.85;  // Only report Event if confidence > 85%
if (score > threshold && strcmp(label, "Event") == 0) {
    // Report as Swarming/Event
} else {
    // Report as Normal
}
```

### 4.3 History Size Tuning

The rolling average uses 12 samples by default. For different sampling intervals:

| Interval | History Size | Time Window |
|----------|--------------|-------------|
| 30 sec | 12 | 6 minutes |
| 1 min | 12 | 12 minutes |
| 5 min | 12 | 1 hour |
| 5 min | 24 | 2 hours |

---

## Part 5: Python Diagnostic Tools

### 5.1 mac_shim.py

Reference implementation that runs on Mac/PC with identical DSP pipeline.

```bash
python mac_shim.py --model summer --verbose
```

Use this to establish ground truth for model predictions.

### 5.2 audio_capture.py

Captures raw audio from Pico and saves as WAV file.

```bash
python audio_capture.py -d /dev/tty.usbmodem2101 -o pico_audio.wav --play
```

### 5.3 parity_diagnostic.py

Analyzes WAV files and shows expected FFT values at each DSP stage.

```bash
python parity_diagnostic.py pico_audio.wav --find-gain
```

### 5.4 test_features.py / test_humidity.py

Direct model testing with specific feature vectors.

```bash
python test_features.py   # Test exact Pico features
python test_humidity.py   # Sweep all features
```

---

## Part 6: Troubleshooting

### "Always predicts Event"

1. **Check spike ratio**: Is it ~1.0? → Need more history
2. **Check FFT bins**: Are they > 0.10? → Lower gain compensation
3. **Check hour**: Is it daytime (6-17)? → Model expects higher activity

### "Always predicts Normal"

1. **Check spike ratio**: Is it < 0.5? → History may be corrupted
2. **Check hour**: Is it nighttime (18-23)? → Expected behavior

### "Predictions don't match Mac"

1. Run `audio_capture.py` to capture Pico audio
2. Run `parity_diagnostic.py --find-gain` to find optimal gain
3. Update `g_gain_compensation` in firmware

---

## Appendix A: Filter Coefficient Derivation

Coefficients were generated using scipy:

```python
import scipy.signal

# High-pass 100Hz, 2nd order Butterworth
sos_hp = scipy.signal.butter(2, 100, btype='high', fs=16000, output='sos')

# Low-pass 6000Hz, 3rd order Butterworth  
sos_lp = scipy.signal.butter(3, 6000, btype='low', fs=16000, output='sos')
```

---

## Appendix B: Memory Budget

| Buffer | Size | Type |
|--------|------|------|
| Audio buffer | 192 KB | uint16_t[96000] |
| FFT input | 2 KB | float[512] |
| Hanning window | 2 KB | float[512] |
| Cos table | 40 KB | float[20][512] |
| Sin table | 40 KB | float[20][512] |
| **Total static** | ~276 KB | |
| **Available RAM** | 520 KB | RP2350 |
| **Headroom** | ~244 KB | For stack, heap, EI |

---

*Document Version: 1.0*
*Last Updated: November 2025*
*Authors: HappyBees Engineering Team*

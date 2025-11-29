#!/usr/bin/env python3
"""
HappyBees Feature Testing Tool

Tests specific feature vectors directly against the TFLite model
to verify firmware parity and understand model sensitivity.

Usage:
    python tools/test_features.py
    python tools/test_features.py --sweep
    python tools/test_features.py --model-path firmware/mode_summer/tflite-model/model.tflite
"""

import argparse
import os
import numpy as np

try:
    import tensorflow.lite as tflite
except ImportError:
    print("ERROR: TensorFlow not installed. Run: pip install tensorflow")
    exit(1)


def load_model(model_path):
    """Load TFLite model."""
    interpreter = tflite.Interpreter(model_path=model_path)
    interpreter.allocate_tensors()
    return interpreter


def predict(interpreter, features, name=None):
    """Run inference and return results."""
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    input_data = np.array([features], dtype=np.float32)
    interpreter.set_tensor(input_details[0]['index'], input_data)
    interpreter.invoke()
    output = interpreter.get_tensor(output_details[0]['index'])[0]

    pred = "Normal" if output[0] > output[1] else "Event"
    conf = max(output) * 100

    if name:
        print(f"{name}:")
        print(f"  Output: Normal={output[0]:.4f}, Event={output[1]:.4f}")
        print(f"  Prediction: {pred} ({conf:.1f}%)")
        print()

    return output, pred, conf


def test_pico_features(interpreter):
    """Test exact features captured from Pico firmware."""
    print("=" * 60)
    print("TESTING PICO FIRMWARE FEATURES")
    print("=" * 60)

    pico_features = [
        20.9224, 45.9174, 14.0000, 0.9988,
        0.021904, 0.022197, 0.020530, 0.020093,
        0.020511, 0.019908, 0.019994, 0.020682,
        0.019431, 0.019336, 0.020493, 0.021086,
        0.020009, 0.019955, 0.020517, 0.021273,
    ]

    print("\nPico features (g=0.35, quiet room, fresh start):")
    print(f"  spike={pico_features[3]}")
    print(f"  bins[4-7]={pico_features[4]:.4f}, {pico_features[5]:.4f}, "
          f"{pico_features[6]:.4f}, {pico_features[7]:.4f}")
    print()

    output, pred, conf = predict(interpreter, pico_features, "Pico (spike=1.0)")

    print("-" * 60)
    print("EXPLANATION:")
    if pred == "Event":
        print("  Model predicts 'Event' because spike ratio = 1.0 (steady state).")
        print("  The model detects CHANGES in activity, not absolute levels.")
        print()
        print("  To get 'Normal' prediction:")
        print("  - Run multiple inferences to build history")
        print("  - Make noise, then go quiet (spike drops < 0.7)")
    print("-" * 60)


def sweep_features(interpreter):
    """Test model sensitivity to each feature."""
    print("\n" + "=" * 60)
    print("FEATURE SENSITIVITY SWEEP")
    print("=" * 60)

    base = [
        25.0, 50.0, 14.0, 1.0,
        0.021, 0.022, 0.021, 0.020,
        0.020, 0.020, 0.020, 0.021,
        0.019, 0.019, 0.020, 0.021,
        0.020, 0.020, 0.021, 0.021,
    ]

    print("\nBaseline:")
    predict(interpreter, base, "  base (spike=1.0)")

    # Spike ratio
    print("\n--- SPIKE RATIO (f[3]) ---")
    print("This is the PRIMARY feature the model uses.")
    for spike in [0.3, 0.5, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0]:
        f = base.copy()
        f[3] = spike
        output, pred, conf = predict(interpreter, f)
        marker = "[NORMAL]" if pred == "Normal" else ""
        print(f"  spike={spike:.1f}: Normal={output[0]:.3f}, Event={output[1]:.3f} -> {pred} {marker}")

    # Hour
    print("\n--- HOUR (f[2]) ---")
    for hour in [6, 10, 14, 18, 22]:
        f = base.copy()
        f[2] = hour
        output, pred, conf = predict(interpreter, f)
        marker = "[NORMAL]" if pred == "Normal" else ""
        print(f"  hour={hour}: Normal={output[0]:.3f}, Event={output[1]:.3f} -> {pred} {marker}")

    # Temperature
    print("\n--- TEMPERATURE (f[0]) ---")
    for temp in [15, 20, 25, 30, 35]:
        f = base.copy()
        f[0] = temp
        output, pred, conf = predict(interpreter, f)
        print(f"  temp={temp}: Normal={output[0]:.3f}, Event={output[1]:.3f} -> {pred}")

    # FFT magnitude
    print("\n--- FFT MAGNITUDE (f[4-19]) ---")
    print("Notice: FFT magnitude has minimal impact on predictions.")
    for scale in [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]:
        f = base.copy()
        for i in range(4, 20):
            f[i] = base[i] * scale
        output, pred, conf = predict(interpreter, f)
        print(f"  scale={scale:.1f}x: Normal={output[0]:.3f}, Event={output[1]:.3f} -> {pred}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
The model is most sensitive to:
1. SPIKE RATIO - Values < 0.7 strongly predict Normal
2. HOUR - Evening hours (18-22) lean toward Normal
3. Temperature/Humidity - Minor effect
4. FFT bins - Almost no effect

The model detects CHANGES in activity, not absolute sound levels.
    """)


def find_model():
    """Find the model file."""
    paths = [
        "mode_summer/tflite-model/model.tflite",
        "firmware/mode_summer/tflite-model/model.tflite",
        "../mode_summer/tflite-model/model.tflite",
        "../firmware/mode_summer/tflite-model/model.tflite",
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def main():
    parser = argparse.ArgumentParser(description="HappyBees Feature Testing")
    parser.add_argument('--sweep', action='store_true', help='Run feature sensitivity sweep')
    parser.add_argument('--model-path', default=None, help='Custom model path')
    args = parser.parse_args()

    model_path = args.model_path or find_model()
    if not model_path:
        print("ERROR: Could not find model.")
        print("Use --model-path to specify location.")
        exit(1)

    print(f"Loading model: {model_path}")
    interpreter = load_model(model_path)

    input_details = interpreter.get_input_details()
    print(f"Model expects {input_details[0]['shape'][1]} features\n")

    if args.sweep:
        sweep_features(interpreter)
    else:
        test_pico_features(interpreter)


if __name__ == "__main__":
    main()

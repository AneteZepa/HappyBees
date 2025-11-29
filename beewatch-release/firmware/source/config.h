/**
 * BeeWatch Firmware Configuration
 * 
 * Hardware and software settings for the BeeWatch edge node.
 */

#ifndef CONFIG_H
#define CONFIG_H

// =============================================================================
// AUDIO SETTINGS
// =============================================================================

#define SAMPLE_RATE_HZ       16000    // 16kHz sample rate
#define CAPTURE_SECONDS      6        // 6 seconds of audio
#define TOTAL_SAMPLES        (SAMPLE_RATE_HZ * CAPTURE_SECONDS)  // 96,000 samples
#define TOTAL_BUFFER_BYTES   (TOTAL_SAMPLES * sizeof(uint16_t))  // 192KB

// FFT Settings
#define FFT_SIZE             512      // 512-point FFT
#define FFT_HOP              512      // Non-overlapping windows
#define NUM_FREQ_BINS        20       // Bins 0-19 (we use 4-19)

// =============================================================================
// ML SETTINGS
// =============================================================================

#define HISTORY_SIZE         12       // Rolling average window size
#define CONFIDENCE_THRESHOLD 0.60f    // Minimum confidence for Event detection

// Default gain compensation for TLC272CP op-amp circuit
// Calibrate for your specific hardware with 'g' command
#define DEFAULT_GAIN         0.35f

// =============================================================================
// HARDWARE PINS
// =============================================================================

// Microphone (ADC)
#define MIC_PIN              26       // GPIO26 = ADC0
#define ADC_CHANNEL          0

// I2C for SHT20 sensor
#define I2C_INST             i2c0
#define SHT_SDA_PIN          4
#define SHT_SCL_PIN          5
#define SHT_ADDR             0x44

// =============================================================================
// NETWORK SETTINGS
// =============================================================================

#define DEFAULT_SERVER_PORT  8000
#define SYNC_INTERVAL_MS     2000     // Poll server every 2 seconds
#define HTTP_TIMEOUT_MS      3000     // HTTP request timeout
#define HTTP_BUF_SIZE        4096     // HTTP receive buffer

// =============================================================================
// BACKGROUND SAMPLING
// =============================================================================

#define BACKGROUND_SAMPLE_INTERVAL_MS  60000  // Sample every 1 minute when enabled

// =============================================================================
// DERIVED CONSTANTS (do not edit)
// =============================================================================

#define AUDIO_BUFFER_SIZE    TOTAL_SAMPLES
#define NUM_WINDOWS          ((TOTAL_SAMPLES - FFT_SIZE) / FFT_HOP + 1)

#endif // CONFIG_H

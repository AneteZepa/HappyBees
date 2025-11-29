/**
 * HappyBees Firmware Configuration
 */

#ifndef CONFIG_H
#define CONFIG_H

// Audio
#define SAMPLE_RATE_HZ       16000
#define CAPTURE_SECONDS      6
#define TOTAL_SAMPLES        (SAMPLE_RATE_HZ * CAPTURE_SECONDS)
#define TOTAL_BUFFER_BYTES   (TOTAL_SAMPLES * sizeof(uint16_t))

// FFT
#define FFT_SIZE             512
#define FFT_HOP              512
#define NUM_FREQ_BINS        20

// ML
#define HISTORY_SIZE         12
#define CONFIDENCE_THRESHOLD 0.60f
#define DEFAULT_GAIN         0.35f

// Hardware Pins
#define MIC_PIN              26
#define ADC_CHANNEL          0
#define I2C_INST             i2c0
#define SHT_SDA_PIN          4
#define SHT_SCL_PIN          5
#define SHT_ADDR             0x44

// Network
#define DEFAULT_SERVER_PORT  8000
#define SYNC_INTERVAL_MS     2000
#define HTTP_TIMEOUT_MS      3000
#define HTTP_BUF_SIZE        4096

// Background Sampling
#define BACKGROUND_SAMPLE_INTERVAL_MS  60000

// Derived
#define AUDIO_BUFFER_SIZE    TOTAL_SAMPLES
#define NUM_WINDOWS          ((TOTAL_SAMPLES - FFT_SIZE) / FFT_HOP + 1)

#endif

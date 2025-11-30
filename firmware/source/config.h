#ifndef CONFIG_H
#define CONFIG_H

// --- System ---
#define FIRMWARE_VERSION     "v0.2-MCU"
#define SAMPLE_RATE_HZ       16000
#define CAPTURE_SECONDS      6
#define AUDIO_BUFFER_SIZE    (SAMPLE_RATE_HZ * CAPTURE_SECONDS) 

// --- Pinout (Matches wiring.md) ---
#define MIC_PIN              26     // ADC0
#define ADC_CHANNEL          0
#define SHT_SDA_PIN          4      // GP4
#define SHT_SCL_PIN          5      // GP5
#define I2C_INST             i2c0

// --- FFT & Features ---
#define FFT_SIZE             512
#define FFT_HOP              512    // Non-overlapping for simplicity in V0
#define NUM_FREQ_BINS        16
#define HISTORY_SIZE         12     // For rolling averages

// --- SHT3x Sensor ---
#define SHT3X_ADDR           0x44
// Command: Clock Stretch Disabled (0x24), High Repeatability (0x00)
#define SHT3X_CMD_MSB        0x24
#define SHT3X_CMD_LSB        0x00

#endif

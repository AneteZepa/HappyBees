/*
 * BeeWatch Firmware V0.6.0 - RP2350 (Pico 2 W)
 * 
 * FIXES:
 * - Added gain compensation to match Mac mic levels
 * - The 22x op-amp gain causes FFT magnitudes to be ~2.5x higher than Mac
 * - Default compensation factor: 0.4 (adjustable with 'g' command)
 * 
 * FEATURES:
 * - Mock sensor mode ('m' command) for exact parity testing with mac_shim.py
 * - Audio streaming ('a' command) to verify mic/ADC quality
 * - Gain compensation ('g' command) to match Mac mic levels
 * 
 * TESTING WORKFLOW:
 * 1. Use 'm' to enable mock mode (temp=25.0, humidity=50.0)
 * 2. Use 'c' to clear history
 * 3. Run 's' and compare FFT bins with mac_shim.py
 * 4. Adjust 'g' factor until bins match (e.g., g0.3 or g0.5)
 */

#include <stdio.h>
#include <math.h>
#include <vector>
#include <numeric>
#include <string.h>

#include "pico/stdlib.h"
#include "hardware/adc.h"
#include "hardware/dma.h"
#include "hardware/i2c.h"
#include "pico/cyw43_arch.h"

// Edge Impulse SDK
#include "edge-impulse-sdk/classifier/ei_run_classifier.h"
#include "edge-impulse-sdk/dsp/numpy.hpp"

// --- CONFIGURATION ---
#define SAMPLE_RATE_HZ      16000
#define CAPTURE_SECONDS     6
#define AUDIO_BUFFER_SIZE   (SAMPLE_RATE_HZ * CAPTURE_SECONDS)  // 96,000 samples
#define FFT_SIZE            512
#define FFT_HOP             512  // Non-overlapping, matches Python
#define HISTORY_SIZE        12
#define NUM_FREQ_BINS       20

// Hardware Pins
#define MIC_PIN             26
#define ADC_CHANNEL         0
#define SHT_SDA_PIN         4
#define SHT_SCL_PIN         5
#define I2C_INST            i2c0
#define SHT_ADDR            0x44

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

// --- STATIC BUFFERS ---
static uint16_t g_audio_buffer[AUDIO_BUFFER_SIZE];
static float g_fft_input[FFT_SIZE];
static float g_hanning_window[FFT_SIZE];

// Feature vectors
static float g_features_summer[20];
static float g_features_winter[5];

// Accumulated FFT magnitudes (use double for precision during accumulation)
static double g_bin_accum[NUM_FREQ_BINS];

// History for rolling averages
static std::vector<float> g_density_history;
static std::vector<float> g_temp_history;

// Climate readings
static float g_last_temp = 0.0f;
static float g_last_hum = 0.0f;

// DMA
static int g_dma_chan;
static dma_channel_config g_dma_cfg;

// --- MOCK MODE ---
// When enabled, uses fixed values matching mac_shim.py defaults
static bool g_mock_mode = false;
static float g_mock_temp = 25.0f;
static float g_mock_hum = 50.0f;
static float g_mock_hour = 14.0f;

// --- GAIN COMPENSATION ---
// The TLC272CP op-amp provides ~22x gain, which produces larger ADC swings
// than the Mac's built-in microphone. We need to scale down to match.
// 
// Calibration based on testing:
// - Mac quiet room bins: ~0.02-0.05
// - Pico with gain=1.0: ~0.28-0.34  
// - Pico with gain=0.4: ~0.11-0.14 (still too high)
// - Optimal: ~0.15 to get bins in 0.02-0.05 range
//
// Adjust with 'g' command during testing (e.g., g0.15)
static float g_gain_compensation = 0.15f;

// Filter coefficients (scipy.signal.butter generated)
// HP: 2nd order Butterworth @ 100Hz
static const float HP_B0 = 0.9726139f;
static const float HP_B1 = -1.9452278f;
static const float HP_B2 = 0.9726139f;
static const float HP_A1 = -1.9444777f;
static const float HP_A2 = 0.9459779f;

// LP: 3rd order Butterworth @ 6000Hz (2 stages)
// Stage 1 (1st order section)
static const float LP1_B0 = 0.4459029f;
static const float LP1_B1 = 0.4459029f;
static const float LP1_B2 = 0.0f;
static const float LP1_A1 = 0.4142136f;
static const float LP1_A2 = 0.0f;

// Stage 2 (2nd order section) 
static const float LP2_B0 = 0.3913f;
static const float LP2_B1 = 0.7827f;
static const float LP2_B2 = 0.3913f;
static const float LP2_A1 = -0.3695f;
static const float LP2_A2 = -0.1958f;

// Filter state (Direct Form II Transposed)
static float hp_w1 = 0, hp_w2 = 0;
static float lp1_w1 = 0;
static float lp2_w1 = 0, lp2_w2 = 0;

// Pre-computed DFT twiddle factors for bins 0-19
static float g_cos_table[NUM_FREQ_BINS][FFT_SIZE];
static float g_sin_table[NUM_FREQ_BINS][FFT_SIZE];

// --- UTILITY FUNCTIONS ---

static void led_set(bool on) {
    cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, on);
}

static void reset_filters() {
    hp_w1 = hp_w2 = 0;
    lp1_w1 = 0;
    lp2_w1 = lp2_w2 = 0;
}

// Biquad filter (Direct Form II Transposed)
static inline float biquad_hp(float x) {
    float y = HP_B0 * x + hp_w1;
    hp_w1 = HP_B1 * x - HP_A1 * y + hp_w2;
    hp_w2 = HP_B2 * x - HP_A2 * y;
    return y;
}

static inline float biquad_lp1(float x) {
    float y = LP1_B0 * x + lp1_w1;
    lp1_w1 = LP1_B1 * x - LP1_A1 * y;
    return y;
}

static inline float biquad_lp2(float x) {
    float y = LP2_B0 * x + lp2_w1;
    lp2_w1 = LP2_B1 * x - LP2_A1 * y + lp2_w2;
    lp2_w2 = LP2_B2 * x - LP2_A2 * y;
    return y;
}

// --- HARDWARE SETUP ---

static void setup_hardware() {
    stdio_init_all();
    sleep_ms(2000);
    
    printf("\n[INIT] BeeWatch Firmware V0.6.0\n");
    
    if (cyw43_arch_init()) {
        printf("[ERR] WiFi init failed\n");
    }
    
    // I2C for SHT sensor
    i2c_init(I2C_INST, 100 * 1000);
    gpio_set_function(SHT_SDA_PIN, GPIO_FUNC_I2C);
    gpio_set_function(SHT_SCL_PIN, GPIO_FUNC_I2C);
    gpio_pull_up(SHT_SDA_PIN);
    gpio_pull_up(SHT_SCL_PIN);
    
    // ADC for microphone
    adc_init();
    adc_gpio_init(MIC_PIN);
    adc_select_input(ADC_CHANNEL);
    
    // DMA for audio capture
    g_dma_chan = dma_claim_unused_channel(true);
    g_dma_cfg = dma_channel_get_default_config(g_dma_chan);
    channel_config_set_transfer_data_size(&g_dma_cfg, DMA_SIZE_16);
    channel_config_set_read_increment(&g_dma_cfg, false);
    channel_config_set_write_increment(&g_dma_cfg, true);
    channel_config_set_dreq(&g_dma_cfg, DREQ_ADC);
    
    // Pre-compute Hanning window (EXACT same as numpy.hanning)
    for (int i = 0; i < FFT_SIZE; i++) {
        g_hanning_window[i] = 0.5f * (1.0f - cosf(2.0f * (float)M_PI * (float)i / (float)(FFT_SIZE - 1)));
    }
    
    // Pre-compute DFT twiddle factors for bins 0-19
    for (int k = 0; k < NUM_FREQ_BINS; k++) {
        for (int n = 0; n < FFT_SIZE; n++) {
            double angle = -2.0 * M_PI * k * n / FFT_SIZE;
            g_cos_table[k][n] = (float)cos(angle);
            g_sin_table[k][n] = (float)sin(angle);
        }
    }
    
    printf("[INIT] Setup complete\n");
}

// --- SENSOR READING ---

static bool read_climate() {
    // If mock mode is enabled, use mock values
    if (g_mock_mode) {
        g_last_temp = g_mock_temp;
        g_last_hum = g_mock_hum;
        printf("[SENSOR] MOCK MODE: Temp=%.2f C, Humidity=%.2f %%\n", g_last_temp, g_last_hum);
        return true;
    }
    
    uint8_t cmd[2] = {0x24, 0x00};
    
    int ret = i2c_write_blocking(I2C_INST, SHT_ADDR, cmd, 2, false);
    if (ret == PICO_ERROR_GENERIC) {
        printf("[WARN] SHT not connected, using defaults\n");
        g_last_temp = 25.0f;
        g_last_hum = 50.0f;
        return false;
    }
    
    sleep_ms(15);
    
    uint8_t data[6];
    ret = i2c_read_blocking(I2C_INST, SHT_ADDR, data, 6, false);
    if (ret == PICO_ERROR_GENERIC) {
        return false;
    }
    
    uint16_t t_raw = (data[0] << 8) | data[1];
    uint16_t h_raw = (data[3] << 8) | data[4];
    
    g_last_temp = -45.0f + (175.0f * (float)t_raw / 65535.0f);
    g_last_hum = 100.0f * ((float)h_raw / 65535.0f);
    g_last_hum = fminf(100.0f, fmaxf(0.0f, g_last_hum));
    
    printf("[SENSOR] Temp: %.2f C, Humidity: %.2f %%\n", g_last_temp, g_last_hum);
    return true;
}

// --- AUDIO CAPTURE ---

static void capture_audio() {
    printf("\n[REC] Capturing %d samples (%.1f seconds)...\n", 
           AUDIO_BUFFER_SIZE, (float)CAPTURE_SECONDS);
    led_set(true);
    
    adc_fifo_drain();
    adc_fifo_setup(true, true, 1, false, false);
    adc_set_clkdiv(3000.0f - 1.0f);  // 48MHz / 16kHz = 3000
    
    dma_channel_configure(g_dma_chan, &g_dma_cfg, 
                          g_audio_buffer, &adc_hw->fifo, 
                          AUDIO_BUFFER_SIZE, true);
    adc_run(true);
    dma_channel_wait_for_finish_blocking(g_dma_chan);
    adc_run(false);
    
    led_set(false);
    
    uint32_t sum = 0;
    uint16_t min_val = 4095, max_val = 0;
    for (int i = 0; i < AUDIO_BUFFER_SIZE; i++) {
        sum += g_audio_buffer[i];
        if (g_audio_buffer[i] < min_val) min_val = g_audio_buffer[i];
        if (g_audio_buffer[i] > max_val) max_val = g_audio_buffer[i];
    }
    float mean = (float)sum / AUDIO_BUFFER_SIZE;
    printf("[REC] Complete. Min=%u, Max=%u, Mean=%.1f\n", min_val, max_val, mean);
}

// --- AUDIO STREAMING (for playback verification) ---

static void stream_audio(int seconds) {
    if (seconds <= 0 || seconds > 6) {
        seconds = 6;
    }
    
    int samples = seconds * SAMPLE_RATE_HZ;
    if (samples > AUDIO_BUFFER_SIZE) {
        samples = AUDIO_BUFFER_SIZE;
    }
    
    printf("[STREAM] Capturing %d samples...\n", samples);
    led_set(true);
    
    adc_fifo_drain();
    adc_fifo_setup(true, true, 1, false, false);
    adc_set_clkdiv(3000.0f - 1.0f);
    
    dma_channel_configure(g_dma_chan, &g_dma_cfg,
                          g_audio_buffer, &adc_hw->fifo,
                          samples, true);
    adc_run(true);
    dma_channel_wait_for_finish_blocking(g_dma_chan);
    adc_run(false);
    
    led_set(false);
    
    // Calculate stats
    uint32_t sum = 0;
    uint16_t min_val = 4095, max_val = 0;
    for (int i = 0; i < samples; i++) {
        sum += g_audio_buffer[i];
        if (g_audio_buffer[i] < min_val) min_val = g_audio_buffer[i];
        if (g_audio_buffer[i] > max_val) max_val = g_audio_buffer[i];
    }
    float mean = (float)sum / samples;
    
    uint64_t var_sum = 0;
    for (int i = 0; i < samples; i++) {
        float diff = g_audio_buffer[i] - mean;
        var_sum += (uint64_t)(diff * diff);
    }
    float std_dev = sqrtf((float)var_sum / samples);
    
    printf("[STREAM] Stats: Min=%u, Max=%u, StdDev=%.1f\n", min_val, max_val, std_dev);
    
    // Flush text output
    stdio_flush();
    sleep_ms(50);
    
    // Send header for Python receiver
    uint32_t payload_bytes = samples * 2;
    printf("HDR:%u:%u:%.1f\n", payload_bytes, samples, std_dev);
    stdio_flush();
    sleep_ms(10);
    
    // Stream raw binary audio (little-endian uint16)
    for (int i = 0; i < samples; i++) {
        uint16_t sample = g_audio_buffer[i];
        putchar_raw(sample & 0xFF);
        putchar_raw((sample >> 8) & 0xFF);
    }
    
    stdio_flush();
    sleep_ms(10);
    
    printf("\nEND\n");
    printf("[STREAM] Transfer complete.\n");
}

// --- DSP PROCESSING ---

static float compute_bin_magnitude_accurate(const float* windowed_data, int k) {
    double real_sum = 0.0;
    double imag_sum = 0.0;
    
    for (int n = 0; n < FFT_SIZE; n++) {
        real_sum += windowed_data[n] * g_cos_table[k][n];
        imag_sum += windowed_data[n] * g_sin_table[k][n];
    }
    
    return (float)sqrt(real_sum * real_sum + imag_sum * imag_sum);
}

static float process_and_compute_features() {
    printf("[DSP] Processing audio...\n");
    
    // Reset accumulators
    for (int k = 0; k < NUM_FREQ_BINS; k++) {
        g_bin_accum[k] = 0.0;
    }
    
    // Step 1: Calculate DC offset from raw ADC
    double dc_sum = 0;
    for (int i = 0; i < AUDIO_BUFFER_SIZE; i++) {
        dc_sum += g_audio_buffer[i];
    }
    float dc_offset = (float)(dc_sum / AUDIO_BUFFER_SIZE);
    printf("[DSP] DC offset: %.1f (gain compensation: %.2f)\n", dc_offset, g_gain_compensation);
    
    int num_windows = (AUDIO_BUFFER_SIZE - FFT_SIZE) / FFT_HOP + 1;
    printf("[DSP] Windows: %d\n", num_windows);
    
    // Reset filters ONCE before the entire stream
    reset_filters();
    
    double rms_sum = 0.0;
    int rms_count = 0;
    
    for (int w = 0; w < num_windows; w++) {
        int offset = w * FFT_HOP;
        
        for (int i = 0; i < FFT_SIZE; i++) {
            // Normalize ADC to -1..1 and apply gain compensation
            // The op-amp gain is ~22x, so we scale down to match Mac mic levels
            float sample = ((float)g_audio_buffer[offset + i] - dc_offset) / 2048.0f;
            sample *= g_gain_compensation;  // Scale to match Mac mic levels
            
            // Apply filters
            sample = biquad_hp(sample);
            sample = biquad_lp1(sample);
            sample = biquad_lp2(sample);
            
            // Accumulate for RMS (before windowing)
            rms_sum += sample * sample;
            rms_count++;
            
            // Apply Hanning window for FFT
            g_fft_input[i] = sample * g_hanning_window[i];
        }
        
        // Compute DFT for bins 0-19
        for (int k = 0; k < NUM_FREQ_BINS; k++) {
            float mag = compute_bin_magnitude_accurate(g_fft_input, k);
            g_bin_accum[k] += mag;
        }
    }
    
    // Calculate RMS density
    float current_density = sqrtf((float)(rms_sum / rms_count));
    printf("[DSP] RMS density: %.6f\n", current_density);
    
    // Average the accumulated magnitudes
    for (int k = 0; k < NUM_FREQ_BINS; k++) {
        g_bin_accum[k] /= num_windows;
    }
    
    printf("[DSP] Bins[4-7]: %.6f, %.6f, %.6f, %.6f\n",
           g_bin_accum[4], g_bin_accum[5], g_bin_accum[6], g_bin_accum[7]);
    
    return current_density;
}

// --- INFERENCE ---

static void run_summer_inference(float current_density) {
    printf("[AI] Building feature vector...\n");
    
    // Update density history
    if (g_density_history.size() >= HISTORY_SIZE) {
        g_density_history.erase(g_density_history.begin());
    }
    g_density_history.push_back(current_density);
    
    // Calculate rolling average
    float rolling_avg = 0.0f;
    if (!g_density_history.empty()) {
        for (float d : g_density_history) {
            rolling_avg += d;
        }
        rolling_avg /= g_density_history.size();
    } else {
        rolling_avg = current_density;  // First run: use current as baseline
    }
    
    // Calculate spike ratio
    float spike_ratio = current_density / (rolling_avg + 1e-6f);
    
    // Build feature vector
    // Use mock values if mock mode is enabled
    float temp = g_mock_mode ? g_mock_temp : g_last_temp;
    float hum = g_mock_mode ? g_mock_hum : g_last_hum;
    float hour = g_mock_mode ? g_mock_hour : 14.0f;
    
    g_features_summer[0] = temp;
    g_features_summer[1] = hum;
    g_features_summer[2] = hour;
    g_features_summer[3] = spike_ratio;
    
    // FFT bins 4-19 (16 frequency features)
    for (int i = 0; i < 16; i++) {
        g_features_summer[4 + i] = (float)g_bin_accum[4 + i];
    }
    
    printf("[AI] Features: temp=%.1f, hum=%.1f, hour=%.1f, spike=%.3f\n",
           g_features_summer[0], g_features_summer[1], 
           g_features_summer[2], g_features_summer[3]);
    printf("[AI] FFT[4-7]: %.6f, %.6f, %.6f, %.6f\n",
           g_features_summer[4], g_features_summer[5],
           g_features_summer[6], g_features_summer[7]);
    
    // Run Edge Impulse classifier
    signal_t signal;
    numpy::signal_from_buffer(g_features_summer, 20, &signal);
    
    ei_impulse_result_t result = {0};
    EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
    
    if (err != EI_IMPULSE_OK) {
        printf("[ERR] Classifier failed: %d\n", err);
        return;
    }
    
    // Find best classification
    const char* best_label = "Unknown";
    float best_score = -1.0f;
    int best_idx = 0;
    
    for (size_t ix = 0; ix < EI_CLASSIFIER_LABEL_COUNT; ix++) {
        if (result.classification[ix].value > best_score) {
            best_score = result.classification[ix].value;
            best_label = result.classification[ix].label;
            best_idx = ix;
        }
    }
    
    // Determine display status
    const char* status;
    const char* emoji;
    if (strcmp(best_label, "Event") == 0 || best_idx == 1) {
        status = "SWARMING / PIPING";
        emoji = "!!";
    } else {
        status = "NORMAL STATE";
        emoji = "OK";
    }
    
    // Print results
    printf("\n");
    printf("==================== HIVE STATUS ====================\n");
    printf("State:          [%s] %s\n", emoji, status);
    printf("Confidence:     %.1f%%\n", best_score * 100.0f);
    printf("Activity(Spike):%.2f\n", spike_ratio);
    if (g_mock_mode) {
        printf("Mode:           MOCK (temp=%.1f, hum=%.1f)\n", g_mock_temp, g_mock_hum);
    }
    printf("-----------------------------------------------------\n");
    printf("Raw Probs:      [");
    for (size_t ix = 0; ix < EI_CLASSIFIER_LABEL_COUNT; ix++) {
        printf("%s: %.3f", result.classification[ix].label, result.classification[ix].value);
        if (ix != EI_CLASSIFIER_LABEL_COUNT - 1) printf(", ");
    }
    printf("]\n");
    printf("=====================================================\n");
    printf("JSON_OUT:{\"status\":\"%s\",\"conf\":%.3f,\"spike\":%.3f,\"mock\":%s}\n",
           status, best_score, spike_ratio, g_mock_mode ? "true" : "false");
}

static void run_winter_inference(float current_density) {
    printf("[AI] Running winter model...\n");
    
    float temp = g_mock_mode ? g_mock_temp : g_last_temp;
    float hum = g_mock_mode ? g_mock_hum : g_last_hum;
    
    // Update temperature history
    if (g_temp_history.size() >= HISTORY_SIZE) {
        g_temp_history.erase(g_temp_history.begin());
    }
    g_temp_history.push_back(temp);
    
    // Calculate temperature stability (variance)
    float temp_stability = 0.0f;
    if (g_temp_history.size() >= 2) {
        float mean = 0.0f;
        for (float t : g_temp_history) mean += t;
        mean /= g_temp_history.size();
        
        for (float t : g_temp_history) {
            float diff = t - mean;
            temp_stability += diff * diff;
        }
        temp_stability /= g_temp_history.size();
    }
    
    // Calculate heater power
    float heater_power = (float)(g_bin_accum[6] + g_bin_accum[7] + g_bin_accum[8]);
    float heater_ratio = heater_power / (current_density + 1e-6f);
    
    g_features_winter[0] = temp;
    g_features_winter[1] = hum;
    g_features_winter[2] = temp_stability;
    g_features_winter[3] = heater_power;
    g_features_winter[4] = heater_ratio;
    
    signal_t signal;
    numpy::signal_from_buffer(g_features_winter, 5, &signal);
    
    ei_impulse_result_t result = {0};
    run_classifier(&signal, &result, false);
    
    printf("INF:{\"model\":\"winter\",\"anomaly\":%.2f,\"mock\":%s}\n", 
           result.anomaly, g_mock_mode ? "true" : "false");
}

// Debug command to dump raw features
static void debug_features() {
    printf("\n[DEBUG] Full feature dump:\n");
    read_climate();
    capture_audio();
    float density = process_and_compute_features();
    
    float temp = g_mock_mode ? g_mock_temp : g_last_temp;
    float hum = g_mock_mode ? g_mock_hum : g_last_hum;
    float hour = g_mock_mode ? g_mock_hour : 14.0f;
    float spike = density / (density + 1e-6f);
    
    printf("\n--- FEATURE VECTOR (20 elements) ---\n");
    printf("MODE: %s\n", g_mock_mode ? "MOCK" : "REAL SENSOR");
    printf("f[0] temp:       %.4f\n", temp);
    printf("f[1] humidity:   %.4f\n", hum);
    printf("f[2] hour:       %.4f\n", hour);
    printf("f[3] spike:      %.4f (density=%.6f)\n", spike, density);
    
    for (int i = 0; i < 16; i++) {
        float freq = (4 + i) * SAMPLE_RATE_HZ / (float)FFT_SIZE;
        printf("f[%d] hz_%.0f:   %.6f\n", 4 + i, freq, g_bin_accum[4 + i]);
    }
    printf("-----------------------------------\n");
}

// Toggle mock mode
static void toggle_mock_mode() {
    g_mock_mode = !g_mock_mode;
    if (g_mock_mode) {
        printf("[CONFIG] Mock mode ENABLED\n");
        printf("  Temp: %.1f C, Humidity: %.1f %%, Hour: %.1f\n",
               g_mock_temp, g_mock_hum, g_mock_hour);
        printf("  (Matches mac_shim.py defaults for parity testing)\n");
    } else {
        printf("[CONFIG] Mock mode DISABLED (using real sensors)\n");
    }
}

// Set mock values
static void set_mock_values(float temp, float hum, float hour) {
    g_mock_temp = temp;
    g_mock_hum = hum;
    g_mock_hour = hour;
    printf("[CONFIG] Mock values updated: temp=%.1f, hum=%.1f, hour=%.1f\n",
           g_mock_temp, g_mock_hum, g_mock_hour);
}

// Clear history for fresh parity test
static void clear_history() {
    g_density_history.clear();
    g_temp_history.clear();
    printf("[CONFIG] History cleared. Ready for fresh parity test.\n");
}

// --- MAIN ---

int main() {
    setup_hardware();
    
    printf("\n");
    printf("========================================\n");
    printf("  BEEWATCH V0.6.0 - GAIN CALIBRATION\n");
    printf("========================================\n");
    printf("\nCommands:\n");
    printf("  's' - Run Summer model inference\n");
    printf("  'w' - Run Winter model inference\n");
    printf("  't' - Read temperature/humidity\n");
    printf("  'd' - Debug feature dump\n");
    printf("  'a' - Stream audio to PC (for playback)\n");
    printf("  'm' - Toggle mock mode (for parity testing)\n");
    printf("  'c' - Clear history (fresh start)\n");
    printf("  'g' - Show/set gain compensation (e.g. g0.4)\n");
    printf("  'p' - Ping\n");
    printf("\nParity Test Workflow:\n");
    printf("  1. Type 'm' to enable mock mode\n");
    printf("  2. Type 'c' to clear history\n");
    printf("  3. Adjust 'g' if FFT magnitudes don't match\n");
    printf("  4. Play audio and type 's'\n");
    printf("  5. Compare output with mac_shim.py\n");
    printf("> ");
    
    char cmd_buffer[64];
    int ptr = 0;
    
    while (true) {
        int c = getchar_timeout_us(1000);
        
        if (c != PICO_ERROR_TIMEOUT) {
            if (c == '\n' || c == '\r') {
                printf("\n");
                cmd_buffer[ptr] = '\0';
                
                if (ptr > 0) {
                    char cmd = cmd_buffer[0];
                    
                    switch (cmd) {
                        case 's':
                        case 'S':
                            read_climate();
                            capture_audio();
                            {
                                float density = process_and_compute_features();
                                run_summer_inference(density);
                            }
                            break;
                            
                        case 'w':
                        case 'W':
                            read_climate();
                            capture_audio();
                            {
                                float density = process_and_compute_features();
                                run_winter_inference(density);
                            }
                            break;
                            
                        case 't':
                        case 'T':
                            read_climate();
                            break;
                            
                        case 'd':
                        case 'D':
                            debug_features();
                            break;
                            
                        case 'a':
                        case 'A':
                            // Stream audio - parse optional seconds argument
                            {
                                int secs = 6;
                                if (ptr > 1) {
                                    secs = atoi(cmd_buffer + 1);
                                }
                                stream_audio(secs);
                            }
                            break;
                            
                        case 'm':
                        case 'M':
                            toggle_mock_mode();
                            break;
                            
                        case 'c':
                        case 'C':
                            clear_history();
                            break;
                            
                        case 'p':
                        case 'P':
                            printf("PONG v0.6.0 mock=%s gain=%.2f\n", g_mock_mode ? "on" : "off", g_gain_compensation);
                            break;
                            
                        case 'v':
                        case 'V':
                            // Set mock values: v25.0,50.0,14.0
                            if (ptr > 1) {
                                float t, h, hr;
                                if (sscanf(cmd_buffer + 1, "%f,%f,%f", &t, &h, &hr) == 3) {
                                    set_mock_values(t, h, hr);
                                } else {
                                    printf("Usage: v<temp>,<hum>,<hour> e.g. v25.0,50.0,14.0\n");
                                }
                            }
                            break;
                        
                        case 'g':
                        case 'G':
                            // Set gain compensation: g0.4
                            if (ptr > 1) {
                                float new_gain = atof(cmd_buffer + 1);
                                if (new_gain > 0.0f && new_gain <= 2.0f) {
                                    g_gain_compensation = new_gain;
                                    printf("[CONFIG] Gain compensation set to: %.3f\n", g_gain_compensation);
                                } else {
                                    printf("Gain must be between 0.01 and 2.0\n");
                                }
                            } else {
                                printf("Current gain compensation: %.3f\n", g_gain_compensation);
                                printf("Usage: g<value> e.g. g0.4\n");
                            }
                            break;
                            
                        default:
                            printf("Unknown command: %c\n", cmd);
                            printf("Type 's', 'w', 't', 'd', 'a', 'm', 'c', 'g', 'p', or 'v'\n");
                            break;
                    }
                }
                
                ptr = 0;
                printf("> ");
            } else {
                if (ptr < 63) {
                    putchar(c);
                    cmd_buffer[ptr++] = (char)c;
                }
            }
        }
    }
    
    return 0;
}

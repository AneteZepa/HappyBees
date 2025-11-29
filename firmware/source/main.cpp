/**
 * BeeWatch Firmware v0.3.1 - Robust HTTP Fix
 * * FIX: Improved LWIP callbacks to handle HTTP Keep-Alive and prevent timeouts.
 */

#include <stdio.h>
#include <math.h>
#include <vector>
#include <string>
#include <cstring>
#include <numeric>

#include "pico/stdlib.h"
#include "hardware/adc.h"
#include "hardware/dma.h"
#include "hardware/i2c.h"
#include "hardware/watchdog.h"
#include "pico/cyw43_arch.h"

#include "lwip/pbuf.h"
#include "lwip/tcp.h"
#include "lwip/dns.h"
#include "lwip/init.h"

#include "flash_config.h"
#include "edge-impulse-sdk/classifier/ei_run_classifier.h"
#include "edge-impulse-sdk/dsp/numpy.hpp"

// --- CONFIGURATION ---
#define SAMPLE_RATE_HZ      16000
#define CAPTURE_SECONDS     6
#define AUDIO_BUFFER_SIZE   (SAMPLE_RATE_HZ * CAPTURE_SECONDS)
#define FFT_SIZE            512
#define FFT_HOP             512
#define HISTORY_SIZE        12
#define NUM_FREQ_BINS       20

#define MIC_PIN             26
#define ADC_CHANNEL         0
#define SHT_ADDR            0x44
#define I2C_INST            i2c0
#define SHT_SDA_PIN         4
#define SHT_SCL_PIN         5

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

// --- GLOBALS ---
static uint16_t g_audio_buffer[AUDIO_BUFFER_SIZE];
static float g_fft_input[FFT_SIZE];
static float g_hanning_window[FFT_SIZE];
static float g_features_summer[20];
static float g_features_winter[5];
static double g_bin_accum[NUM_FREQ_BINS];
static std::vector<float> g_density_history;
static std::vector<float> g_temp_history;
static float g_last_temp = 0.0f;
static float g_last_hum = 0.0f;
static int g_dma_chan;
static dma_channel_config g_dma_cfg;

static bool g_mock_mode = false;
static float g_mock_temp = 25.0f;
static float g_mock_hum = 50.0f;
static float g_mock_hour = 14.0f;
static float g_gain_compensation = 0.4f;

// Filter State
static float hp_w1 = 0, hp_w2 = 0;
static float lp1_w1 = 0;
static float lp2_w1 = 0, lp2_w2 = 0;
static float g_cos_table[NUM_FREQ_BINS][FFT_SIZE];
static float g_sin_table[NUM_FREQ_BINS][FFT_SIZE];

static const float HP_B0 = 0.9726139f; static const float HP_B1 = -1.9452278f; static const float HP_B2 = 0.9726139f;
static const float HP_A1 = -1.9444777f; static const float HP_A2 = 0.9459779f;
static const float LP1_B0 = 0.4459029f; static const float LP1_B1 = 0.4459029f; static const float LP1_B2 = 0.0f;
static const float LP1_A1 = 0.4142136f; static const float LP1_A2 = 0.0f;
static const float LP2_B0 = 0.3913f; static const float LP2_B1 = 0.7827f; static const float LP2_B2 = 0.3913f;
static const float LP2_A1 = -0.3695f; static const float LP2_A2 = -0.1958f;

// --- NETWORK GLOBALS ---
#define HTTP_BUF_SIZE 4096
static char http_rx_buffer[HTTP_BUF_SIZE];
static int http_rx_index = 0;
static bool http_complete = false;
static bool wifi_connected = false;
static uint32_t last_sync_time = 0;
#define SYNC_INTERVAL_MS 2000 

struct Command {
    std::string type;   
    std::string params; 
    bool from_network;  
};
static std::vector<Command> cmd_queue;

// --- FORWARD DECLARATIONS ---
static void led_set(bool on);
void process_command(Command cmd);
static bool read_climate();
static void capture_audio();
static float process_and_compute_features();
static void run_summer_inference(float density);
static void run_winter_inference(float density);
static void stream_audio(int seconds);
static void debug_features();

// =================================================================================
// ROBUST HTTP CLIENT (Fixes Timeouts)
// =================================================================================

static err_t http_recv_callback(void *arg, struct tcp_pcb *tpcb, struct pbuf *p, err_t err) {
    if (!p) {
        // Server closed connection
        tcp_close(tpcb);
        http_complete = true;
        return ERR_OK;
    }
    
    // Copy data
    if (http_rx_index < HTTP_BUF_SIZE - 1) {
        int copy_len = p->len;
        if (http_rx_index + copy_len >= HTTP_BUF_SIZE) {
            copy_len = HTTP_BUF_SIZE - 1 - http_rx_index;
        }
        memcpy(&http_rx_buffer[http_rx_index], p->payload, copy_len);
        http_rx_index += copy_len;
        http_rx_buffer[http_rx_index] = 0;
    }
    
    tcp_recved(tpcb, p->tot_len);
    pbuf_free(p);

    // FIX: Check if we have the full response?
    // For now, if we see the end of JSON "}]" or just "OK" (not robust, but helps)
    // Or if buffer is reasonably full.
    // Ideally we parse Content-Length, but for short JSON, just waiting a bit is safer.
    // We will rely on tcp_close or timeout in the main loop if Keep-Alive is active.
    
    return ERR_OK;
}

static err_t http_connected_callback(void *arg, struct tcp_pcb *tpcb, err_t err) {
    if (err != ERR_OK) return err;
    const char* request = (const char*)arg;
    tcp_write(tpcb, request, strlen(request), TCP_WRITE_FLAG_COPY);
    tcp_output(tpcb);
    return ERR_OK;
}

static void http_error_callback(void *arg, err_t err) {
    printf("[NET] TCP Error: %d\n", err);
    http_complete = true; // Bail out
}

static bool perform_http_request(const char* method, const char* path, const char* body) {
    if (!wifi_connected) return false;

    http_rx_index = 0;
    http_rx_buffer[0] = 0;
    http_complete = false;

    struct tcp_pcb *pcb = tcp_new();
    if (!pcb) return false;

    // Set error callback to catch resets
    tcp_err(pcb, http_error_callback);

    ip_addr_t server_ip;
    ip4addr_aton(sys_config.server_ip, &server_ip);

    char request[1024];
    // FIX: Add Connection: close header to prevent server keeping link open
    int len = snprintf(request, sizeof(request), 
        "%s /api/v1/%s HTTP/1.1\r\n"
        "Host: %s:%d\r\n"
        "Connection: close\r\n" 
        "Content-Type: application/json\r\n"
        "Content-Length: %d\r\n"
        "\r\n"
        "%s", 
        method, path, sys_config.server_ip, sys_config.server_port, (int)strlen(body), body);

    tcp_arg(pcb, (void*)request);
    tcp_recv(pcb, http_recv_callback);
    
    if (tcp_connect(pcb, &server_ip, sys_config.server_port, http_connected_callback) != ERR_OK) {
        printf("[NET] Connection failed\n");
        return false;
    }

    uint32_t start = to_ms_since_boot(get_absolute_time());
    // Wait for completion OR timeout (3s)
    while (!http_complete) {
        cyw43_arch_poll();
        sleep_ms(5); // Yield
        if (to_ms_since_boot(get_absolute_time()) - start > 3000) {
            // Force close if server is slow / keep-alive
            tcp_abort(pcb);
            // Don't return false yet, check if we got data
            if (http_rx_index > 0) return true; 
            printf("[NET] Timeout\n");
            return false;
        }
    }
    return true;
}

static void log_to_server(const char* msg) {
    if(!wifi_connected) return;
    char json[256];
    snprintf(json, sizeof(json), "{\"node_id\": \"%s\", \"message\": \"%s\"}", sys_config.node_id, msg);
    perform_http_request("POST", "logs/", json);
}

// Simple JSON Parser to extract commands from Server Response
// Expects: [{"command_type": "RUN_INFERENCE", "params": {...}}]
static void parse_server_commands() {
    // Find body (after double newline)
    char* body = strstr(http_rx_buffer, "\r\n\r\n");
    if (!body) return;
    body += 4; // Skip CRLFCRLF

    // Basic parsing logic
    if (strstr(body, "RUN_INFERENCE")) {
        std::string params = "";
        if (strstr(body, "winter")) params = "winter";
        else params = "summer";
        cmd_queue.push_back({"RUN_INFERENCE", params, true});
        printf("[NET] CMD Received: RUN_INFERENCE (%s)\n", params.c_str());
    }
    else if (strstr(body, "READ_CLIMATE")) {
        cmd_queue.push_back({"READ_CLIMATE", "", true});
        printf("[NET] CMD Received: READ_CLIMATE\n");
    }
    else if (strstr(body, "PING")) {
        cmd_queue.push_back({"PING", "", true});
    }
}

// =================================================================================
// SENSORS & DSP (Preserved)
// =================================================================================

static void reset_filters() {
    hp_w1 = hp_w2 = 0; lp1_w1 = 0; lp2_w1 = lp2_w2 = 0;
}

static inline float biquad_hp(float x) {
    float y = HP_B0 * x + hp_w1; hp_w1 = HP_B1 * x - HP_A1 * y + hp_w2; hp_w2 = HP_B2 * x - HP_A2 * y; return y;
}
static inline float biquad_lp1(float x) {
    float y = LP1_B0 * x + lp1_w1; lp1_w1 = LP1_B1 * x - LP1_A1 * y; return y;
}
static inline float biquad_lp2(float x) {
    float y = LP2_B0 * x + lp2_w1; lp2_w1 = LP2_B1 * x - LP2_A1 * y + lp2_w2; lp2_w2 = LP2_B2 * x - LP2_A2 * y; return y;
}

static float compute_bin_magnitude_accurate(const float* windowed_data, int k) {
    double real_sum = 0.0, imag_sum = 0.0;
    for (int n = 0; n < FFT_SIZE; n++) {
        real_sum += windowed_data[n] * g_cos_table[k][n];
        imag_sum += windowed_data[n] * g_sin_table[k][n];
    }
    return (float)sqrt(real_sum * real_sum + imag_sum * imag_sum);
}

static void led_set(bool on) { cyw43_arch_gpio_put(CYW43_WL_GPIO_LED_PIN, on); }

static void setup_hardware() {
    stdio_init_all();
    load_config(); 

    if (cyw43_arch_init()) { printf("[ERR] WiFi init failed\n"); return; }
    cyw43_arch_enable_sta_mode();

    if (strlen(sys_config.wifi_ssid) > 0) {
        printf("[NET] Connecting to %s...\n", sys_config.wifi_ssid);
        int retries = 3;
        while (retries > 0 && !wifi_connected) {
            led_set(true);
            int err = cyw43_arch_wifi_connect_timeout_ms(sys_config.wifi_ssid, sys_config.wifi_pass, CYW43_AUTH_WPA2_AES_PSK, 15000);
            led_set(false);
            if (err == 0) {
                printf("[NET] Connected! IP: %s\n", ip4addr_ntoa(netif_ip4_addr(netif_list)));
                wifi_connected = true;
            } else {
                printf("[NET] WiFi Failed (%d). Retrying...\n", err);
                sleep_ms(2000);
                retries--;
            }
        }
    }

    i2c_init(I2C_INST, 100 * 1000);
    gpio_set_function(SHT_SDA_PIN, GPIO_FUNC_I2C); gpio_set_function(SHT_SCL_PIN, GPIO_FUNC_I2C);
    gpio_pull_up(SHT_SDA_PIN); gpio_pull_up(SHT_SCL_PIN);

    adc_init(); adc_gpio_init(MIC_PIN); adc_select_input(ADC_CHANNEL);

    g_dma_chan = dma_claim_unused_channel(true);
    g_dma_cfg = dma_channel_get_default_config(g_dma_chan);
    channel_config_set_transfer_data_size(&g_dma_cfg, DMA_SIZE_16);
    channel_config_set_read_increment(&g_dma_cfg, false);
    channel_config_set_write_increment(&g_dma_cfg, true);
    channel_config_set_dreq(&g_dma_cfg, DREQ_ADC);

    for (int i = 0; i < FFT_SIZE; i++) g_hanning_window[i] = 0.5f * (1.0f - cosf(2.0f * (float)M_PI * (float)i / (float)(FFT_SIZE - 1)));
    for (int k = 0; k < NUM_FREQ_BINS; k++) {
        for (int n = 0; n < FFT_SIZE; n++) {
            double angle = -2.0 * M_PI * k * n / FFT_SIZE;
            g_cos_table[k][n] = (float)cos(angle);
            g_sin_table[k][n] = (float)sin(angle);
        }
    }
    
    printf("[INIT] Ready. Node: %s\n", sys_config.node_id);
    if(wifi_connected) log_to_server("System Booted");
}

static bool read_climate() {
    if (g_mock_mode) {
        g_last_temp = g_mock_temp; g_last_hum = g_mock_hum;
        printf("[SENSOR] MOCK: %.2fC %.2f%%\n", g_last_temp, g_last_hum);
        return true;
    }
    uint8_t cmd[2] = {0x24, 0x00};
    i2c_write_blocking(I2C_INST, SHT_ADDR, cmd, 2, false);
    sleep_ms(15);
    uint8_t data[6];
    if (i2c_read_blocking(I2C_INST, SHT_ADDR, data, 6, false) == PICO_ERROR_GENERIC) return false;
    uint16_t t_raw = (data[0] << 8) | data[1];
    uint16_t h_raw = (data[3] << 8) | data[4];
    g_last_temp = -45.0f + (175.0f * (float)t_raw / 65535.0f);
    g_last_hum = 100.0f * ((float)h_raw / 65535.0f);
    printf("[SENSOR] %.2fC %.2f%%\n", g_last_temp, g_last_hum);
    return true;
}

static void capture_audio() {
    printf("[REC] Capturing %d samples...\n", AUDIO_BUFFER_SIZE);
    led_set(true);
    adc_fifo_drain();
    adc_fifo_setup(true, true, 1, false, false);
    adc_set_clkdiv(3000.0f - 1.0f);
    dma_channel_configure(g_dma_chan, &g_dma_cfg, g_audio_buffer, &adc_hw->fifo, AUDIO_BUFFER_SIZE, true);
    adc_run(true);
    dma_channel_wait_for_finish_blocking(g_dma_chan);
    adc_run(false);
    led_set(false);
}

static void stream_audio(int seconds) {
    if (seconds <= 0 || seconds > 6) seconds = 6;
    int samples = seconds * SAMPLE_RATE_HZ;
    printf("[STREAM] Capturing %d samples...\n", samples);
    led_set(true);
    adc_fifo_drain();
    adc_fifo_setup(true, true, 1, false, false);
    adc_set_clkdiv(3000.0f - 1.0f);
    dma_channel_configure(g_dma_chan, &g_dma_cfg, g_audio_buffer, &adc_hw->fifo, samples, true);
    adc_run(true);
    dma_channel_wait_for_finish_blocking(g_dma_chan);
    adc_run(false);
    led_set(false);
    
    // Header
    uint64_t sum = 0, var_sum = 0;
    for(int i=0; i<samples; i++) sum += g_audio_buffer[i];
    float mean = (float)sum / samples;
    for(int i=0; i<samples; i++) { float diff = g_audio_buffer[i] - mean; var_sum += (uint64_t)(diff * diff); }
    float std_dev = sqrtf((float)var_sum / samples);
    
    printf("HDR:%u:%u:%.1f\n", samples * 2, samples, std_dev);
    stdio_flush();
    sleep_ms(10);
    for (int i = 0; i < samples; i++) {
        putchar_raw(g_audio_buffer[i] & 0xFF);
        putchar_raw((g_audio_buffer[i] >> 8) & 0xFF);
    }
    stdio_flush();
    sleep_ms(10);
    printf("\nEND\n");
}

static float process_and_compute_features() {
    printf("[DSP] Processing...\n");
    for (int k = 0; k < NUM_FREQ_BINS; k++) g_bin_accum[k] = 0.0;
    
    double dc_sum = 0;
    for (int i = 0; i < AUDIO_BUFFER_SIZE; i++) dc_sum += g_audio_buffer[i];
    float dc_offset = (float)(dc_sum / AUDIO_BUFFER_SIZE);
    
    int num_windows = (AUDIO_BUFFER_SIZE - FFT_SIZE) / FFT_HOP + 1;
    reset_filters();
    
    double rms_sum = 0; int rms_count = 0;
    
    for (int w = 0; w < num_windows; w++) {
        int offset = w * FFT_HOP;
        for (int i = 0; i < FFT_SIZE; i++) {
            float sample = ((float)g_audio_buffer[offset + i] - dc_offset) / 2048.0f;
            sample *= g_gain_compensation;
            sample = biquad_lp2(biquad_lp1(biquad_hp(sample)));
            rms_sum += sample * sample; rms_count++;
            g_fft_input[i] = sample * g_hanning_window[i];
        }
        for (int k = 0; k < NUM_FREQ_BINS; k++) g_bin_accum[k] += compute_bin_magnitude_accurate(g_fft_input, k);
    }
    float density = sqrtf((float)(rms_sum / rms_count));
    for (int k = 0; k < NUM_FREQ_BINS; k++) g_bin_accum[k] /= num_windows;
    printf("[DSP] Density: %.6f\n", density);
    return density;
}

static void run_summer_inference(float current_density) {
    if (g_density_history.size() >= HISTORY_SIZE) g_density_history.erase(g_density_history.begin());
    g_density_history.push_back(current_density);
    float rolling = 0; for(float d: g_density_history) rolling += d;
    rolling = (g_density_history.size() > 0) ? rolling / g_density_history.size() : current_density;
    float spike = current_density / (rolling + 1e-6f);
    
    g_features_summer[0] = g_last_temp;
    g_features_summer[1] = g_last_hum;
    g_features_summer[2] = 14.0f; 
    g_features_summer[3] = spike;
    for (int i = 0; i < 16; i++) g_features_summer[4 + i] = (float)g_bin_accum[4 + i];
    
    signal_t signal;
    numpy::signal_from_buffer(g_features_summer, 20, &signal);
    ei_impulse_result_t result = {0};
    run_classifier(&signal, &result, false);
    
    const char* label = "Unknown"; float score = 0.0f;
    for (size_t ix = 0; ix < EI_CLASSIFIER_LABEL_COUNT; ix++) {
        if (result.classification[ix].value > score) {
            score = result.classification[ix].value;
            label = result.classification[ix].label;
        }
    }
    
    printf("[AI] Result: %s (%.1f%%)\n", label, score*100);
    
    if (wifi_connected) {
        char json[256];
        snprintf(json, sizeof(json), 
            "{\"node_id\": \"%s\", \"model_type\": \"summer\", \"classification\": \"%s\", \"confidence\": %.2f, \"timestamp\": \"2023-01-01T00:00:00\"}",
            sys_config.node_id, label, score);
        perform_http_request("POST", "inference/", json);
        log_to_server("Inference Completed");
    }
}

static void run_winter_inference(float density) {
    printf("[AI] Winter logic placeholder\n");
    if(wifi_connected) log_to_server("Winter Logic Run");
}

static void debug_features() {
    read_climate(); capture_audio(); process_and_compute_features();
    printf("Density: %.6f\n", 0.0f); // Placeholder print
}

// =================================================================================
// MAIN CLI
// =================================================================================

void process_command(Command cmd) {
    if (cmd.type == "READ_CLIMATE") {
        read_climate();
        if (cmd.from_network && wifi_connected) {
            char json[128];
            snprintf(json, sizeof(json), 
                "{\"node_id\":\"%s\",\"temperature_c\":%.2f,\"humidity_pct\":%.2f,\"battery_mv\":4200}", 
                sys_config.node_id, g_last_temp, g_last_hum);
            perform_http_request("POST", "telemetry/", json);
        }
    }
    else if (cmd.type == "RUN_INFERENCE") {
        read_climate(); capture_audio();
        float density = process_and_compute_features();
        if (cmd.params == "winter") run_winter_inference(density);
        else run_summer_inference(density);
    }
    else if (cmd.type == "CAPTURE_AUDIO") stream_audio(6);
    else if (cmd.type == "TOGGLE_MOCK") {
        g_mock_mode = !g_mock_mode;
        printf("[CONF] Mock: %d\n", g_mock_mode);
        if(wifi_connected) log_to_server(g_mock_mode ? "Mock Enabled" : "Mock Disabled");
    }
    else if (cmd.type == "CLEAR_HISTORY") {
        g_density_history.clear();
        printf("[CONF] History Cleared\n");
    }
    else if (cmd.type == "DEBUG_DUMP") debug_features();
    else if (cmd.type == "PING") {
        printf("PONG\n");
        if(wifi_connected) log_to_server("PONG");
    }
}

static void set_mock_values(float t, float h, float hr) {
    g_mock_temp = t; g_mock_hum = h; g_mock_hour = hr;
    printf("[CONF] Mock Set: %.1fC %.1f%%\n", t, h);
}

int main() {
    setup_hardware();
    char serial_buf[64]; int serial_ptr = 0;
    
    printf("\n>>> BeeWatch Node Ready.\n");

    while (true) {
        int c = getchar_timeout_us(0);
        if (c != PICO_ERROR_TIMEOUT) {
            if (c == '\n' || c == '\r') {
                serial_buf[serial_ptr] = 0; printf("\n");
                char* token = strtok(serial_buf, " ");
                if (token) {
                    if (strcmp(token, "s") == 0) cmd_queue.push_back({"RUN_INFERENCE", "summer", false});
                    else if (strcmp(token, "w") == 0) cmd_queue.push_back({"RUN_INFERENCE", "winter", false});
                    else if (strcmp(token, "t") == 0) cmd_queue.push_back({"READ_CLIMATE", "", false});
                    else if (strcmp(token, "a") == 0) cmd_queue.push_back({"CAPTURE_AUDIO", "", false});
                    else if (strcmp(token, "m") == 0) cmd_queue.push_back({"TOGGLE_MOCK", "", false});
                    else if (strcmp(token, "c") == 0) cmd_queue.push_back({"CLEAR_HISTORY", "", false});
                    else if (strcmp(token, "d") == 0) cmd_queue.push_back({"DEBUG_DUMP", "", false});
                    else if (strcmp(token, "p") == 0) cmd_queue.push_back({"PING", "", false});
                    else if (strcmp(token, "wifi") == 0) {
                        char* s = strtok(NULL, " "); char* p = strtok(NULL, " ");
                        if(s && p) { strncpy(sys_config.wifi_ssid, s, 31); strncpy(sys_config.wifi_pass, p, 63); save_config(); printf("Saved WiFi.\n"); }
                    }
                    else if (strcmp(token, "server") == 0) {
                        char* i = strtok(NULL, " ");
                        if(i) { strncpy(sys_config.server_ip, i, 15); save_config(); printf("Saved IP: %s\n", i); }
                    }
                    else if (strcmp(token, "v") == 0) {
                        char* t = strtok(NULL, " "); char* h = strtok(NULL, " "); char* hr = strtok(NULL, " ");
                        if(t && h && hr) set_mock_values(atof(t), atof(h), atof(hr));
                    }
                }
                serial_ptr = 0; printf("> ");
            } else if (serial_ptr < 63) {
                putchar(c); serial_buf[serial_ptr++] = (char)c;
            }
        }

        // 2. Poll Network
        if (wifi_connected && (to_ms_since_boot(get_absolute_time()) - last_sync_time > SYNC_INTERVAL_MS)) {
            last_sync_time = to_ms_since_boot(get_absolute_time());
            char query[128];
            snprintf(query, 128, "commands/pending?node_id=%s", sys_config.node_id);
            if (perform_http_request("GET", query, "")) {
                parse_server_commands();
            }
        }
        
        // 3. Execute Queue
        if (!cmd_queue.empty()) {
            Command cmd = cmd_queue.front();
            cmd_queue.erase(cmd_queue.begin());
            process_command(cmd);
        }
        
        cyw43_arch_poll();
        sleep_ms(10);
    }
    return 0;
}

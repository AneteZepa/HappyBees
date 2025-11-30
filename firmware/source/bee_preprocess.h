/*
 * bee_preprocess.h
 * Handles rolling averages and feature extraction for Bee Smart Hive
 */

#ifndef BEE_PREPROCESS_H
#define BEE_PREPROCESS_H

#include <vector>
#include <numeric>
#include <cmath>

// Config
#define HISTORY_SIZE 12   // 12 samples (e.g., 3 hours if 15m intervals) for stability check
#define FFT_SIZE 32       // Depends on your specific Edge Impulse DSP block settings

// Indices of specific frequencies in your spectrum array 
// (You must map these to your specific FFT bin outputs from Edge Impulse)
// Example: if bin 5 corresponds to ~213Hz
const int IDX_HEATING_START = 5; 
const int IDX_HEATING_END = 8;  
const int IDX_PIPING_START = 10;
const int IDX_PIPING_END = 12;

struct BeeSensorData {
    float temperature;
    float humidity;
    int hour;
    float audio_density;
    float spectrum[FFT_SIZE]; // Array of frequency magnitudes
};

class BeeFeatureExtractor {
private:
    std::vector<float> temp_history;
    std::vector<float> audio_density_history;

public:
    // Add new reading to rolling buffers
    void add_reading(float temp, float density) {
        temp_history.push_back(temp);
        if (temp_history.size() > HISTORY_SIZE) temp_history.erase(temp_history.begin());

        audio_density_history.push_back(density);
        if (audio_density_history.size() > HISTORY_SIZE) audio_density_history.erase(audio_density_history.begin());
    }

    // Calculate Variance (Stability)
    float get_temp_stability() {
        if (temp_history.size() < 2) return 0.0f;
        
        float sum = std::accumulate(temp_history.begin(), temp_history.end(), 0.0f);
        float mean = sum / temp_history.size();
        
        float sq_sum = 0.0f;
        for (float val : temp_history) {
            sq_sum += (val - mean) * (val - mean);
        }
        return sq_sum / temp_history.size();
    }

    float get_rolling_audio_avg() {
         if (audio_density_history.empty()) return 1.0f; // Avoid div/0
         float sum = std::accumulate(audio_density_history.begin(), audio_density_history.end(), 0.0f);
         return sum / audio_density_history.size();
    }

    // --- WINTER PREP ---
    // Features: [temperature, humidity, temp_stability, heater_power, heater_ratio]
    std::vector<float> get_winter_input(BeeSensorData raw) {
        std::vector<float> features;
        
        // 1. Temperature
        features.push_back(raw.temperature);
        
        // 2. Humidity
        features.push_back(raw.humidity);
        
        // 3. Temp Stability (Calculated)
        features.push_back(get_temp_stability());
        
        // 4. Heater Power (Sum of ~180-250Hz bins)
        float heater_pwr = 0.0f;
        for(int i=IDX_HEATING_START; i<=IDX_HEATING_END; i++) {
            if(i < FFT_SIZE) heater_pwr += raw.spectrum[i];
        }
        features.push_back(heater_pwr);
        
        // 5. Heater Ratio
        float ratio = heater_pwr / (raw.audio_density + 1e-6);
        features.push_back(ratio);

        return features;
    }

    // --- SUMMER PREP ---
    // Features: [temp, humid, hour, spike_ratio, ...audio_spectrum...]
    std::vector<float> get_summer_input(BeeSensorData raw) {
        std::vector<float> features;

        features.push_back(raw.temperature);
        features.push_back(raw.humidity);
        features.push_back((float)raw.hour);

        // Audio Spike Ratio
        float rolling = get_rolling_audio_avg();
        float spike = raw.audio_density / (rolling + 1e-6);
        features.push_back(spike);

        // Full Spectrum (or specific bins used in training)
        for(int i=0; i<16; i++) { // Assuming model takes 16 bins
            features.push_back(raw.spectrum[i]);
        }

        return features;
    }
};

#endif // BEE_PREPROCESS_H
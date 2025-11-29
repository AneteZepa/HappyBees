/*
 * flash_config.h
 * Persists WiFi credentials and Server Config to the last page of Flash.
 */
#ifndef FLASH_CONFIG_H
#define FLASH_CONFIG_H

#include "hardware/flash.h"
#include "hardware/sync.h"
#include <string.h>

// Use the very last sector of flash for config
#define FLASH_TARGET_OFFSET (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)
#define CONFIG_MAGIC 0xBEEFCAFE

struct SystemConfig {
    uint32_t magic;
    char wifi_ssid[32];
    char wifi_pass[64];
    char server_ip[16];
    int server_port;
    char node_id[32];
};

// Global config instance
static SystemConfig sys_config;

static void load_config() {
    const uint8_t *flash_target_contents = (const uint8_t *) (XIP_BASE + FLASH_TARGET_OFFSET);
    memcpy(&sys_config, flash_target_contents, sizeof(SystemConfig));
    
    if (sys_config.magic != CONFIG_MAGIC) {
        printf("[CONF] No valid config found. Using defaults.\n");
        // Set safe defaults or empty strings
        memset(&sys_config, 0, sizeof(SystemConfig));
        sys_config.magic = CONFIG_MAGIC;
        strcpy(sys_config.node_id, "pico-hive-001");
        strcpy(sys_config.server_ip, "192.168.1.50"); // Default dev IP
        sys_config.server_port = 8000;
    } else {
        printf("[CONF] Config loaded. SSID: %s, Server: %s\n", sys_config.wifi_ssid, sys_config.server_ip);
    }
}

static void save_config() {
    // Flash programming must be done with interrupts disabled
    uint32_t ints = save_and_disable_interrupts();
    flash_range_erase(FLASH_TARGET_OFFSET, FLASH_SECTOR_SIZE);
    flash_range_program(FLASH_TARGET_OFFSET, (uint8_t*)&sys_config, FLASH_PAGE_SIZE);
    restore_interrupts(ints);
    printf("[CONF] Config saved to flash.\n");
}

#endif

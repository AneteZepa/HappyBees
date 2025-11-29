/**
 * BeeWatch Flash Configuration Storage
 * 
 * Stores WiFi credentials and server settings in flash memory.
 * Configuration persists across reboots.
 */

#ifndef FLASH_CONFIG_H
#define FLASH_CONFIG_H

#include <string.h>
#include "hardware/flash.h"
#include "hardware/sync.h"

// Flash storage location (last 4KB page)
#define FLASH_TARGET_OFFSET (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)

// Configuration structure
typedef struct {
    uint32_t magic;           // 0xBEE5CAFE = valid config
    char wifi_ssid[32];
    char wifi_pass[64];
    char server_ip[16];
    uint16_t server_port;
    char node_id[32];
    uint32_t checksum;
} SystemConfig;

// Global configuration
static SystemConfig sys_config;

// Default values
#define CONFIG_MAGIC 0xBEE5CAFE
#define DEFAULT_SERVER_IP "192.168.0.100"
#define DEFAULT_SERVER_PORT 8000
#define DEFAULT_NODE_ID "pico-hive-001"

/**
 * Calculate simple checksum for validation
 */
static uint32_t calc_checksum(const SystemConfig* cfg) {
    const uint8_t* data = (const uint8_t*)cfg;
    uint32_t sum = 0;
    // Sum all bytes except the checksum field itself
    for (size_t i = 0; i < offsetof(SystemConfig, checksum); i++) {
        sum += data[i];
    }
    return sum;
}

/**
 * Load configuration from flash
 */
static void load_config() {
    const SystemConfig* flash_cfg = (const SystemConfig*)(XIP_BASE + FLASH_TARGET_OFFSET);
    
    // Check for valid config
    if (flash_cfg->magic == CONFIG_MAGIC && 
        flash_cfg->checksum == calc_checksum(flash_cfg)) {
        // Copy from flash to RAM
        memcpy(&sys_config, flash_cfg, sizeof(SystemConfig));
        printf("[FLASH] Config loaded: SSID=%s, Server=%s:%d, Node=%s\n",
               sys_config.wifi_ssid, sys_config.server_ip, 
               sys_config.server_port, sys_config.node_id);
    } else {
        // Initialize with defaults
        printf("[FLASH] No valid config, using defaults\n");
        sys_config.magic = CONFIG_MAGIC;
        memset(sys_config.wifi_ssid, 0, sizeof(sys_config.wifi_ssid));
        memset(sys_config.wifi_pass, 0, sizeof(sys_config.wifi_pass));
        strncpy(sys_config.server_ip, DEFAULT_SERVER_IP, sizeof(sys_config.server_ip) - 1);
        sys_config.server_port = DEFAULT_SERVER_PORT;
        strncpy(sys_config.node_id, DEFAULT_NODE_ID, sizeof(sys_config.node_id) - 1);
        sys_config.checksum = calc_checksum(&sys_config);
    }
}

/**
 * Save configuration to flash
 */
static void save_config() {
    // Update checksum
    sys_config.checksum = calc_checksum(&sys_config);
    
    // Prepare buffer (must be 256-byte aligned for flash write)
    uint8_t buffer[FLASH_PAGE_SIZE];
    memset(buffer, 0xFF, FLASH_PAGE_SIZE);
    memcpy(buffer, &sys_config, sizeof(SystemConfig));
    
    // Disable interrupts during flash operations
    uint32_t ints = save_and_disable_interrupts();
    
    // Erase sector (4KB)
    flash_range_erase(FLASH_TARGET_OFFSET, FLASH_SECTOR_SIZE);
    
    // Write page (256 bytes)
    flash_range_program(FLASH_TARGET_OFFSET, buffer, FLASH_PAGE_SIZE);
    
    // Re-enable interrupts
    restore_interrupts(ints);
    
    printf("[FLASH] Config saved\n");
}

#endif // FLASH_CONFIG_H

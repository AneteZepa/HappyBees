/**
 * BeeWatch lwIP Configuration
 * 
 * TCP/IP stack options for WiFi networking.
 */

#ifndef LWIPOPTS_H
#define LWIPOPTS_H

// Common settings from pico_cyw43_arch
#include "lwipopts_examples_common.h"

// Override for our needs
#define TCP_MSS                 1460
#define TCP_WND                 (4 * TCP_MSS)
#define TCP_SND_BUF             (4 * TCP_MSS)
#define MEMP_NUM_TCP_PCB        8
#define PBUF_POOL_SIZE          16

// DNS
#define LWIP_DNS                1

// Reduce debug noise
#define LWIP_DEBUG              0

#endif // LWIPOPTS_H

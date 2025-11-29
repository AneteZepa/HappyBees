/**
 * HappyBees lwIP Configuration
 */

#ifndef LWIPOPTS_H
#define LWIPOPTS_H

#include "lwipopts_examples_common.h"

#define TCP_MSS                 1460
#define TCP_WND                 (4 * TCP_MSS)
#define TCP_SND_BUF             (4 * TCP_MSS)
#define MEMP_NUM_TCP_PCB        8
#define PBUF_POOL_SIZE          16
#define LWIP_DNS                1
#define LWIP_DEBUG              0

#endif

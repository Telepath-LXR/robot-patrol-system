#ifndef __PROTOCOL_H
#define __PROTOCOL_H

#include <stdint.h>
#include "FreeRTOS.h"
#include "task.h"

#define PROTO_MAX_LEN   64U

typedef struct {
    uint16_t len;
    uint8_t  data[PROTO_MAX_LEN];
} RawFrame_t;

extern volatile TickType_t g_last_heartbeat_tick;

uint16_t CRC16_CCITT(const uint8_t *data, uint16_t len);
void     Proto_FeedByte(uint8_t b);
void     Proto_SendFrame(uint8_t type, const uint8_t *data, uint8_t len);
void     Proto_SendHeartbeatAck(uint8_t status);

#endif
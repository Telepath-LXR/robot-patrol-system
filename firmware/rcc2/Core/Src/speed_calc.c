#include "speed_calc.h"
#include "tim.h"

/* 外部时钟模式（单向计数）：2000个脉冲 = 1转 */
#define COUNTS_PER_REV   2000.0f

static uint16_t last_cnt = 0;

float Speed_MeasureRPM(uint32_t window_ms)
{
    uint16_t now   = (uint16_t)__HAL_TIM_GET_COUNTER(&htim2);
    int16_t  delta = (int16_t)(now - last_cnt);   /* 16位溢出安全处理 */
    last_cnt = now;

    // RPM = delta * (1000/100) * 60 / 2000 = delta * 0.3
    return (float)delta * (1000.0f / (float)window_ms) * 60.0f / COUNTS_PER_REV;
}
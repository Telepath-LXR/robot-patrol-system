#include "virtual_motor.h"
#include "tim.h"

#define VMOTOR_MAX_HZ    2000.0f
#define VMOTOR_ALPHA     0.02f
#define VMOTOR_MIN_HZ    16.0f

static float vmotor_hz = 0.0f;

// 【避坑】：去掉了static，这样你在Keil的Watch里能手动改成0.7测试负载
float vmotor_load = 1.0f;   

void VMotor_ToggleLoad(void)
{
    vmotor_load = (vmotor_load > 0.9f) ? 0.7f : 1.0f;
}

void VMotor_Update(float duty_percent)
{
    float target = VMOTOR_MAX_HZ * duty_percent / 100.0f * vmotor_load;
    vmotor_hz += (target - vmotor_hz) * VMOTOR_ALPHA;

    if (vmotor_hz < VMOTOR_MIN_HZ) {
        __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_1, 0U);
        return;
    }
    
    // TIM4 计数时钟为 1MHz，ARR = 1e6/f - 1
    uint32_t arr = (uint32_t)(1000000.0f / vmotor_hz) - 1U;
    __HAL_TIM_SET_AUTORELOAD(&htim4, arr);
    __HAL_TIM_SET_COMPARE(&htim4, TIM_CHANNEL_1, (arr + 1U) / 2U);
}

float VMotor_GetTrueHz(void) { return vmotor_hz; }
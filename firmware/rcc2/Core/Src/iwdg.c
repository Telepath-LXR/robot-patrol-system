#include "iwdg.h"

void MX_IWDG_Init(void)
{
    // 开启 LSI 时钟
    __HAL_RCC_LSI_ENABLE();
    uint32_t timeout = 0xFFFF;
    while (__HAL_RCC_GET_FLAG(RCC_FLAG_LSIRDY) == RESET) {
        if (--timeout == 0) break; 
    }

    IWDG->KR = 0x5555; // 解除写保护
    IWDG->PR = 3;      // 32分频，1ms计数一次
    IWDG->RLR = 1000;  // 1000ms = 1s 超时
    
    timeout = 0xFFFF;
    while ((IWDG->SR & 0x03) != 0) {
        if (--timeout == 0) break; 
    }
    
    IWDG->KR = 0xCCCC; // 启动看门狗
}

void IWDG_Feed(void)
{
    IWDG->KR = 0xAAAA; // 喂狗
}
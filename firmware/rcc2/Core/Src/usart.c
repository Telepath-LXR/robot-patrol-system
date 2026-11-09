/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    usart.c
  * @brief   This file provides code for the configuration
  *          of the USART instances.
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "usart.h"

/* USER CODE BEGIN 0 */
/* USER CODE END 0 */

UART_HandleTypeDef huart2;
DMA_HandleTypeDef hdma_usart2_rx;

/* USART2 init function */
void MX_USART2_UART_Init(void)
{
  /* USER CODE BEGIN USART2_Init 0 */
  /* USER CODE END USART2_Init 0 */

  /* USER CODE BEGIN USART2_Init 1 */
  /* USER CODE END USART2_Init 1 */
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART2_Init 2 */
  /* USER CODE END USART2_Init 2 */
}

void HAL_UART_MspInit(UART_HandleTypeDef* uartHandle)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  if(uartHandle->Instance==USART2)
  {
  /* USER CODE BEGIN USART2_MspInit 0 */
  /* USER CODE END USART2_MspInit 0 */
    /* USART2 clock enable */
    __HAL_RCC_USART2_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();

    /**USART2 GPIO Configuration
    PA2     ------> USART2_TX
    PA3     ------> USART2_RX
    */
    GPIO_InitStruct.Pin = GPIO_PIN_2|GPIO_PIN_3;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF7_USART2;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    /* USART2 DMA Init */
    /* USART2_RX Init */
    hdma_usart2_rx.Instance = DMA1_Stream5;
    hdma_usart2_rx.Init.Channel = DMA_CHANNEL_4;
    hdma_usart2_rx.Init.Direction = DMA_PERIPH_TO_MEMORY;
    hdma_usart2_rx.Init.PeriphInc = DMA_PINC_DISABLE;
    hdma_usart2_rx.Init.MemInc = DMA_MINC_ENABLE;
    hdma_usart2_rx.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
    hdma_usart2_rx.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
    hdma_usart2_rx.Init.Mode = DMA_NORMAL;
    hdma_usart2_rx.Init.Priority = DMA_PRIORITY_LOW;
    hdma_usart2_rx.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
    if (HAL_DMA_Init(&hdma_usart2_rx) != HAL_OK)
    {
      Error_Handler();
    }

    __HAL_LINKDMA(uartHandle,hdmarx,hdma_usart2_rx);

    /* USART2 interrupt Init */
    HAL_NVIC_SetPriority(USART2_IRQn, 5, 0);
    HAL_NVIC_EnableIRQ(USART2_IRQn);
  /* USER CODE BEGIN USART2_MspInit 1 */
  /* USER CODE END USART2_MspInit 1 */
  }
}

void HAL_UART_MspDeInit(UART_HandleTypeDef* uartHandle)
{
  if(uartHandle->Instance==USART2)
  {
  /* USER CODE BEGIN USART2_MspDeInit 0 */
  /* USER CODE END USART2_MspDeInit 0 */
    /* Peripheral clock disable */
    __HAL_RCC_USART2_CLK_DISABLE();
    /**USART2 GPIO Configuration
    PA2     ------> USART2_TX
    PA3     ------> USART2_RX
    */
    HAL_GPIO_DeInit(GPIOA, GPIO_PIN_2|GPIO_PIN_3);

    /* USART2 DMA DeInit */
    HAL_DMA_DeInit(uartHandle->hdmarx);

    /* USART2 interrupt Deinit */
    HAL_NVIC_DisableIRQ(USART2_IRQn);
  /* USER CODE BEGIN USART2_MspDeInit 1 */
  /* USER CODE END USART2_MspDeInit 1 */
  }
}

/* USER CODE BEGIN 1 */
#include <string.h>
#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"
#include "protocol_parse.h"
#include "protocol_pack.h"

extern QueueHandle_t vel_cmd_queue; 
extern volatile TickType_t g_last_heartbeat_tick; 
volatile uint8_t g_send_hb_ack = 0;

uint8_t rx_buf[128];
static parser_t rx_parser;
static BaseType_t s_woken = pdFALSE;

static void on_frame(uint8_t type, const uint8_t *data, uint8_t len)
{
    if (type == TYPE_VEL_CMD && len == 8) {
        vel_cmd_t cmd;
        cmd.v_left  = unpack_float_le(&data[0]);
        cmd.v_right = unpack_float_le(&data[4]);
        xQueueSendFromISR(vel_cmd_queue, &cmd, &s_woken); 
    } 
    else if (type == TYPE_HEARTBEAT) {
        g_last_heartbeat_tick = xTaskGetTickCountFromISR(); 
        g_send_hb_ack = 1; 
    }
    // 0x07 编码器注入
    else if (type == TYPE_ENC_INJECT && len == 8) {
        int32_t dl, dr;
        memcpy(&dl, &data[0], 4);
        memcpy(&dr, &data[4], 4);
        extern void Encoder_Inject(int32_t dl, int32_t dr);
        Encoder_Inject(dl, dr);
    }
}

void UART1_RxStart(void) { 
    parser_init(&rx_parser, on_frame);
    HAL_UARTEx_ReceiveToIdle_DMA(&huart2, rx_buf, 128); 
}

// 【终极修复】加入超时逃逸机制，彻底杜绝 RTOS 死锁
void UART1_SendData(uint8_t *data, uint16_t len) {
    for (uint16_t i = 0; i < len; i++) {
        uint32_t timeout = 100000; 
        while ((USART2->SR & 0x80) == 0 && timeout > 0) { timeout--; } 
        if (timeout == 0) return; 
        USART2->DR = data[i];
    }
    uint32_t timeout = 100000;
    while ((USART2->SR & 0x40) == 0 && timeout > 0) { timeout--; } 
}

void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size) {
    if (huart->Instance == USART2) { 
        for (uint16_t i = 0; i < Size; i++) {
            parser_feed(&rx_parser, rx_buf[i]);
        }
        HAL_UARTEx_ReceiveToIdle_DMA(&huart2, rx_buf, 128);
        portYIELD_FROM_ISR(s_woken);
    }
}
/* USER CODE END 1 */
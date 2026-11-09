/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * File Name          : freertos.c
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "FreeRTOS.h"
#include "task.h"
#include "main.h"
#include "cmsis_os.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "pid.h"
#include "speed_calc.h"
#include "virtual_motor.h"
#include "protocol_pack.h"
#include "queue.h"
#include "mpu6050.h"
#include "iwdg.h"
/* USER CODE END Includes */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define HEARTBEAT_TIMEOUT_MS   500U
/* USER CODE END PD */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN Variables */
QueueHandle_t vel_cmd_queue;       
QueueHandle_t xQueueActualSpeed;   

PID_t g_pid_l;
PID_t g_pid_r;
volatile TickType_t g_last_heartbeat_tick = 0; 

extern volatile uint32_t g_ok_cnt;
extern volatile uint32_t g_crc_err_cnt;
extern volatile uint8_t g_send_hb_ack; 
extern void UART1_SendData(uint8_t *data, uint16_t len);

float odom_x = 0.0f;
float odom_y = 0.0f;
float odom_theta = 0.0f;

volatile int32_t g_enc_cnt_left = 0;
volatile int32_t g_enc_cnt_right = 0;

void Encoder_Inject(int32_t dl, int32_t dr) {
    g_enc_cnt_left += dl;
    g_enc_cnt_right += dr;
}
/* USER CODE END Variables */

/* Definitions for CommTask */
osThreadId_t CommTaskHandle;
const osThreadAttr_t CommTask_attributes = {
  .name = "CommTask",
  .stack_size = 512 * 4,
  .priority = (osPriority_t) osPriorityHigh,
};

/* Definitions for CtrlTask */
osThreadId_t CtrlTaskHandle;
const osThreadAttr_t CtrlTask_attributes = {
  .name = "CtrlTask",
  .stack_size = 1024 * 4, // 4KB 栈防爆
  .priority = (osPriority_t) osPriorityAboveNormal,
};

/* Definitions for AcqTask */
osThreadId_t AcqTaskHandle;
const osThreadAttr_t AcqTask_attributes = {
  .name = "AcqTask",
  .stack_size = 256 * 4,
  .priority = (osPriority_t) osPriorityNormal,
};

/* Definitions for ImuTask */
osThreadId_t ImuTaskHandle;
const osThreadAttr_t ImuTask_attributes = {
  .name = "ImuTask",
  .stack_size = 512 * 4,
  .priority = (osPriority_t) osPriorityNormal,
};

void StartCommTask(void *argument);
void StartCtrlTask(void *argument);
void StartAcqTask(void *argument);
void StartImuTask(void *argument);
void MX_FREERTOS_Init(void);

void MX_FREERTOS_Init(void) {
  /* USER CODE BEGIN RTOS_QUEUES */
  vel_cmd_queue     = xQueueCreate(4, sizeof(vel_cmd_t)); 
  xQueueActualSpeed = xQueueCreate(1, sizeof(float));     
  /* USER CODE END RTOS_QUEUES */

  CommTaskHandle = osThreadNew(StartCommTask, NULL, &CommTask_attributes);
  CtrlTaskHandle = osThreadNew(StartCtrlTask, NULL, &CtrlTask_attributes);
  AcqTaskHandle  = osThreadNew(StartAcqTask, NULL, &AcqTask_attributes);
  ImuTaskHandle  = osThreadNew(StartImuTask, NULL, &ImuTask_attributes);
}

void StartCommTask(void *argument)
{
  for(;;) {
    if (g_send_hb_ack) {
        g_send_hb_ack = 0;
        uint8_t txbuf[16];
        uint16_t n = pack_heartbeat_ack(txbuf, 0); 
        UART1_SendData(txbuf, n); 
    }
    osDelay(10); 
  }
}

void StartCtrlTask(void *argument)
{
  float target_l = 0.0f, target_r = 0.0f;
  float actual_l = 0.0f, actual_r = 0.0f;
  uint8_t in_safe_stop = 0;
  TickType_t xLastWake = xTaskGetTickCount();
  
    // 把 Kp 从 15 降到 3.0，Ki 从 0.02 降到 0.005，积分上限降到 100
  PID_Init(&g_pid_l, 3.0f, 0.005f, 0.0f, 100.0f, 100.0f);
  PID_Init(&g_pid_r, 3.0f, 0.005f, 0.0f, 100.0f, 100.0f);
  
  g_last_heartbeat_tick = xTaskGetTickCount(); 
  uint16_t div100ms = 0; 
  uint32_t last_time = xTaskGetTickCount();
  int32_t last_enc_l = 0, last_enc_r = 0;

  for(;;)
  {
    // ==========================================================
    // 【自激测试 & 看门狗】每 2 秒自动注入速度；每 500ms 闪//
    // 闪烁 LED 灯（PF10），证明程序活着
    static uint16_t led_test_tick = 0;
    if (++led_test_tick >= 500) {
        led_test_tick = 0;
        HAL_GPIO_TogglePin(GPIOF, GPIO_PIN_10);
    }
    // ==========================================================

    if ((xTaskGetTickCount() - g_last_heartbeat_tick) > pdMS_TO_TICKS(HEARTBEAT_TIMEOUT_MS)) {
        if (!in_safe_stop) {
            in_safe_stop = 1;
            PID_Reset(&g_pid_l);
            PID_Reset(&g_pid_r);
            xQueueReset(vel_cmd_queue); 
        }
        
        static uint16_t safe_stop_tick = 0;
        if (++safe_stop_tick >= 100) { 
            safe_stop_tick = 0;
            uint8_t txbuf[32];
            uint16_t n = pack_pwm_telem(txbuf, 0, 0, 0, 0);
            UART1_SendData(txbuf, n);
        }
        
        vTaskDelayUntil(&xLastWake, pdMS_TO_TICKS(1));
        continue;
    }
    
    if (in_safe_stop) {
        in_safe_stop = 0; 
    }
    
    vel_cmd_t cmd;
    if (xQueueReceive(vel_cmd_queue, &cmd, 0) == pdPASS) {
        target_l = cmd.v_left; 
        target_r = cmd.v_right;
    }
    
    uint32_t now_time = xTaskGetTickCount();
    if (now_time - last_time >= 10) {
        int32_t dl = g_enc_cnt_left - last_enc_l;
        int32_t dr = g_enc_cnt_right - last_enc_r;
        last_enc_l = g_enc_cnt_left;
        last_enc_r = g_enc_cnt_right;
        
        actual_l = (dl / 1560.0f) * (3.14159f * 0.1f) / 0.01f; 
        actual_r = (dr / 1560.0f) * (3.14159f * 0.1f) / 0.01f;
        last_time = now_time;
    }

    PID_SetTarget(&g_pid_l, target_l);
    PID_SetTarget(&g_pid_r, target_r);
    float duty_l = PID_Compute(&g_pid_l, actual_l);
    float duty_r = PID_Compute(&g_pid_r, actual_r);

    if (++div100ms >= 100) {
        div100ms = 0;
        
        // 算三角函数，测试会不会爆栈
        float v = (actual_l + actual_r) / 2.0f;
        float w = (actual_r - actual_l) / 0.30f; 
        
        odom_x += v * 0.1f * cos(odom_theta);
        odom_y += v * 0.1f * sin(odom_theta);
        odom_theta += w * 0.1f;

        uint8_t txbuf[32];
        uint16_t n = pack_odom(txbuf, odom_x, odom_y, odom_theta); 
        UART1_SendData(txbuf, n);
        
        int16_t pwm_l = (int16_t)(duty_l * 10.0f);
        int16_t pwm_r = (int16_t)(duty_r * 10.0f);
        int16_t spd_l = (int16_t)(actual_l * 1000.0f);
        int16_t spd_r = (int16_t)(actual_r * 1000.0f);
        
        n = pack_pwm_telem(txbuf, pwm_l, pwm_r, spd_l, spd_r);
        UART1_SendData(txbuf, n);
    }

    vTaskDelayUntil(&xLastWake, pdMS_TO_TICKS(1));
  }
}

void StartAcqTask(void *argument)
{
  TickType_t xLastWake = xTaskGetTickCount();
  uint16_t div500ms = 0; 

  for(;;) {
    IWDG_Feed();        
    float rpm = Speed_MeasureRPM(100);
    xQueueOverwrite(xQueueActualSpeed, &rpm);
    
    if (++div500ms >= 5) {
        div500ms = 0;
        uint8_t txbuf[16];
        uint16_t n = pack_battery(txbuf, 12.6f); 
        UART1_SendData(txbuf, n);
    }
    vTaskDelayUntil(&xLastWake, pdMS_TO_TICKS(100));
  }
}

void StartImuTask(void *argument)
{
  osDelay(1000); 
  mpu6050_calibrate_gyro();
  TickType_t xLastWake = xTaskGetTickCount();
  
  for(;;) {
    float acc[3], gyro[3];
    mpu6050_read_all(acc, gyro);
    
    uint8_t txbuf[32];
    uint16_t n = pack_imu_0x04(txbuf, acc, gyro);
    
    if (n > 0) {
        UART1_SendData(txbuf, n);
    }
    vTaskDelayUntil(&xLastWake, pdMS_TO_TICKS(50)); 
  }
}
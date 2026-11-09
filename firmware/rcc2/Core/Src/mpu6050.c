#include "mpu6050.h"
#include <stdio.h>

float g_gyro_bias[3] = {0};

static void MPU_WriteReg(uint8_t reg, uint8_t val) {
    HAL_I2C_Mem_Write(&hi2c1, MPU6050_ADDR_W, reg, 1, &val, 1, 10);
}
static void MPU_ReadRegs(uint8_t reg, uint8_t *buf, uint8_t len) {
    HAL_I2C_Mem_Read(&hi2c1, MPU6050_ADDR_W, reg, 1, buf, len, 10);
}

void mpu6050_init(void) {
    uint8_t who = 0;
    HAL_I2C_Mem_Read(&hi2c1, MPU6050_ADDR_W, REG_WHO_AM_I, 1, &who, 1, 10);
    if (who != 0x68) {
        return; // 读不到直接返回，防止死等
    }
    MPU_WriteReg(REG_PWR_MGMT_1, 0x01);   
    HAL_Delay(50);                        
    MPU_WriteReg(REG_SMPLRT_DIV, 0x07);   
    MPU_WriteReg(REG_GYRO_CFG, 0x00);     
    MPU_WriteReg(REG_ACCEL_CFG, 0x00);    
}

void mpu6050_calibrate_gyro(void) {
    uint8_t buf[6];
    int16_t raw[3];
    float sum[3] = {0};
    
    for (int i = 0; i < 200; i++) {
        MPU_ReadRegs(0x43, buf, 6);
        for (int k = 0; k < 3; k++) {
            raw[k] = (int16_t)((buf[2*k] << 8) | buf[2*k+1]);
            sum[k] += raw[k] / 131.0f;
        }
        HAL_Delay(5);
    }
    for (int k = 0; k < 3; k++) g_gyro_bias[k] = sum[k] / 200.0f;
}

void mpu6050_read_all(float *acc, float *gyro) {
    uint8_t buf[14];
    int16_t raw[7];
    MPU_ReadRegs(REG_ACCEL_XOUT_H, buf, 14);
    
    for (int i = 0; i < 7; i++) {
        raw[i] = (int16_t)((buf[2*i] << 8) | buf[2*i+1]);
    }
    
    acc[0] = raw[0] / 16384.0f * 9.80665f;
    acc[1] = raw[1] / 16384.0f * 9.80665f;
    acc[2] = raw[2] / 16384.0f * 9.80665f;
    
    gyro[0] = (raw[4] / 131.0f - g_gyro_bias[0]) * 0.0174533f;
    gyro[1] = (raw[5] / 131.0f - g_gyro_bias[1]) * 0.0174533f;
    gyro[2] = (raw[6] / 131.0f - g_gyro_bias[2]) * 0.0174533f;
}
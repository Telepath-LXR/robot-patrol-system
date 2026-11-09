#ifndef __MPU6050_H
#define __MPU6050_H

#include "main.h"
#include "i2c.h"

#define MPU6050_ADDR_W      0xD0
#define REG_WHO_AM_I        0x75
#define REG_PWR_MGMT_1      0x6B
#define REG_SMPLRT_DIV      0x19
#define REG_GYRO_CFG        0x1B
#define REG_ACCEL_CFG       0x1C
#define REG_ACCEL_XOUT_H    0x3B

extern float g_gyro_bias[3];

void mpu6050_init(void);
void mpu6050_calibrate_gyro(void);
void mpu6050_read_all(float *acc, float *gyro);

#endif
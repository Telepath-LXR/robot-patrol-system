#ifndef __VIRTUAL_MOTOR_H
#define __VIRTUAL_MOTOR_H

#include "main.h"

void  VMotor_Update(float duty_percent);
void  VMotor_ToggleLoad(void);
float VMotor_GetTrueHz(void);

#endif
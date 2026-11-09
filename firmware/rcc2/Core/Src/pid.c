#include "pid.h"

void PID_Init(PID_t *pid, float kp, float ki, float kd, float integral_max, float output_max)
{
    pid->Kp = kp;  pid->Ki = ki;  pid->Kd = kd;
    pid->setpoint = 0.0f;
    pid->integral = 0.0f;
    pid->prev_error = 0.0f;
    pid->output = 0.0f;
    pid->integral_max = integral_max;
    pid->output_max   = output_max;
}

void PID_SetTarget(PID_t *pid, float setpoint)
{
    pid->setpoint = setpoint;
}

float PID_Compute(PID_t *pid, float measurement)
{
    float error = pid->setpoint - measurement;

    // 【核心修复 1】如果目标速度是 0，直接清空积分，瞬间刹停！
    if (pid->setpoint == 0.0f) {
        pid->integral = 0.0f;
        pid->prev_error = 0.0f;
        pid->output = 0.0f;
        return 0.0f;
    }

    pid->integral += error;
    // 【核心修复 2】严格限制积分幅值，防止饱和
    if (pid->integral >  pid->integral_max) pid->integral =  pid->integral_max;
    if (pid->integral < -pid->integral_max) pid->integral = -pid->integral_max;

    float derivative = error - pid->prev_error;
    pid->prev_error  = error;

    pid->output = pid->Kp * error
                + pid->Ki * pid->integral
                + pid->Kd * derivative;

    if (pid->output > pid->output_max)  pid->output =  pid->output_max;
    if (pid->output < -pid->output_max) pid->output = -pid->output_max;

    return pid->output;
}

void PID_Reset(PID_t *pid)
{
    pid->integral   = 0.0f;
    pid->prev_error = 0.0f;
    pid->output     = 0.0f;
}
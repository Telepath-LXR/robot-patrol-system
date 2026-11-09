#ifndef __PID_H
#define __PID_H

typedef struct {
    float Kp;
    float Ki;
    float Kd;
    float setpoint;
    float integral;
    float prev_error;
    float output;
    float integral_max;
    float output_max;
} PID_t;

void  PID_Init(PID_t *pid, float kp, float ki, float kd, float integral_max, float output_max);
void  PID_SetTarget(PID_t *pid, float setpoint);
float PID_Compute(PID_t *pid, float measurement);
void  PID_Reset(PID_t *pid);

#endif
#ifndef __IWDG_H__
#define __IWDG_H__

#ifdef __cplusplus
extern "C" {
#endif

#include "main.h"

void MX_IWDG_Init(void);
void IWDG_Feed(void);

#ifdef __cplusplus
}
#endif

#endif /* __IWDG_H__ */
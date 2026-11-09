import ctypes
import numpy as np

LIB_PATH = "~/voice/rknn-llm/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so"
lib = ctypes.CDLL(LIB_PATH)

# 简化封装：用 rkllm_create_default / rkllm_init / rkllm_run 这套 C API
# 具体结构体定义参考 rknn-llm/examples/llm/cpp 里的 rkllm.h

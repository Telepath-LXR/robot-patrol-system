#!/usr/bin/env python3
import numpy as np
from rknnlite.api import RKNNLite

MODEL_PATH = '~/yolo11.rknn'   # 改成你文件的实际路径

rknn = RKNNLite()
assert rknn.load_rknn(MODEL_PATH) == 0, 'load_rknn failed'
assert rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_0) == 0, 'init_runtime failed'

# 用一张任意图片或随机数据做一次推理，目的是拿到 outputs 结构
dummy_input = np.random.randint(0, 256, (1, 640, 640, 3), dtype=np.uint8)
outputs = rknn.inference(inputs=[dummy_input])

print(f'输出张量总数: {len(outputs)}')
for i, out in enumerate(outputs):
    print(f'  output[{i}]: shape={out.shape}, dtype={out.dtype}')

rknn.release()

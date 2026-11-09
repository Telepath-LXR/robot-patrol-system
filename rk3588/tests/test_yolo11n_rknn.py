#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK3588 板端最小推理验证：yolo11n_rk3588.rknn + 一张图 + 标准单头后处理。"""
import cv2
import numpy as np
from rknnlite.api import RKNNLite

CLASSES = [
    'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck',
    'boat', 'traffic light', 'fire hydrant', 'stop sign', 'parking meter', 'bench',
    'bird', 'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra',
    'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
    'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove',
    'skateboard', 'surfboard', 'tennis racket', 'bottle', 'wine glass', 'cup',
    'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple', 'sandwich', 'orange',
    'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
    'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse',
    'remote', 'keyboard', 'cell phone', 'microwave', 'oven', 'toaster', 'sink',
    'refrigerator', 'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier',
    'toothbrush'
]

IMG_SIZE = 640
CONF_THRES = 0.25
NMS_THRES = 0.45

def letterbox(img, new_shape=(IMG_SIZE, IMG_SIZE), color=(114, 114, 114)):
    h, w = img.shape[:2]
    r = min(new_shape[0] / h, new_shape[1] / w)
    new_unpad = (int(round(w * r)), int(round(h * r)))
    dw, dh = (new_shape[1] - new_unpad[0]) / 2, (new_shape[0] - new_unpad[1]) / 2
    if (w, h) != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right,
                             cv2.BORDER_CONSTANT, value=color)
    return img, r, (dw, dh)

def postprocess(output, ratio, pad, orig_hw, conf_thres, nms_thres):
    pred = np.squeeze(output).astype(np.float32)
    if pred.shape[0] < pred.shape[1]:
        pred = pred.T
    boxes_cxcywh, cls_scores = pred[:, :4], pred[:, 4:]
    class_ids = np.argmax(cls_scores, axis=1)
    confidences = cls_scores[np.arange(len(cls_scores)), class_ids]
    keep = confidences > conf_thres
    boxes_cxcywh = boxes_cxcywh[keep]
    class_ids, confidences = class_ids[keep], confidences[keep]
    if boxes_cxcywh.shape[0] == 0:
        return np.empty((0, 4)), np.empty(0, int), np.empty(0)
    dw, dh = pad
    x1 = (boxes_cxcywh[:, 0] - dw - boxes_cxcywh[:, 2] / 2) / ratio
    y1 = (boxes_cxcywh[:, 1] - dh - boxes_cxcywh[:, 3] / 2) / ratio
    x2 = (boxes_cxcywh[:, 0] - dw + boxes_cxcywh[:, 2] / 2) / ratio
    y2 = (boxes_cxcywh[:, 1] - dh + boxes_cxcywh[:, 3] / 2) / ratio
    h, w = orig_hw
    boxes_xyxy = np.stack([x1, y1, x2, y2], 1)
    boxes_xyxy[:, [0, 2]] = boxes_xyxy[:, [0, 2]].clip(0, w - 1)
    boxes_xyxy[:, [1, 3]] = boxes_xyxy[:, [1, 3]].clip(0, h - 1)
    idx = cv2.dnn.NMSBoxes(boxes_xyxy.tolist(), confidences.tolist(),
                           conf_thres, nms_thres)
    idx = np.array(idx).flatten() if len(idx) > 0 else np.empty(0, int)
    return boxes_xyxy[idx], class_ids[idx], confidences[idx]

def main():
    model_path = '~/yolo11n_rk3588.rknn'
    img_path = '~/000000000036.jpg'

    rknn = RKNNLite()
    assert rknn.load_rknn(model_path) == 0, 'load_rknn 失败'
    assert rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_0) == 0, 'init_runtime 失败'
    print(f'模型加载成功: {model_path}')

    img = cv2.imread(img_path)
    assert img is not None, f'图片读不到: {img_path}'
    orig_hw = img.shape[:2]
    print(f'原图尺寸: {orig_hw[1]}x{orig_hw[0]}')
    inp, ratio, pad = letterbox(img)
    inp_rgb = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB)
    input_data = np.expand_dims(inp_rgb, 0)

    outputs = rknn.inference(inputs=[input_data])
    out = outputs[0]
    print(f'推理输出形状: {out.shape}')

    boxes, cids, confs = postprocess(out, ratio, pad, orig_hw, CONF_THRES, NMS_THRES)
    print(f'后处理得到 {len(boxes)} 个检测:')
    for box, cid, conf in zip(boxes, cids, confs):
        print(f'  {CLASSES[int(cid)]:15s} score={conf:.3f} '
              f'box=({box[0]:.1f},{box[1]:.1f},{box[2]:.1f},{box[3]:.1f})')

    persons = [c for c in cids if CLASSES[int(c)] == 'person']
    print(f'\nperson 检测数量: {len(persons)}')
    rknn.release()

if __name__ == '__main__':
    main()

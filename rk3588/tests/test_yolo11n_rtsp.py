#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK3588 海康 RTSP 子码流实时推理（640x360，H.264）"""
import os
import cv2
import numpy as np
import time
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
CONF_THRES = 0.4
NMS_THRES = 0.45
RTSP_URL = os.environ.get("RTSP_URL", "rtsp://admin:<password>@<camera-ip>:554/Streaming/Channels/102")

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
    rknn = RKNNLite()
    assert rknn.load_rknn('~/yolo11n_rk3588.rknn') == 0
    assert rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_0) == 0
    print('模型加载成功')

    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        print(f'无法打开 RTSP: {RTSP_URL}')
        return

    # 读第一帧，确认尺寸
    ret, frame = cap.read()
    if not ret:
        print('读第一帧失败')
        cap.release()
        return
    print(f'RTSP 帧尺寸: {frame.shape[1]}x{frame.shape[0]}')

    fps_t0, fps_count, infer_ms_ema = time.time(), 0, 0.0

    try:
        while True:
            if frame is None:
                ret, frame = cap.read()
                if not ret:
                    print('读帧失败，重连...')
                    cap.release()
                    time.sleep(2)
                    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
                    ret, frame = cap.read()
                    if not ret:
                        break
                    continue

            orig_hw = frame.shape[:2]
            inp, ratio, pad = letterbox(frame)
            inp_rgb = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB)
            input_data = np.expand_dims(inp_rgb, 0)

            t0 = time.perf_counter()
            outputs = rknn.inference(inputs=[input_data])
            infer_ms = (time.perf_counter() - t0) * 1000.0
            infer_ms_ema = (0.9 * infer_ms_ema + 0.1 * infer_ms
                            if infer_ms_ema else infer_ms)

            boxes, cids, confs = postprocess(outputs[0], ratio, pad,
                                             orig_hw, CONF_THRES, NMS_THRES)

            persons = [(c, s) for c, s in zip(cids, confs)
                       if CLASSES[int(c)] == 'person']
            if persons:
                print(f'person x{len(persons)}: '
                      + ', '.join(f'score={s:.3f}' for _, s in persons))

            fps_count += 1
            if time.time() - fps_t0 >= 2.0:
                fps = fps_count / (time.time() - fps_t0)
                print(f'--- FPS: {fps:.1f}, 推理: {infer_ms_ema:.1f}ms ---')
                fps_t0, fps_count = time.time(), 0

            frame = None
            ret, frame = cap.read()
            if not ret:
                frame = None

    except KeyboardInterrupt:
        print('中断退出')
    finally:
        cap.release()
        rknn.release()

if __name__ == '__main__':
    main()

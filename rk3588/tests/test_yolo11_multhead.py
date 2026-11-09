#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YOLO11 多头模型 RTSP 实时推理 + 实时显示窗口"""
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

MODEL_PATH = '~/yolo11.rknn'
RTSP_URL   = os.environ.get("RTSP_URL", "rtsp://admin:<password>@<camera-ip>:554/Streaming/Channels/102")
IMG_SIZE   = 640
CONF_THRES = 0.5
NMS_THRES  = 0.45
STRIDES    = [8, 16, 32]
COLORS     = [(0, 255, 0), (255, 128, 0), (0, 128, 255), (255, 0, 255)]


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


def dfl_decode(box_dist):
    _, H, W = box_dist.shape
    x = box_dist.reshape(4, 16, H, W).transpose(0, 2, 3, 1)
    x = x - x.max(axis=-1, keepdims=True)
    exp = np.exp(x)
    softmax = exp / exp.sum(axis=-1, keepdims=True)
    bins = np.arange(16, dtype=np.float32)
    return (softmax * bins).sum(axis=-1)


def postprocess(outputs, orig_hw, ratio, pad_w, pad_h):
    h, w = orig_hw
    all_boxes, all_scores, all_cids = [], [], []

    for i, stride in enumerate(STRIDES):
        box_dist = outputs[i * 3][0]
        cls_score = outputs[i * 3 + 1][0]
        conf_sum = outputs[i * 3 + 2][0]

        mask = conf_sum[0] > 0.1
        if not np.any(mask):
            continue
        grid_y, grid_x = np.where(mask)

        scores = cls_score[:, grid_y, grid_x]
        cids = np.argmax(scores, axis=0)
        max_scores = scores[cids, np.arange(len(grid_x))]

        keep = max_scores > CONF_THRES
        if not np.any(keep):
            continue
        grid_x, grid_y = grid_x[keep], grid_y[keep]
        cids, max_scores = cids[keep], max_scores[keep]

        dist = dfl_decode(box_dist)
        d = dist[:, grid_y, grid_x]

        x1 = (-d[0] + grid_x + 0.5) * stride
        y1 = (-d[1] + grid_y + 0.5) * stride
        x2 = ( d[2] + grid_x + 0.5) * stride
        y2 = ( d[3] + grid_y + 0.5) * stride

        x1 = (x1 - pad_w) / ratio; y1 = (y1 - pad_h) / ratio
        x2 = (x2 - pad_w) / ratio; y2 = (y2 - pad_h) / ratio
        x1 = np.clip(x1, 0, w - 1); y1 = np.clip(y1, 0, h - 1)
        x2 = np.clip(x2, 0, w - 1); y2 = np.clip(y2, 0, h - 1)

        all_boxes.append(np.stack([x1, y1, x2, y2], axis=1))
        all_scores.append(max_scores)
        all_cids.append(cids)

    if not all_boxes:
        return np.empty((0, 4)), np.empty(0, int), np.empty(0)

    boxes = np.concatenate(all_boxes, axis=0)
    scores = np.concatenate(all_scores, axis=0)
    cids = np.concatenate(all_cids, axis=0)

    xywh = boxes.copy()
    xywh[:, 2] = boxes[:, 2] - boxes[:, 0]
    xywh[:, 3] = boxes[:, 3] - boxes[:, 1]
    idx = cv2.dnn.NMSBoxes(xywh.tolist(), scores.tolist(), CONF_THRES, NMS_THRES)
    idx = np.array(idx).flatten() if len(idx) > 0 else np.empty(0, int)
    return boxes[idx], cids[idx], scores[idx]


def main():
    rknn = RKNNLite()
    assert rknn.load_rknn(MODEL_PATH) == 0, 'load_rknn 失败'
    assert rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_0) == 0, 'init_runtime 失败'
    print(f'模型加载成功: {MODEL_PATH}')

    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        print(f'无法打开 RTSP: {RTSP_URL}')
        return
    ret, frame = cap.read()
    if not ret:
        print('读第一帧失败'); cap.release(); return
    print(f'RTSP 帧尺寸: {frame.shape[1]}x{frame.shape[0]}')
    print('实时窗口已打开，按 q 退出')

    cv2.namedWindow('YOLO11 RK3588', cv2.WINDOW_NORMAL)

    fps_t0, fps_count, infer_ema = time.time(), 0, 0.0
    fps_display = 0.0

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
            inp, ratio, (dw, dh) = letterbox(frame)
            inp_rgb = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB)
            x = np.expand_dims(inp_rgb, 0)

            t0 = time.perf_counter()
            outputs = rknn.inference(inputs=[x])
            infer_ms = (time.perf_counter() - t0) * 1000.0
            if outputs is None:
                break
            infer_ema = (0.9 * infer_ema + 0.1 * infer_ms) if infer_ema else infer_ms

            boxes, cids, confs = postprocess(outputs, orig_hw, ratio, dw, dh)

            # 画框
            annotated = frame.copy()
            for box, cid, conf in zip(boxes, cids, confs):
                x1, y1, x2, y2 = map(int, box)
                color = COLORS[int(cid) % len(COLORS)]
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                label = f'{CLASSES[int(cid)]} {conf:.2f}'
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                cv2.rectangle(annotated, (x1, max(y1 - th - 6, 0)),
                              (x1 + tw + 4, max(y1, th + 6)), color, -1)
                cv2.putText(annotated, label, (x1 + 2, max(y1 - 6, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

            # 左上角显示 FPS 和推理耗时
            fps_count += 1
            now = time.time()
            if now - fps_t0 >= 1.0:
                fps_display = fps_count / (now - fps_t0)
                fps_t0, fps_count = now, 0
            info = f'FPS: {fps_display:.1f}  Infer: {infer_ema:.1f}ms  Obj: {len(boxes)}'
            cv2.putText(annotated, info, (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

            persons = [s for c, s in zip(cids, confs) if CLASSES[int(c)] == 'person']
            if persons:
                print(f'person x{len(persons)}: '
                      + ', '.join(f'{s:.3f}' for s in persons))

            cv2.imshow('YOLO11 RK3588', annotated)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                print('按 q 退出')
                break

            ret, frame = cap.read()
            if not ret:
                frame = None

    except KeyboardInterrupt:
        print('\n中断退出')
    finally:
        cap.release()
        rknn.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()

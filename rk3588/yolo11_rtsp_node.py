#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import cv2
import numpy as np
import time
import threading
import rclpy
import os
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from vision_msgs.msg import Detection2DArray, Detection2D, ObjectHypothesisWithPose
from std_msgs.msg import String
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
RTSP_URL   = os.environ.get("RTSP_URL", "rtsp://admin:<password>@<camera-ip>:554/Streaming/Channels/102?tcp")
IMG_SIZE   = 640
CONF_THRES = 0.5
NMS_THRES  = 0.45
STRIDES    = [8, 16, 32]

BASE_DIR = "~/voice"
PENDING_DIR = os.path.join(BASE_DIR, "pending_records")
SAFE_DIR = os.path.join(BASE_DIR, "safe_records")
DANGER_DIR = os.path.join(BASE_DIR, "danger_records")
os.makedirs(PENDING_DIR, exist_ok=True)
os.makedirs(SAFE_DIR, exist_ok=True)
os.makedirs(DANGER_DIR, exist_ok=True)

def letterbox(img, new_shape=(IMG_SIZE, IMG_SIZE), color=(114, 114, 114)):
    h, w = img.shape[:2]
    r = min(new_shape[0] / h, new_shape[1] / w)
    new_unpad = (int(round(w * r)), int(round(h * r)))
    dw, dh = (new_shape[1] - new_unpad[0]) / 2, (new_shape[0] - new_unpad[1]) / 2
    if (w, h) != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
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
        if not np.any(mask): continue
        grid_y, grid_x = np.where(mask)
        scores = cls_score[:, grid_y, grid_x]
        cids = np.argmax(scores, axis=0)
        max_scores = scores[cids, np.arange(len(grid_x))]
        keep = max_scores > CONF_THRES
        if not np.any(keep): continue
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
    if not all_boxes: return np.empty((0, 4)), np.empty(0, int), np.empty(0)
    boxes = np.concatenate(all_boxes, axis=0)
    scores = np.concatenate(all_scores, axis=0)
    cids = np.concatenate(all_cids, axis=0)
    xywh = boxes.copy()
    xywh[:, 2] = boxes[:, 2] - boxes[:, 0]
    xywh[:, 3] = boxes[:, 3] - boxes[:, 1]
    idx = cv2.dnn.NMSBoxes(xywh.tolist(), scores.tolist(), CONF_THRES, NMS_THRES)
    idx = np.array(idx).flatten() if len(idx) > 0 else np.empty(0, int)
    return boxes[idx], cids[idx], scores[idx]

class YoloDetectorNode(Node):
    def __init__(self):
        super().__init__('yolo_detector_node')
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=1)
        self.pub_det = self.create_publisher(Detection2DArray, '/detections', 10)
        self.alarm_pub = self.create_publisher(String, '/safety_alarm', 10)
        
        self.create_subscription(String, '/auth_status', self.auth_cb, 10)
        self.create_subscription(String, '/system_mode', self.mode_cb, 10)
        self.create_subscription(String, '/safety_alarm', self.alarm_cb, 10) # 监听 STOP_ALARM
        
        self.auth_status = "NONE"
        self.system_mode = "cruise"
        self.pending_img_path = ""
        self.last_alert_time = 0.0
        self.cooldown_time = 0.0 # 冷却时间

        self.rknn = RKNNLite()
        assert self.rknn.load_rknn(MODEL_PATH) == 0, 'load_rknn 失败'
        assert self.rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_0) == 0, 'init_runtime 失败'
        
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.running = True
        threading.Thread(target=self.capture_loop, daemon=True).start()
        threading.Thread(target=self.infer_loop, daemon=True).start()

    def mode_cb(self, msg):
        self.system_mode = msg.data
        self.get_logger().info(f'🔄 系统模式切换为: {self.system_mode}')

    def auth_cb(self, msg):
        self.auth_status = msg.data
        if self.auth_status in ["SUCCESS", "FAILED"]:
            if os.path.exists(self.pending_img_path):
                target_dir = SAFE_DIR if self.auth_status == "SUCCESS" else DANGER_DIR
                target_path = os.path.join(target_dir, os.path.basename(self.pending_img_path))
                os.rename(self.pending_img_path, target_path)
                self.pending_img_path = ""
            self.cooldown_time = time.time() # 记录验证结束时间
            if self.auth_status == "SUCCESS":
                self.get_logger().info('✅ 验证成功，进入 10 秒冷却期')
                # 10秒后允许重新报警
                threading.Timer(10.0, self.reset_success_status).start()
            elif self.auth_status == "FAILED":
                self.get_logger().info('🚨 验证失败，无限锁死报警')
                # 失败状态不自动重置，直到收到 STOP_ALARM

    def reset_success_status(self):
        if self.auth_status == "SUCCESS":
            self.auth_status = "NONE"

    def alarm_cb(self, msg):
        if msg.data == "STOP_ALARM":
            self.auth_status = "NONE"
            self.cooldown_time = time.time() # 点击解除后，再次进入 10 秒冷却
            self.get_logger().info('🔓 收到人工确认，清除报警状态')

    def capture_loop(self):
        cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        while self.running and rclpy.ok():
            cap.grab()
            ret, frame = cap.retrieve()
            if not ret:
                time.sleep(2)
                cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                continue
            with self.frame_lock:
                self.latest_frame = frame
        cap.release()

    def infer_loop(self):
        processed_frame_id = None
        while self.running and rclpy.ok():
            with self.frame_lock:
                frame = self.latest_frame
            if frame is None: time.sleep(0.01); continue
            frame_id = id(frame)
            if frame_id == processed_frame_id: time.sleep(0.005); continue
            processed_frame_id = frame_id

            orig_hw = frame.shape[:2]
            inp, ratio, (dw, dh) = letterbox(frame)
            inp_rgb = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB)
            x = np.expand_dims(inp_rgb, 0)
            outputs = self.rknn.inference(inputs=[x])
            if outputs is None: continue
            boxes, cids, confs = postprocess(outputs, orig_hw, ratio, dw, dh)

            det_arr = Detection2DArray()
            det_arr.header.stamp = self.get_clock().now().to_msg()
            det_arr.header.frame_id = 'camera_link'

            for box, cid, conf in zip(boxes, cids, confs):
                det = Detection2D()
                det.header = det_arr.header
                hyp = ObjectHypothesisWithPose()
                hyp.hypothesis.class_id = CLASSES[int(cid)]
                hyp.hypothesis.score = float(conf)
                det.results.append(hyp)
                x1, y1, x2, y2 = box
                det.bbox.center.position.x = float((x1 + x2) / 2.0)
                det.bbox.center.position.y = float((y1 + y2) / 2.0)
                det.bbox.size_x = float(x2 - x1)
                det.bbox.size_y = float(y2 - y1)
                det_arr.detections.append(det)
                
                # 仅在安防模式下，且不在冷却期内，且不是失败死锁状态
                if CLASSES[int(cid)] == 'person' and self.system_mode == "security":
                    time_since_cooldown = time.time() - self.cooldown_time
                    if time_since_cooldown > 10.0 and self.auth_status not in ["PENDING", "FAILED"]:
                        self.last_alert_time = time.time()
                        self.auth_status = "PENDING"
                        self.cooldown_time = time.time()
                        
                        img_time = time.strftime("%Y%m%d_%H%M%S")
                        self.pending_img_path = os.path.join(PENDING_DIR, f"intruder_{img_time}.jpg")
                        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
                        cv2.imwrite(self.pending_img_path, frame)
                        self.get_logger().warn(f"🚨 [安防模式] 发现闯入者！")
                        msg = String()
                        msg.data = "INTRUDER_DETECTED"
                        self.alarm_pub.publish(msg)

            self.pub_det.publish(det_arr)

    def destroy_node(self):
        self.running = False
        self.rknn.release()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = YoloDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()

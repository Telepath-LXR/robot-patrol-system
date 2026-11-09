# 差速轮目标速度指令（单位 m/s）
# 由上层决策节点或 teleop 产生，最终由 serial_bridge_node 转成 0x01 协议帧
float32 left_speed
float32 right_speed

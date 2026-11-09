# 具身智能巡检机器人（Embodied Intelligent Patrol Robot）

一套 **PC + RK3588 + STM32F407** 三级异构巡检安防机器人系统：

- **自主导航**：Nav2（AMCL + DWB），Gazebo 仿真中实测最高 1.5 m/s
- **视觉安防**：RK3588 NPU 跑 YOLO11（FP16 多头 + 手写 DFL 解码），RTSP 网络相机，约 23Hz 检测帧率
- **语音交互**：KWS 唤醒（sherpa-onnx Zipformer）+ SenseVoice ASR + Qwen2.5-1.5B（RKLLM）+ MeloTTS 全离线语音栈
- **安防双模式**：巡航/安防切换；安防模式下见人锁死底盘 + 现场截图 + 免唤醒强制录音 5 秒 + 密码验证 + 失败无限报警 + PC 远程人工确认
- **硬件在环（HIL）闭环**：STM32 跑真实 1kHz 双轮 PID 固件，通过自定义串口协议驱动 Gazebo 里的虚拟小车——"真固件，假世界"

## 系统架构

```
┌──────────────┐  CycloneDDS(单播)  ┌───────────────┐  UART 115200  ┌──────────────┐
│  PC (Ubuntu) │ ◄───────────────► │    RK3588     │ ◄───────────► │  STM32F407   │
│ Nav2/Gazebo/ │                   │ YOLO/语音/LLM │   自定义协议    │ 1kHz PID 固件 │
│  Dashboard   │                   │   串口网关     │  CRC16+8态机   │  (rcc2 工程)  │
└──────────────┘                   └───────────────┘               └──────────────┘
```

全车速度指令的唯一出口是 PC 端 `dashboard_node` 的 `/cmd_vel_input` 话题，仲裁优先级：
**安防警报锁存 > 急停锁存 > 行人刹车（2s 迟滞）> Nav2 > 语音/手动**。
所有阻断动作都主动发布全零 Twist，绝不"沉默"。

## 目录结构

```
├── pc/                     # PC 端（Ubuntu 22.04 + ROS2 Humble）
│   ├── robot_dashboard.py      # 总控台：速度仲裁唯一出口 + 安防 UI + 进程编排（PyQt5）
│   ├── hil_bridge_sim.py       # HIL 虚拟电机/编码器（100Hz 强塞零速兜底）
│   ├── cyclonedds_pc.xml       # CycloneDDS 单播配置（PC 侧）
│   ├── patrol_description/     # ROS2 包：URDF + Gazebo world + 地图 + Nav2 参数 + launch
│   ├── robot_interfaces/       # 自定义消息（MotorCommand / MotorState）
│   └── tests/                  # 协议对拍测试（双端逐字节 100% 一致）
├── rk3588/                 # RK3588 端（Ubuntu 22.04 + ROS2 Humble + RKNN）
│   ├── yolo11_rtsp_node.py     # RTSP 视觉安防节点（NPU 推理 + 检测发布 + 安防落盘）
│   ├── hil_bridge.py           # HIL 串口桥（0x07 编码器注入 / 0x08 PWM 回读）
│   ├── cyclonedds_rk.xml       # CycloneDDS 单播配置（RK 侧）
│   ├── robot_serial/           # 实机串口桥包（protocol.py + serial_bridge_node.py）
│   ├── robot_interfaces/       # 与 PC 同源的消息定义
│   ├── voice/                  # 语音栈：assistant.py 主程序 + KWS 词表 + LLM Flask 服务
│   └── tests/                  # 串口注入测试、视觉验证脚本、语音测试脚本
├── firmware/
│   └── rcc2/               # STM32F407 最终固件工程（Core + rcc2.ioc + Keil 工程文件）
│                           # Drivers/ 与 Middlewares/ 由 CubeMX 打开 rcc2.ioc 重新生成
├── deploy/
│   ├── 99-robot-mcu.rules      # udev：PL2303 固定为 /dev/robot_mcu
│   └── 99-robot-pclink.rules   # udev：备用对录串口
├── docs/
│   └── DEPLOY.md               # 分层复现指南 L0~L4（小白从这里开始）
└── scripts/
    └── check_env.sh            # 环境自检脚本（只检查不修改）
```

## 通信协议（PC/RK ↔ STM32）

帧格式：`[0xAA][0x55][TYPE][LEN][DATA(≤32B)][CRC16_H][CRC16_L][0x0D]`

- CRC-16/CCITT-FALSE（0x1021 / 初值 0xFFFF，校验向量 `"123456789"→0x29B1`）
- 混合字节序：payload 小端，CRC16 大端传输
- 帧类型：0x01 速度下行 / 0x02 里程计 / 0x03 电压 / 0x04 IMU / 0x05 心跳 / 0x06 应答；0x07/0x08 为 HIL 私有扩展

## 依赖与环境

见各目录下的 requirements：

- PC：`pc/requirements.txt`（rclpy、PyQt5 等；系统级依赖 ROS2 Humble + Gazebo + Nav2）
- RK3588：`rk3588/requirements.txt`（rknn-toolkit-lite2、sherpa-onnx 等；模型需单独下载）

**模型文件不入库**（共约 3.5GB），需要的模型与获取方式见 `rk3588/README_MODELS.md`（YOLO11 FP16 多头、sherpa-onnx KWS/SenseVoice-ASR/MeloTTS、Qwen2.5-1.5B-Instruct RKLLM w8a8）。

**第三方 ROS2 包不入库**，请自行 clone 到工作区：
- [m-explore-ros2](https://github.com/robo-friends/m-explore-ros2)（自主探索，可选）
- [gazebo_models_worlds_collection](https://gitee.com/)（Gazebo 离线模型/世界集）

## 快速开始（最小复现）

> ⚠️ **这个仓不是 clone 下来一键跑的**——它横跨 PC / RK3588 / STM32 三套硬件，依赖模型 3.5GB。
> **第一次来，请直接看 👉 [`docs/DEPLOY.md`](docs/DEPLOY.md)**：它把复现拆成 L0~L4 五层，从 0 元的纯 PC 仿真开始，每层都有"怎么算跑通了"的判据，强烈建议按层来，不要想着一步全亮。

最快的一步（L0 纯仿真，0 元，只要一台 Ubuntu22.04 电脑）：

```bash
# 装 ROS2 Humble + Nav2 + Gazebo（命令见 docs/DEPLOY.md L0）
mkdir -p ~/ros2_ws/src && cd ~/ros2_ws/src
cp -r <本仓库>/pc/{patrol_description,robot_interfaces} .
cd ~/ros2_ws && source /opt/ros/humble/setup.bash
colcon build --packages-select robot_interfaces && source install/setup.bash
colcon build --packages-select patrol_description && source install/setup.bash

# 三个终端分别：
ros2 launch patrol_description gazebo_sim.launch.py   # 仿真世界
ros2 launch patrol_description nav2_bringup.launch.py  # 导航
rviz2                                                    # 看效果
```
Gazebo 里小车能用 "2D Goal Pose" 指点导航，L0 就通了。

## 一键环境自检

拿不准自己装对没有，跑这个（只检查不修改）：
```bash
bash scripts/check_env.sh
```
在 PC 上跑查 PC 的、在 RK3588 上跑查 RK 的，自动识别。`✗` 必须解决，`!` 看情况。

## 完整部署（含硬件）

从 L0 仿真一路加到 L4 全套实机的分层步骤、每层硬件清单/接线/验证判据/踩坑表，全部在 **`docs/DEPLOY.md`**。

## 安全说明

- 代码中的 RTSP 相机凭据、内网 IP 均已脱敏为环境变量或占位符，部署时按实际填写
- 安防密码（0929）为演示功能设计，生产环境请修改 `rk3588/voice/assistant.py` 中的验证逻辑

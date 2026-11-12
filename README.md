# 具身智能巡检机器人（Embodied Intelligent Patrol Robot）

一套基于 **PC + RK3588 + STM32F407** 的三级异构巡检安防机器人系统。本项目不仅实现了完整的自主导航与安防业务闭环，更提供了一套**“真固件，假世界”**的硬件在环（HIL）仿真验证方案，实现仿真到真车的零成本迁移。

### 🌟 核心特性 (Features)

- **自主导航**：基于 ROS2 Nav2（AMCL + DWB），结合 Gazebo 物理仿真，实测最高巡航速度 1.5 m/s，支持自主探索与定点导航。
- **视觉安防**：RK3588 NPU 部署 YOLO11，使用 **FP16 多头模型 + 纯 NumPy 手写 DFL 解码**，RTSP 网络流拉取，实现约 **23Hz** 实时目标检测。
- **全离线语音栈**：KWS 唤醒（sherpa-onnx Zipformer）+ SenseVoice ASR + Qwen2.5-1.5B（RKLLM 单核 NPU）+ MeloTTS。支持免唤醒词强制录音与密码口令验证。
- **安防双模式**：支持巡航/安防模式无缝切换；安防模式下“见人锁死底盘 → 现场截图 → 免唤醒强制录音 5s → 密码验证（0929）→ 失败无限报警 → PC 端远程人工确认”。
- **HIL 硬件在环**：STM32 跑真实 1kHz 双轮 PID 固件，通过自定义串口协议（0x07/0x08）驱动 Gazebo 里的虚拟小车，实现真实控制闭环。
- **集中仲裁与物理隔离**：全车速度唯一出口收敛至 PC 端 `/cmd_vel_input`，采用“安防 > 急停 > 行人(2s迟滞) > Nav2 > 语音”五级优先级链；通过 URDF 话题重映射实现底盘执行权的物理隔离。

---

## 📐 系统架构与数据流

```text
┌──────────────┐  CycloneDDS(单播)  ┌───────────────┐  UART 115200  ┌──────────────┐
│  PC (Ubuntu) │ ◄───────────────► │    RK3588     │ ◄───────────► │  STM32F407   │
│ Nav2/Gazebo/ │                   │ YOLO/语音/LLM │   自定义协议    │ 1kHz PID 固件 │
│  Dashboard   │                   │   串口网关     │  CRC16+8态机   │  (rcc2 工程)  │
└──────────────┘                   └───────────────┘               └──────────────┘
```

*   **全车速度唯一出口**：所有控制节点（导航、语音、急停）绝不直接控制底盘，统一交由 PC 端 `dashboard_node` 仲裁后，发布 `/cmd_vel_input`。
*   **安全防御底线**：所有阻断/刹车动作，均采用主动发布全零 `Twist` 强制覆盖，杜绝因节点死机导致的“指令沉默”。
*   **HIL 闭环回路**：STM32 接收虚拟编码器注入（0x07），计算出真实 PWM 回传（0x08）；PC 端再将其映射为 Gazebo 的速度，彻底打通虚实链路。

---

## 🧠 核心技术细节 (Deep Dive)

### 1. STM32 + FreeRTOS 底层控制
*   **多任务调度**：CommTask（通信）、CtrlTask（1kHz PID）、AcqTask（采集）、ImuTask（姿态）。
*   **硬实时保障**：使用 `vTaskDelayUntil` 取代普通延时，DWT 实测 1kHz 控制周期抖动 < 50µs；针对浮点运算开启 FPU 并扩容任务栈。
*   **双重看门狗**：软件心跳看门狗（500ms 断联清 PWM）+ 硬件 IWDG（1s 物理复位，防固件跑飞）。
*   **外设防暴死**：USART2 + DMA + IDLE 空闲中断接收变长帧（规避中断风暴）；I2C 读写强制 10ms 超时（防传感器掉线卡死）。

### 2. 自定义二进制协议
*   **帧格式**：`[0xAA][0x55][TYPE][LEN][DATA][CRC16_H][CRC16_L][0x0D]`
*   **混合字节序**：业务数据小端（配合 ARM 架构零开销），CRC16 大端传输。
*   **8 态状态机**：带 `resync` 重同步机制，对抗半帧与噪声干扰；CRC 校验采用 CCITT-FALSE 算法，国际校验向量 `123456789 -> 0x29B1`。
*   **HIL 私有扩展**：0x07（注入虚拟编码器增量）、0x08（回传真实 PID 计算出的 PWM）。

### 3. NPU 边缘 AI 部署
*   **规避量化坍缩**：舍弃原生单头输出，改用 **9 输出多头 FP16**，避免坐标大数值撑爆分类 Scale。
*   **CPU 后处理**：手写 NumPy DFL（Distribution Focal Loss）解码，配合 `conf_sum` 张量做 Filter-First 粗筛，极大降低 CPU 算力。
*   **RTSP 延迟治理**：通过强制 TCP 拉流、压减 Buffer、生产者-消费者跳帧策略，将端到端延迟压至 80ms 内。

### 4. 集中仲裁与物理隔离
*   **五级优先级**：`安防警报(最高) > 急停锁存 > 行人刹车 > Nav2 > 语音/手动(最低)`。
*   **解决抢占**：Nav2 多个节点天生会强占 `/cmd_vel`，本项目在 URDF 中将 Gazebo 底盘控制话题 Remapping 为 `/cmd_vel_sim`，彻底切断了导航算法与执行器的底层直连，急停失效问题被连根拔起。

---

## 📁 目录结构

```text
├── pc/                     # PC 端（Ubuntu 22.04 + ROS2 Humble）
│   ├── robot_dashboard.py      # 总控台：五级仲裁唯一出口 + 安防 UI + 跨机进程编排（PyQt5）
│   ├── hil_bridge_sim.py       # HIL 虚拟电机/编码器（100ms 强塞零速兜底）
│   ├── cyclonedds_pc.xml       # CycloneDDS 单播配置（防组播风暴）
│   ├── patrol_description/     # ROS2 包：极简 7-link URDF + Gazebo 环境 + Nav2 参数 + Launch
│   ├── robot_interfaces/       # 自定义消息（MotorCommand / MotorState）
│   └── tests/                  # 协议对拍测试（双端逐字节 100% 一致）
├── rk3588/                 # RK3588 端（Ubuntu 22.04 + ROS2 Humble + RKNN）
│   ├── yolo11_rtsp_node.py     # RTSP 视觉安防节点（NPU 推理 + 检测发布 + 安防落盘）
│   ├── hil_bridge.py           # HIL 串口桥（0x07 注入 / 0x08 回读，含 DTR/RTS 防死锁）
│   ├── cyclonedds_rk.xml       # CycloneDDS 单播配置（RK 侧）
│   ├── robot_serial/           # 实机串口桥包（protocol.py + serial_bridge_node.py）
│   ├── robot_interfaces/       # 与 PC 同源的消息定义
│   ├── voice/                  # 语音栈：assistant.py 主程序 + KWS 词表 + LLM Flask 服务
│   └── tests/                  # 串口 pty 注入测试、视觉验证脚本
├── firmware/
│   └── rcc2/               # STM32F407 最终固件工程（CubeMX 配置 + Keil 工程）
├── deploy/
│   ├── 99-robot-mcu.rules      # udev 规则：PL2303 固定为 /dev/robot_mcu
│   └── 99-robot-pclink.rules   # udev：备用对录串口
├── docs/
│   └── DEPLOY.md               # 分层复现指南 L0~L4
└── scripts/
    └── check_env.sh            # 环境自检脚本（只检查不修改）
```

---

## 📊 实测性能指标

*   **通信延迟**：心跳 100.3ms（min 100.2 / max 100.4），216/216 全应答；DDS 跨机延迟数十毫秒。
*   **HIL 闭环延迟**：从 Gazebo 物理引擎到 STM32 真实 PID 再回到 Gazebo，全链路延迟 **8~21ms**。
*   **控制周期**：STM32 控制环严格 1kHz，DWT 实测抖动 < 50µs。
*   **AI 推理**：YOLO11 跨机检测帧率 23Hz，RTSP 端到端延迟 40~80ms。
*   **大模型**：Qwen2.5-1.5B w8a8，单核 NPU 约 8 token/s，首 token 延迟 1.5~2s。

---

## ⚙️ 通信协议（PC/RK ↔ STM32）

*   **帧格式**：`[0xAA][0x55][TYPE][LEN][DATA(≤32B)][CRC16_H][CRC16_L][0x0D]`
*   **校验算法**：CRC-16/CCITT-FALSE（多项式 0x1021，初值 0xFFFF，校验向量 `"123456789"→0x29B1`）。
*   **帧类型**：
    *   `0x01` 速度下行（左右轮目标线速度）
    *   `0x02` 里程计上行（x, y, theta）
    *   `0x03` 电压上行（电池电压）
    *   `0x04` IMU 上行（MPU6050 六轴）
    *   `0x05` 心跳下行 / `0x06` 心跳应答
    *   `0x07` 编码器注入（HIL 私货） / `0x08` PWM 回传（HIL 私货）

---

## 📦 依赖与环境

模型文件与第三方 ROS2 包**不入库**，请按需自行下载：
*   **模型文件（共约 3.5GB）**：见 `rk3588/README_MODELS.md`（YOLO11 FP16 多头、sherpa-onnx KWS、SenseVoice-ASR、MeloTTS、Qwen2.5-1.5B RKLLM w8a8）。
*   **第三方包**：`m-explore-ros2`（自主探索）、`gazebo_models_worlds_collection`（Gazebo 离线模型）。

---

## 🚀 快速开始（L0 纯仿真）

> ⚠️ **这个仓不是 clone 下来一键跑的**——它横跨 PC / RK3588 / STM32 三套硬件。
> **第一次来，请直接看 👉 [`docs/DEPLOY.md`](docs/DEPLOY.md)**：它把复现拆成 L0~L4 五层，强烈建议按层来。

最快的一步（L0 纯仿真，只要一台 Ubuntu22.04 电脑）：

```bash
# 装 ROS2 Humble + Nav2 + Gazebo
mkdir -p ~/ros2_ws/src && cd ~/ros2_ws/src
cp -r <本仓库>/pc/{patrol_description,robot_interfaces} .
cd ~/ros2_ws && source /opt/ros/humble/setup.bash
colcon build --packages-select robot_interfaces && source install/setup.bash
colcon build --packages-select patrol_description && source install/setup.bash

# 三个终端分别：
ros2 launch patrol_description gazebo_sim.launch.py   # 仿真世界
ros2 launch patrol_description nav2_bringup.launch.py  # 导航
rviz2                                                  # 看效果
```

---

## 🛡️ 安全与部署说明

*   代码中的 RTSP 相机凭据、内网 IP 均已脱敏为环境变量或占位符。
*   安防密码（`0929`）为演示功能设计，生产环境请修改 `rk3588/voice/assistant.py` 中的验证逻辑。
*   若遇 `ros2 daemon` 幽灵节点，请执行 `ros2 daemon stop && ros2 daemon start` 清理。
*   若遇 RViz 无法接收地图，请确保 Map 话题 QoS 设置为 **Transient Local**。

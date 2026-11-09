# 分层复现指南（从 0 元仿真到全套实机）

这个仓不是"clone 下来一键跑"的项目——它横跨 PC、RK3588、STM32 三套硬件，依赖模型加起来 3.5GB。**对小白，唯一不劝退的走法是一层层来**，每层跑通了都有正反馈，再决定要不要往下投入。

```
L0  纯 PC 仿真          0 元      Gazebo + Nav2 全栈，小车自己巡点
L1  +STM32+PL2303      ~100 元   HIL 闭环：真 1kHz PID 固件驱动仿真小车
L2  +RK3588            ~800 元   决策下板，跨机 DDS + 串口走真实链路
L3  +RTSP 相机         ~200 元   视觉安防：入侵检测/锁死/截图/报警
L4  +ReSpeaker 麦克风   ~200 元   全离线语音栈：唤醒→识别→大模型→合成
```

**强烈建议从 L0 开始**。L0 不需要买任何东西，跑通了你就知道这套系统的"大脑"长什么样，后面每加一层硬件只是替换最底层的执行端，上层代码一行不改。

---

## L0：纯 PC 仿真（0 元，必做）

**目标**：在一台普通 Ubuntu 电脑上，让 Gazebo 里的小车用 Nav2 自主导航。

### 硬件
一台 x86 电脑，装 **Ubuntu 22.04**（虚拟机也行，但 Gazebo 会卡，建议物理机 + 独显）。

### 安装
```bash
# 1. ROS2 Humble（官方一键脚本，国内建议先换源）
#    参考 https://docs.ros.org/en/humble/Installation.html
sudo apt install ros-humble-desktop -y

# 2. 本项目需要的 ROS2 包
sudo apt install -y \
    ros-humble-navigation2 ros-humble-nav2-bringup \
    ros-humble-slam-toolbox ros-humble-gazebo-ros-pkgs \
    ros-humble-robot-state-publisher ros-humble-xacro \
    ros-humble-rmw-cyclonedds-cpp ros-humble-cyclonedds \
    gazebo python3-colcon-common-extensions python3-pip

# 3. Python 依赖
pip3 install -r pc/requirements.txt
```

### 编译
```bash
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
cp -r <本仓库>/pc/patrol_description .
cp -r <本仓库>/pc/robot_interfaces .
cd ~/ros2_ws

source /opt/ros/humble/setup.bash
colcon build --packages-select robot_interfaces   # 先编译自定义消息
source install/setup.bash
colcon build --packages-select patrol_description # 再编译依赖它的包
source install/setup.bash
```

### 运行（开 3 个终端，每个都先 `source /opt/ros/humble/setup.bash && source ~/ros2_ws/install/setup.bash`）
```bash
# 终端1：仿真世界 + 小车
ros2 launch patrol_description gazebo_sim.launch.py

# 终端2：Nav2 导航（等终端1的 Gazebo 完全起来再开）
ros2 launch patrol_description nav2_bringup.launch.py

# 终端3：RViz 看效果（可选）
rviz2 -d ~/ros2_ws/install/patrol_description/share/patrol_description/rviz/patrol.rviz
```

### ✅ 怎么算跑通了
- Gazebo 弹出一个带四面墙（或办公室）的世界，中间一辆蓝色小车
- RViz 里能看到红色激光点打在线框墙上
- 在 RViz 工具栏点 **"2D Goal Pose"**，在地上拖一个箭头，**小车自己规划路线开过去**——这就是 Nav2

### 这层最常见的坑
| 现象 | 原因 | 解法 |
|---|---|---|
| Gazebo 起不来/卡死 | 联网下载模型被墙 | launch 里已禁用联网；首次启动慢属正常，等 30s |
| RViz 里地图是黑的 | Nav2 还没 localize | 用 "2D Pose Estimate" 在地上点一下小车的初始位置 |
| 车不动/原地打转 | Nav2 生命周期节点没激活 | 看终端2有没有 `Managed nodes are active`；没有就重启终端2 |

---

## L1：HIL 硬件在环（+STM32，~100 元）

**目标**：让一块**真实的 STM32F407 跑着 1kHz PID 固件**，通过串口驱动 Gazebo 里的虚拟小车——"真固件，假世界"。这是本项目最核心也最有意思的一层。

### 硬件
| 件 | 型号 | 作用 |
|---|---|---|
| STM32 开发板 | STM32F407（正点原子探索者即可） | 跑真实电机控制固件 |
| USB 转串口 | **PL2303**（不要用 CH341，内核 6.12+ 没驱动） | PC ↔ STM32 |
| 杜邦线 | 3 根 | TX/RX/GND |

### 接线
```
STM32 USART2:  PA2(TX) ──► PL2303 RX
               PA3(RX) ◄── PL2303 TX
               GND     ───  GND      （必须共地！）
```
> 全程用 **USART2 (PA2/PA3)**，不是 PA9/PA10（那是 USART1，项目早期文档的残留笔误）。

### 烧录固件
```bash
# 固件只需要 Core/ 里的代码，Drivers/ 和 Middlewares/ 用 CubeMX 重新生成：
# 1. 打开 STM32CubeMX，加载 firmware/rcc2/rcc2.ioc，点 "Generate Code"
# 2. 用 Keil 打开 firmware/rcc2/MDK-ARM/rcc2.uvprojx，编译烧录
```
（这一步需要 Windows + Keil + CubeMX，是纯嵌入式活，卡住先看 `firmware/rcc2/docs/protocolv1.0.md`）

### 安装 udev 规则（固定串口名）
```bash
sudo cp deploy/*.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
# 插上 PL2303 后应该出现 /dev/robot_mcu
ls -l /dev/robot_mcu
```

### 运行 HIL 闭环
HIL 要同时起三样东西：Gazebo（假世界）、`hil_bridge_sim`（PC 端虚拟电机/编码器）、`hil_bridge`（串口桥）。
```bash
# 终端1
ros2 launch patrol_description gazebo_sim.launch.py
# 终端2
python3 pc/hil_bridge_sim.py
# 终端3（若在 PC 直插 STM32）
python3 rk3588/hil_bridge.py
```
> 注意：本仓的 `hil_bridge.py` 默认串口是 `/dev/ttyUSB0`，且跑在 RK3588 端设计的。
> 在 PC 上做 L1 时把它拷过来、把 `SERIAL_PORT` 改成 `/dev/robot_mcu` 即可。

### ✅ 怎么算跑通了
- 在另一个终端 `ros2 topic pub /cmd_vel_input geometry_msgs/Twist "{linear: {x: 0.3}}" -r 10`
- **Gazebo 里的小车开始走**——但驱动它的不是仿真，而是 STM32 真实算出来的 PWM，经串口回来控制虚拟电机
- `ros2 topic echo /hil_wheel_cmd` 能看到实时的 PWM 值

### 这层最常见的坑
| 现象 | 原因 | 解法 |
|---|---|---|
| STM32 一插串口就复位/死机 | PL2303 的 DTR/RTS 拉死了复位脚 | `hil_bridge.py` 里已 `setDTR(False); setRTS(False)` |
| 车刹车后死锁不动 | 刹车时忘了继续发编码器反馈 | `hil_bridge_sim.py` 注释"绝对核心！刹车也必须发反馈" |
| 串口收发乱码/对不上 | CRC 大小端错 | 协议是 payload 小端 + CRC16 大端传输，见 `protocolv1.0.md` |

---

## L2：决策下板 RK3588（+RK3588，~800 元）

**目标**：把视觉、语音、串口桥这些"车端"节点从 PC 挪到 RK3588 上跑，PC 只留 Gazebo 仿真和总控台。这层开始需要两台机器联网。

### 硬件
- RK3588 开发板（正点原子 ATK-DLRK3588，已刷好 Ubuntu 22.04 + RKNN 驱动）
- PC 和 RK3588 接到**同一局域网**，互相能 ping 通

### 配置跨机通信（CycloneDDS 单播）
项目用单播而不是组播（跨子网组播会丢）。
```bash
# PC 端：把 cyclonedds_pc.xml 里的 <RK3588_IP> 改成 RK 的真实 IP
# RK 端：把 cyclonedds_rk.xml 里的 <PC_IP> 改成 PC 的真实 IP

# 两台机器都设置：
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///绝对路径/cyclonedds_xx.xml
```
（建议写进各自的 `~/.bashrc`）

### 在 RK3588 上装环境
```bash
# RK 端同样要装 ROS2 Humble + cyclonedds
# 然后编译 robot_serial 和 robot_interfaces：
mkdir -p ~/robot_ws/src && cd ~/robot_ws/src
cp -r <本仓库>/rk3588/robot_serial .
cp -r <本仓库>/rk3588/robot_interfaces .
cd ~/robot_ws && source /opt/ros/humble/setup.bash
colcon build && source install/setup.bash
```

### ✅ 怎么算跑通了
- PC 上 `ros2 topic list` 能看到 RK 端发出来的话题
- 在 RK 上 `ros2 run robot_serial serial_bridge_node`，PC 上能 `ros2 topic echo /odom` 收到数据
- **关键判据**：PC 发 `/cmd_vel_input`，STM32 的电机（或 HIL 虚拟电机）有反应，说明 PC→DDS→RK→串口→STM32 整条链通了

### 这层最常见的坑
| 现象 | 原因 | 解法 |
|---|---|---|
| 两台机器互相看不到话题 | DDS 组播被路由器隔离 | 必须改单播 Peers，且 IP 填对 |
| 话题能 list 但 echo 没数据 | RMW 没统一 | 两台都 `export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` |

---

## L3：视觉安防（+RTSP 相机，~200 元）

**目标**：接上网络相机，RK3588 用 NPU 实时检测入侵者，触发锁死/截图/报警。

### 硬件
- 海康/大华 RTSP 网络相机（项目因 MIPI 在非官方 SDK 走不通而改用网络相机，反而更灵活）

### 安装模型
YOLO 模型要单独下载，**见 [`rk3588/README_MODELS.md`](../rk3588/README_MODELS.md)**（约 4MB 的 `yolo11.rknn`，FP16 多头版）。

### 配置相机
```bash
# 相机 IP 和凭据通过环境变量传入，不要写死在代码里
export RTSP_URL="rtsp://admin:<你的密码>@<相机IP>:554/Streaming/Channels/102?tcp"
```

### 运行
```bash
# 在 RK3588 上
python3 rk3588/yolo11_rtsp_node.py
```

### ✅ 怎么算跑通了
- 节点打印检测帧率（约 23Hz）
- 有人走进画面，`/detections` 话题有输出，安防模式下触发报警、存截图到 `pending_records/`

---

## L4：全离线语音栈（+ReSpeaker，~200 元）

**目标**：喊一声唤醒词，机器人听懂并回答，全程不联网。

### 硬件
- ReSpeaker USB 麦克风阵列（或兼容 USB 声卡）

### 安装模型
语音三件套 + 大模型共约 2.5GB，**全部见 [`rk3588/README_MODELS.md`](../rk3588/README_MODELS.md)**：
- KWS 唤醒（zipformer-3.3M）
- SenseVoice ASR（229MB）
- MeloTTS（291MB）
- Qwen2.5-1.5B RKLLM（2GB）

### 运行
```bash
# 终端1：LLM 本地服务（先确保 librkllmrt.so 就位）
python3 rk3588/voice/flask_server.py
# 终端2：语音主程序
python3 rk3588/voice/assistant.py
```

### ✅ 怎么算跑通了
- 说唤醒词，终端打印命中
- 接着下指令"前进"，ASR 识别 → LLM 理解 → TTS 播报回应 → 小车动

---

## 附录：各层依赖速查

| 层 | 必读文件 | 关键环境变量 |
|---|---|---|
| L0 | `pc/patrol_description/` | 无 |
| L1 | `firmware/rcc2/docs/protocolv1.0.md` | 无 |
| L2 | 两个 `cyclonedds_*.xml` | `RMW_IMPLEMENTATION`、`CYCLONEDDS_URI` |
| L3 | `rk3588/README_MODELS.md` | `RTSP_URL` |
| L4 | `rk3588/README_MODELS.md` | `RTSP_URL`、模型路径 |

**卡住了先翻项目总结**（如果你也有那份 8 万字文档），里面第 15 章有一张"计划 vs 实测差异总表"，记录了这个项目踩过的 50 多个坑，大概率你的问题在里面有答案。

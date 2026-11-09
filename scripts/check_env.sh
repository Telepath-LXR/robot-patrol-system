#!/usr/bin/env bash
# 具身智能巡检机器人 · 环境自检脚本
# 用法:  bash scripts/check_env.sh
# 在 PC 上跑查 PC 的东西，在 RK3588 上跑查 RK 的东西，自动判断。
# 只检查、不修改，全绿不代表能跑，全红一定跑不了。

OK="\033[32m[✓]\033[0m"
NO="\033[31m[✗]\033[0m"
WARN="\033[33m[!]\033[0m"

pass(){ echo -e "$OK $1"; }
fail(){ echo -e "$NO $1"; }
warn(){ echo -e "$WARN $1"; }

have(){ command -v "$1" >/dev/null 2>&1; }

echo "==================== 系统基础 ===================="
. /etc/os-release 2>/dev/null
if [ "$VERSION_ID" = "22.04" ]; then pass "Ubuntu 22.04 ($PRETTY_NAME)"; else warn "推荐 Ubuntu 22.04，当前: $PRETTY_NAME"; fi

# 判断是 x86 PC 还是 aarch64 RK3588
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    ROLE="PC"
elif [ "$ARCH" = "aarch64" ]; then
    ROLE="RK3588"
else
    ROLE="未知($ARCH)"
fi
echo "检测到角色: $ROLE ($ARCH)"

echo ""
echo "==================== ROS2 ===================="
if have ros2; then
    if [ "$ROS_DISTRO" = "humble" ] || grep -q humble <<<"$(ros2 --version 2>/dev/null)"; then
        pass "ROS2 Humble"
    else
        warn "ROS2 已装但没 source？试试: source /opt/ros/humble/setup.bash"
    fi
else
    fail "没装 ros2，去 https://docs.ros.org/en/humble/Installation.html"
fi

if [ "$RMW_IMPLEMENTATION" = "rmw_cyclonedds_cpp" ]; then
    pass "RMW = CycloneDDS"
else
    warn "RMW 未设为 cyclonedds，跨机会看不到话题。export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp"
fi

echo ""
echo "==================== 工作区与包 ===================="
for ws in "$HOME/ros2_ws" "$HOME/robot_ws"; do
    if [ -d "$ws/install" ]; then pass "找到工作区 $ws"; fi
done
if have ros2; then
    for pkg in patrol_description robot_interfaces robot_serial; do
        if ros2 pkg prefix "$pkg" >/dev/null 2>&1; then pass "ROS2 包 $pkg 已编译"; fi
    done
fi

echo ""
echo "==================== Python 依赖 ===================="
python3 - <<'PY' 2>/dev/null || echo -e "\033[31m[✗]\033[0m python3 异常"
import importlib, shutil
mods = {
    "PC": ["PyQt5","serial","numpy"],
    "RK3588": ["serial","numpy","cv2","flask","sounddevice","scipy","sherpa_onnx"],
}
import platform
arch = platform.machine()
role = "PC" if arch=="x86_64" else ("RK3588" if arch=="aarch64" else "PC")
for m in mods.get(role, []):
    name = {"serial":"pyserial","cv2":"opencv-python"}.get(m,m)
    try:
        importlib.import_module(m)
        print(f"\033[32m[✓]\033[0m python 包 {name}")
    except Exception:
        print(f"\033[31m[✗]\033[0m 缺 python 包 {name}  →  pip3 install {name}")
PY

echo ""
echo "==================== 串口 / udev ===================="
if [ -e /dev/robot_mcu ]; then
    pass "/dev/robot_mcu 存在（udev 规则生效）"
elif [ -e /dev/ttyUSB0 ]; then
    warn "只有 /dev/ttyUSB0，没固定成 robot_mcu。装规则: sudo cp deploy/*.rules /etc/udev/rules.d/ && sudo udevadm trigger"
else
    fail "没找到串口设备（L1/L2 需要插 PL2303）"
fi

echo ""
echo "==================== 模型文件（仅 RK3588 需要）===================="
if [ "$ROLE" = "RK3588" ]; then
    [ -f "$HOME/yolo11.rknn" ] && pass "YOLO: ~/yolo11.rknn" || warn "缺 ~/yolo11.rknn（见 rk3588/README_MODELS.md）"
    [ -f "$HOME/voice/sense-voice-onnx/model.int8.onnx" ] && pass "ASR: sense-voice-onnx" || warn "缺 sense-voice-onnx 模型"
    [ -f "$HOME/voice/vits-melo-tts-zh_en/model.onnx" ] && pass "TTS: vits-melo-tts-zh_en" || warn "缺 vits-melo-tts-zh_en 模型"
    ls "$HOME/voice/model/"*encoder*onnx >/dev/null 2>&1 && pass "KWS: ~/voice/model/" || warn "缺 KWS zipformer 模型"
    ls "$HOME/voice/qwen/RK3588/"*.rkllm >/dev/null 2>&1 && pass "LLM: Qwen .rkllm" || warn "缺 Qwen .rkllm"
    [ -f "$HOME/voice/rknn-llm/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so" ] && pass "RKLLM 运行时 librkllmrt.so" || warn "缺 librkllmrt.so"
else
    echo "（PC 端跳过模型检查）"
fi

echo ""
echo "==================== 环境变量 ===================="
[ -n "$RTSP_URL" ] && pass "RTSP_URL 已设置" || warn "RTSP_URL 未设置（L3 视觉安防需要）"
[ -n "$CYCLONEDDS_URI" ] && pass "CYCLONEDDS_URI 已设置" || warn "CYCLONEDDS_URI 未设置（L2 跨机需要）"

echo ""
echo "==================== 小结 ===================="
echo "上面 ✗ 是必须解决的，! 是看情况。"
echo "各层怎么跑、怎么算通，看 docs/DEPLOY.md。"

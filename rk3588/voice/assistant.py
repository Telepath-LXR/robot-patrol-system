import sounddevice as sd
import numpy as np
import sherpa_onnx
from scipy.signal import resample_poly
import queue, threading, time, re, resource, subprocess
import os, glob, socket
from datetime import datetime
import math
import requests

from geometry_msgs.msg import Twist, PoseStamped
from std_msgs.msg import Bool, String

resource.setrlimit(resource.RLIMIT_NOFILE, (102400, 102400))

cur_v = 0.0
cur_w = 0.0
v_lock = threading.Lock()
estop_pub = None
last_estop_sent = None   # None=从未发过, True=锁存, False=解除
ros_node = None          # 供查询 ROS 节点数用
voice_enabled = False    # 首次动作词命中前不发 /cmd_vel_voice，避免启动时覆盖手动速度

# ================= 安防新增全局变量 =================
auth_required = False    # 安防验证标志
alarm_looping = threading.Event() # 报警循环标志
system_mode = "cruise"   # 默认巡航模式

TURN_DURATION = 3.0
turn_timer = None
turn_lock = threading.Lock()

# ================= 目标点定义 =================
WAYPOINTS = {
    "1号": (-0.767, -2.33, 0.00194),
    "2号": (-0.672, 2.79, -0.00013),
    "3号": (-4.09, 2.78, 0.0029),
    "沙发": (-1.86, -0.198, 0.00377),
    "大门": (0.142, 4.37, 0.00235),
}

HAS_ROS2 = False
try:
    import rclpy
    from rclpy.node import Node

    class VoiceRosNode(Node):
        def __init__(self):
            super().__init__('voice_cmd_node')
            # 发 /cmd_vel_voice，PC 端作为唯一仲裁者
            self.pub = self.create_publisher(Twist, '/cmd_vel_voice', 10)
            self.estop_pub = self.create_publisher(Bool, '/voice_estop', 10)
            self.goal_pub = self.create_publisher(PoseStamped, '/goal_pose', 10)
            
            # 安防相关发布与订阅
            self.auth_status_pub = self.create_publisher(String, '/auth_status', 10)
            self.create_subscription(String, '/safety_alarm', self.alarm_cb, 10)
            self.create_subscription(String, '/system_mode', self.mode_cb, 10)
            
            self.timer = self.create_timer(0.1, self.publish_loop)
            self.get_logger().info("Voice ROS2 started, 10Hz → /cmd_vel_voice (首次动作词前静默)")

        def publish_loop(self):
            global cur_v, cur_w, voice_enabled
            # 首次动作词命中前不发，避免启动时用 0 覆盖 dashboard 里的手动速度
            if not voice_enabled:
                return
            twist = Twist()
            with v_lock:
                twist.linear.x = float(cur_v)
                twist.angular.z = float(cur_w)
            self.pub.publish(twist)
            
        def mode_cb(self, msg):
            global system_mode
            system_mode = msg.data
            print(f"[安防] 系统模式切换为: {system_mode}")

        def alarm_cb(self, msg):
            global auth_required, alarm_looping
            if msg.data == "INTRUDER_DETECTED" and not auth_required:
                auth_required = True
                print("[安防] 收到报警，触发强制验证！")
                llm_task_q.put("__TRIGGER_AUTH__")
            elif msg.data == "STOP_ALARM":
                alarm_looping.clear() # 停止报警循环
                auth_required = False
                # 清空所有 TTS 和 播放队列
                tts_playing = False
                subprocess.run(["pkill", "-9", "aplay"], capture_output=True)
                
                # 清空所有的队列
                while not tts_q.empty():
                    try: tts_q.get_nowait()
                    except: pass
                while not audio_play_q.empty():
                    try: audio_play_q.get_nowait()
                    except: pass
                
                # 塞入一个 None 唤醒可能被阻塞的播放线程
                audio_play_q.put(None) 
                
                print("[安防] 收到人工确认，报警已停止！")

    def ros_spin_thread():
        global estop_pub, ros_node
        rclpy.init()
        node = VoiceRosNode()
        estop_pub = node.estop_pub
        ros_node = node
        try:
            rclpy.spin(node)
        except Exception:
            pass
        finally:
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()

    threading.Thread(target=ros_spin_thread, daemon=True).start()
    HAS_ROS2 = True
    print("[ROS2] 10Hz 速度发布线程已启动 → /cmd_vel_voice")
except Exception as e:
    print(f"[ROS2] 不可用，动作仅打印: {e}")

def send_nav_goal(x, y, theta):
    """发布 Nav2 目标点"""
    if ros_node is None: return
    goal = PoseStamped()
    goal.header.frame_id = 'map'
    goal.header.stamp = ros_node.get_clock().now().to_msg()
    goal.pose.position.x = float(x)
    goal.pose.position.y = float(y)
    goal.pose.orientation.z = math.sin(theta * 0.5)
    goal.pose.orientation.w = math.cos(theta * 0.5)
    ros_node.goal_pub.publish(goal)
    print(f"[导航] 发布目标点: x={x}, y={y}")

def setup_amixer():
    cmds = [
        ["amixer", "-c", "1", "cset", "numid=16", "0"],
        ["amixer", "-c", "1", "cset", "numid=25", "192,192"],
        ["amixer", "-c", "1", "cset", "numid=27", "8"],
        ["amixer", "-c", "1", "cset", "numid=28", "8"],
        ["amixer", "-c", "1", "cset", "numid=43", "on"],
        ["amixer", "-c", "1", "cset", "numid=26", "0"],
        ["amixer", "-c", "1", "cset", "numid=47", "1"],
        ["amixer", "-c", "1", "cset", "numid=45", "2"],
        ["amixer", "-c", "1", "cset", "numid=46", "2"],
        ["amixer", "-c", "1", "cset", "numid=36", "1"],
    ]
    for c in cmds:
        subprocess.run(c, capture_output=True)
    print("[amixer] 增益已自动设置")

setup_amixer()

WAKE_WORDS = {"苹果", "助手", "聊天", "小安", "小欸", "小阿"}
ACTION_WORDS = {"前进", "后退", "左转", "右转", "停下", "加速", "减速"}
VOICE_V_MAX = 3.00
VOICE_V_STEP = 0.50

def _turn_timeout():
    global cur_w, turn_timer
    with v_lock:
        cur_w = 0.0
    with turn_lock:
        turn_timer = None
    print("[动作] ⏹ 转向 5s 结束，角速度归零")

def _cancel_turn_timer():
    global turn_timer
    with turn_lock:
        if turn_timer is not None:
            turn_timer.cancel()
            turn_timer = None

def _start_turn_timer():
    global turn_timer
    with turn_lock:
        if turn_timer is not None:
            turn_timer.cancel()
        turn_timer = threading.Timer(TURN_DURATION, _turn_timeout)
        turn_timer.daemon = True
        turn_timer.start()

def handle_action(word):
    global cur_v, cur_w, last_estop_sent, voice_enabled
    # 首次动作词命中，才允许发 /cmd_vel_voice
    voice_enabled = True
    if estop_pub is not None:
        is_stop = (word == "停下")
        estop_pub.publish(Bool(data=is_stop))
        last_estop_sent = is_stop
    log_msg = ""
    need_start = False
    need_cancel = False
    with v_lock:
        if word == "停下":
            cur_v, cur_w = 0.0, 0.0
            need_cancel = True
            log_msg = "🛑 急停"
        elif word == "加速":
            cur_v = min(cur_v + VOICE_V_STEP, VOICE_V_MAX)
            cur_w = 0.0
            need_cancel = True
            log_msg = f"⏫ 加速 → v={cur_v:.2f}"
        elif word == "减速":
            cur_v = max(cur_v - VOICE_V_STEP, -VOICE_V_MAX)
            cur_w = 0.0
            need_cancel = True
            log_msg = f"⏬ 减速 → v={cur_v:.2f}"
        elif word == "左转":
            cur_w = +2.5
            # cur_v 不变，线速度保持
            need_start = True
            log_msg = f"⬅ 左转 5s（v={cur_v:.2f} 保持）"
        elif word == "右转":
            cur_w = -2.5
            need_start = True
            log_msg = f"➡ 右转 5s（v={cur_v:.2f} 保持）"
        elif word == "前进":
            cur_v = +0.30
            cur_w = 0.0
            need_cancel = True
            log_msg = f"前进 → v={cur_v:.2f}"
        elif word == "后退":
            cur_v = -0.30
            cur_w = 0.0
            need_cancel = True
            log_msg = f"后退 → v={cur_v:.2f}"
    if need_start:
        _start_turn_timer()
    elif need_cancel:
        _cancel_turn_timer()
    print(f"[动作] {log_msg}")

# ================= 系统健康查询工具 =================
def _read_thermal(zone_keywords):
    temps = []
    for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            ztype = open(f"{zone}/type").read().strip().lower()
            if any(k in ztype for k in zone_keywords):
                temps.append(int(open(f"{zone}/temp").read().strip()) / 1000.0)
        except Exception:
            continue
    return max(temps) if temps else None

def get_cpu_temp(): return _read_thermal(["soc", "cpu", "bigcore", "littlecore", "cluster", "center"])
def get_npu_temp(): return _read_thermal(["npu"])
def get_gpu_temp(): return _read_thermal(["gpu"])

def get_cpu_usage():
    def _snap():
        with open("/proc/stat") as f:
            p = list(map(int, f.readline().split()[1:]))
        idle = p[3] + (p[4] if len(p) > 4 else 0)
        return idle, sum(p)
    i1, t1 = _snap()
    time.sleep(0.3)
    i2, t2 = _snap()
    dt = t2 - t1
    return 100.0 * (1 - (i2 - i1) / dt) if dt > 0 else 0.0

def get_mem_usage():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k] = int(v.strip().split()[0])
    total = info["MemTotal"]
    used = total - info.get("MemAvailable", info["MemFree"])
    return 100.0 * used / total

def get_disk_free_gb(path="/"):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / (1024 ** 3)

def get_uptime_hours():
    with open("/proc/uptime") as f:
        return float(f.read().split()[0]) / 3600.0

def get_loadavg():
    with open("/proc/loadavg") as f:
        p = f.read().split()
    return float(p[0]), float(p[1]), float(p[2])

def get_datetime_str():
    now = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return f"{now.year}年{now.month}月{now.day}日 {weekdays[now.weekday()]} {now.hour}点{now.minute:02d}分"

def get_cpu_freq_ghz():
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq") as f:
            return int(f.read().strip()) / 1e6
    except Exception:
        return None

def get_cpu_governor():
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor") as f:
            return f.read().strip()
    except Exception:
        return None

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def get_process_count():
    try:
        return sum(1 for p in os.listdir("/proc") if p.isdigit())
    except Exception:
        return None

def get_npu_load():
    try:
        with open("/sys/kernel/debug/rknpu/load") as f:
            nums = re.findall(r'(\d+)%', f.read())
        if nums:
            vals = [int(x) for x in nums]
            while len(vals) < 3: vals.append(0)
            return tuple(vals[:3])
    except Exception:
        pass
    return None

def get_stm32_status():
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    if not ports:
        return "offline", None
    port = ports[0]
    try:
        r = subprocess.run(["fuser", port], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            pid_txt = (r.stdout + r.stderr).strip()
            if re.search(r'\d+', pid_txt):
                return "bridge_running", port
            return "occupied_unknown", port
        return "device_only", port
    except Exception:
        return "unknown", port

def check_llm_service():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(("127.0.0.1", 8080))
        s.close()
        return True
    except Exception:
        return False

def check_mic():
    try:
        dev = sd.query_devices(device=0)
        return f"麦克风设备存在，名称{dev['name']}"
    except Exception:
        return None

def get_ros_node_count():
    if ros_node is None:
        return None
    try:
        return len(ros_node.get_node_names())
    except Exception:
        return None

def get_motion_state():
    with v_lock:
        v, w = cur_v, cur_w
    with turn_lock:
        turning = turn_timer is not None
    return v, w, turning

def _temp_level(t):
    if t is None: return "读不到"
    if t < 60: return "正常"
    if t < 75: return "偏高"
    return "过热"

QUERY_KEYWORDS = {
    "temp":       ["温度", "多热", "热不热", "烫", "发烧", "过热"],
    "cpu":        ["cpu", "处理器", "占用率", "使用率"],
    "mem":        ["内存", "memory", "ram"],
    "disk":       ["磁盘", "硬盘", "存储", "空间", "还剩", "剩余"],
    "uptime":     ["运行多久", "运行了多久", "开机多久", "跑了多久", "连续跑"],
    "load":       ["负载", "load"],
    "datetime":   ["今天", "日期", "几号", "星期几", "现在几点", "当前时间", "时间", "几点"],
    "freq":       ["频率", "主频", "ghz", "mhz", "调频", "性能模式"],
    "network":    ["ip", "地址", "网络", "联网"],
    "process":    ["进程", "process"],
    "npu":        ["npu", "神经网络", "加速器"],
    "stm32":      ["单片机", "stm32", "下位机", "串口", "底层板"],
    "service":    ["大脑", "服务", "llm", "在线", "离线"],
    "mic":        ["麦克风", "话筒", "收音", "录音"],
    "motion":     ["速度", "多快", "车速", "跑多快", "运动状态", "在干什么", "在做什么"],
    "turning":    ["转向", "在转", "转弯", "转向状态"],
    "estop":      ["急停", "锁存", "停车状态", "安全状态"],
    "ros":        ["ros", "节点", "话题"],
    "capability": ["你能做什么", "能干什么", "会什么", "有什么功能", "你有什么能力", "你能干嘛", "介绍一下自己", "自我介绍", "你能帮我做什么"],
}
QUERY_ALL = ["状态", "健康", "运行情况", "怎么样", "还好吗", "检查一下", "体检"]

def detect_query_intent(text):
    t = text.lower()
    hits = set()
    for metric, kws in QUERY_KEYWORDS.items():
        if any(w in t for w in kws):
            hits.add(metric)
    if any(w in t for w in QUERY_ALL):
        hits.add("all")
    return hits

def build_status_context(hits):
    if hits == {"all"}:
        hits = {"temp", "cpu", "mem", "npu", "stm32"}

    parts = []
    if hits & {"temp", "all"}:
        ct, nt, gt = get_cpu_temp(), get_npu_temp(), get_gpu_temp()
        if ct is not None: parts.append(f"CPU温度{ct:.1f}摄氏度{_temp_level(ct)}")
        if nt is not None: parts.append(f"NPU温度{nt:.1f}摄氏度{_temp_level(nt)}")
        if gt is not None: parts.append(f"GPU温度{gt:.1f}摄氏度{_temp_level(gt)}")
    if hits & {"cpu", "all"}:
        parts.append(f"CPU占用率{get_cpu_usage():.0f}%")
    if hits & {"mem", "all"}:
        parts.append(f"内存占用率{get_mem_usage():.0f}%")
    if hits & {"disk", "all"}:
        parts.append(f"磁盘剩余{get_disk_free_gb():.1f}GB")
    if hits & {"uptime", "all"}:
        parts.append(f"运行时长{get_uptime_hours():.1f}小时")
    if hits & {"load", "all"}:
        l1, l5, l15 = get_loadavg()
        parts.append(f"负载1分钟{l1:.2f}、5分钟{l5:.2f}、15分钟{l15:.2f}")
    if hits & {"datetime"}:
        parts.append(f"当前是{get_datetime_str()}")
    if hits & {"freq", "all"}:
        f = get_cpu_freq_ghz()
        if f is not None: parts.append(f"CPU当前频率{f:.2f}GHz")
        g = get_cpu_governor()
        if g is not None: parts.append(f"调频策略{g}")
    if hits & {"network", "all"}:
        ip = get_local_ip()
        if ip: parts.append(f"本机IP{ip}")
    if hits & {"process", "all"}:
        pc = get_process_count()
        if pc: parts.append(f"当前{pc}个进程")
    if hits & {"npu", "all"}:
        load = get_npu_load()
        if load: parts.append(f"NPU三核负载{load[0]}%、{load[1]}%、{load[2]}%")
        else: parts.append("NPU负载读数不可用")
    if hits & {"stm32", "all"}:
        st, port = get_stm32_status()
        if st == "bridge_running": parts.append(f"STM32串口{port}在线桥接运行中")
        elif st == "occupied_unknown": parts.append(f"STM32串口{port}被占用桥接可能以root运行")
        elif st == "device_only": parts.append(f"STM32串口{port}已连接但桥接未运行")
        elif st == "offline": parts.append("未检测到STM32串口设备")
        else: parts.append("STM32状态未知")
    if hits & {"service"}:
        parts.append("LLM服务在线" if check_llm_service() else "LLM服务无响应")
    if hits & {"mic"}:
        mic = check_mic()
        if mic: parts.append(mic)
        else: parts.append("麦克风不可用")
    if hits & {"motion", "turning"}:
        v, w, turning = get_motion_state()
        if hits & {"motion"}: parts.append(f"当前线速度{v:.2f}米每秒角速度{w:.2f}")
        if hits & {"turning"} or hits & {"motion"}: parts.append("正在转向" if turning else "没有转向")
    if hits & {"estop"}:
        if last_estop_sent is True: parts.append("急停已锁存")
        elif last_estop_sent is False: parts.append("急停未锁存")
        else: parts.append("尚未发送过急停指令")
    if hits & {"ros"}:
        n = get_ros_node_count()
        if n is not None: parts.append(f"ROS当前{n}个节点")
        else: parts.append("ROS节点查询不可用")
    return "；".join(parts)

# ================= 模型初始化 =================
kws = sherpa_onnx.KeywordSpotter(
    tokens="~/voice/model/tokens.txt",
    encoder="~/voice/model/encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    decoder="~/voice/model/decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    joiner="~/voice/model/joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    keywords_file="~/voice/my_keywords.txt",
    num_threads=2,
)

asr = sherpa_onnx.OfflineRecognizer.from_sense_voice(
    model="~/voice/sense-voice-onnx/model.int8.onnx",
    tokens="~/voice/sense-voice-onnx/tokens.txt",
    num_threads=2, use_itn=True, language="zh",
)

tts_dir = "~/voice/vits-melo-tts-zh_en"
tts_cfg = sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=f"{tts_dir}/model.onnx",
            lexicon=f"{tts_dir}/lexicon.txt",
            tokens=f"{tts_dir}/tokens.txt",
        ),
        num_threads=6,
    ),
    rule_fsts=f"{tts_dir}/date.fst,{tts_dir}/phone.fst,{tts_dir}/number.fst",
    max_num_sentences=1,
)
tts = sherpa_onnx.OfflineTts(tts_cfg)

STATE_IDLE, STATE_REC = 0, 1
state = STATE_IDLE
rec_buf = []
audio_q = queue.Queue(maxsize=20)
llm_task_q = queue.Queue()
tts_q = queue.Queue()
audio_play_q = queue.Queue()

tts_playing = False
rec_done = threading.Event()
silence_frames = 0
has_speech = False

system_prompt = (
    "你叫小A，是巡检机器人助手。回答会直接转为语音播报。\n"
    "规则：1. 直接说答案，不要开场白。2. 禁止列表、编号、书名号、括号。"
    "3. 总字数不超过40字。4. 消息中出现【系统实测数据】时，"
    "只能依据其中的数值回答，禁止编造或估算任何未给出的数据。"
)
chat_history = [{"role": "system", "content": system_prompt}]

CAPABILITY_TEXT = (
    "我能查温度、CPU、内存、磁盘、日期、网络、进程、速度、转向、急停、"
    "STM32连接、服务在线和ROS节点，也能控制前进后退转向，还能导航去1号点、2号点、3号点、沙发或大门。"
    "我没有环境温度传感器，不能控制底盘以外的设备。"
)

SILENCE_THRESHOLD = 0.01
SILENCE_FRAMES_MAX = 76

def postprocess_llm_reply(text: str) -> str:
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    text = re.sub(r'^\s*\d+[\.、\)]\s*', '', text, flags=re.M)
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.M)
    text = re.sub(r'（[^）]*）', '', text)
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'[《》【】\[\]{}]', '', text)
    text = text.replace(':', '，').replace('：', '，')
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[，。！？]{2,}', '。', text)
    if len(text) > 60:
        idx = text.rfind('。', 0, 60)
        if idx > 0: text = text[:idx+1]
    return text

def clean_text_for_tts(text: str) -> str:
    text = re.sub(r'（[^）]*）', '', text)
    text = text.replace('：', '，').replace('；', '，').replace(':', '，')
    text = re.sub(r'[《》【】\[\]{}]', '', text)
    text = text.replace('"', '').replace("'", "").replace('“', '').replace('”', '').replace('‘', '').replace('’', '')
    text = text.replace('/', '每').replace('／', '每')
    return re.sub(r'[，。！？]{2,}', '。', text).strip()

def decide_speed(text: str) -> float:
    n = len(text)
    return 1.1 if n < 10 else (0.9 if n > 25 else 1.0)

def audio_cb(indata, frames, t, status):
    global state, rec_buf, tts_playing, silence_frames, has_speech
    if tts_playing:
        return
    mono = np.mean(indata, axis=1)
    a16 = resample_poly(mono, up=1, down=3).astype(np.float32)
    peak = float(np.max(np.abs(a16)))
    if state == STATE_IDLE:
        try: audio_q.put(a16.copy(), block=False)
        except queue.Full: pass
    elif state == STATE_REC:
        rec_buf.append(a16.copy())
        if peak > SILENCE_THRESHOLD:
            silence_frames = 0
            has_speech = True
        else:
            silence_frames += 1
            if has_speech and silence_frames >= SILENCE_FRAMES_MAX:
                rec_done.set()

def kws_worker():
    global state, rec_buf, kws, silence_frames, has_speech
    kws_stream = kws.create_stream()
    while True:
        a16 = audio_q.get()
        if a16 is None: break
        kws_stream.accept_waveform(16000, a16)
        while kws.is_ready(kws_stream):
            kws.decode_stream(kws_stream)
            r = kws.get_result(kws_stream)
            if r:
                word = r.strip()
                print(f"\n[KWS命中] {word}")
                
                if system_mode == "security":
                    print("[安防模式] 忽略常规唤醒/指令")
                    kws_stream = kws.create_stream()
                    continue

                if word in ACTION_WORDS:
                    handle_action(word)
                    kws_stream = kws.create_stream()
                elif word in WAKE_WORDS:
                    print(f"[唤醒] {word} → 进入对话模式（不影响速度）")
                    state = STATE_REC
                    rec_buf = []
                    silence_frames = 0
                    has_speech = False
                    rec_done.clear()
                    kws_stream = kws.create_stream()
                break

def llm_worker():
    global chat_history, auth_required
    while True:
        user_text = llm_task_q.get()
        if user_text is None: break
        try:
            # === 1. 安防触发特殊逻辑 ===
            if user_text == "__TRIGGER_AUTH__":
                tts_q.put("发现未授权人员。")
                tts_q.put("请进行身份验证。")
                continue

            # === 2. 验证逻辑拦截 ===
            if auth_required:
                auth_required = False
                if "0929" in user_text or "零九二九" in user_text:
                    tts_q.put("身份验证通过，继续巡检。")
                    if ros_node: ros_node.auth_status_pub.publish(String(data="SUCCESS"))
                else:
                    tts_q.put("验证失败，已触发警报！")
                    if ros_node: ros_node.auth_status_pub.publish(String(data="FAILED"))
                    time.sleep(1.5) # 等上一句播完
                    alarm_looping.set() # 开启无限报警
                continue

            # === 3. 导航意图拦截 ===
            nav_reply = None
            for name, (x, y, theta) in WAYPOINTS.items():
                if name in user_text:
                    with v_lock:
                        global cur_v, cur_w
                        cur_v, cur_w = 0.0, 0.0
                    send_nav_goal(x, y, theta)
                    nav_reply = f"收到，正在前往{name}。"
                    break
            if nav_reply:
                print(f"[小A] {nav_reply}")
                tts_q.put(nav_reply)
                chat_history.append({"role": "user", "content": user_text})
                chat_history.append({"role": "assistant", "content": nav_reply})
                if len(chat_history) > 8: chat_history = [chat_history[0]] + chat_history[-6:]
                continue

            # === 4. 原有能力查询拦截 ===
            hits = detect_query_intent(user_text)
            if "capability" in hits:
                reply = CAPABILITY_TEXT
                print(f"[小A] {reply}")
                chat_history.append({"role": "user", "content": user_text})
                chat_history.append({"role": "assistant", "content": reply})
                if len(chat_history) > 8: chat_history = [chat_history[0]] + chat_history[-6:]
                tts_q.put(reply)
                continue

            # === 5. 原有系统状态注入逻辑 ===
            ctx = build_status_context(hits) if hits else ""
            chat_history.append({"role": "user", "content": user_text})

            if ctx:
                injected = (
                    f"【系统实测数据：{ctx}】\n"
                    f"用户问：{user_text}\n"
                    f"请严格依据以上实测数据回答，只复述数据，不得编造数值，不超过40字。"
                )
                msgs = list(chat_history[:-1]) + [{"role": "user", "content": injected}]
            else:
                msgs = list(chat_history)

            t0 = time.time()
            r = requests.post(
                "http://127.0.0.1:8080/v1/chat/completions",
                json={"model": "qwen", "messages": msgs, "max_tokens": 60, "temperature": 0.3},
                timeout=15,
            )
            r.raise_for_status()
            reply_raw = r.json()["choices"][0]["message"]["content"].strip()
            print(f"[LLM] 耗时 {time.time()-t0:.1f}s  intent={hits or '-'}")
            reply = postprocess_llm_reply(reply_raw)
            print(f"[小A] {reply}")
            chat_history.append({"role": "assistant", "content": reply})
            if len(chat_history) > 8: chat_history = [chat_history[0]] + chat_history[-6:]
            tts_q.put(reply)
        except Exception as e:
            print(f"[LLM 错误] {e}")
            tts_q.put("我的大脑卡住了。")

def tts_synth_worker():
    global tts_playing
    import tempfile, soundfile as sf
    while True:
        text = tts_q.get()
        if text is None:
            audio_play_q.put(None)
            break
        text = clean_text_for_tts(text)
        tts_playing = True
        try:
            sentences = [s.strip() for s in re.split(r'(?<=[。！？!?；;\n])', text) if s.strip()]
            for sent in sentences:
                speed = decide_speed(sent)
                audio = tts.generate(sent, sid=0, speed=speed)
                samples = np.array(audio.samples, dtype=np.float32)
                if audio.sample_rate != 24000:
                    from math import gcd
                    g = gcd(audio.sample_rate, 24000)
                    samples = resample_poly(samples, up=24000//g, down=audio.sample_rate//g).astype(np.float32)
                print(f"[TTS] 合成 (speed={speed}): {sent[:20]}")
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    tmp_path = f.name
                sf.write(tmp_path, samples, 24000)
                audio_play_q.put(tmp_path)
        except Exception as e:
            print(f"[TTS 合成错误] {e}")
        finally:
            audio_play_q.put(None)

def tts_play_worker():
    global tts_playing
    import os
    while True:
        item = audio_play_q.get()
        if item is None:
            if audio_play_q.empty():
                tts_playing = False
                while not audio_q.empty():
                    try: audio_q.get_nowait()
                    except queue.Empty: break
            continue
        try:
            subprocess.run(["aplay", "-q", "-D", "pulse", item], capture_output=True, timeout=20)
        except Exception as e:
            print(f"[TTS 播放错误] {e}")
        finally:
            try: os.remove(item)
            except: pass

def alarm_worker():
    """独立的报警循环线程，直到收到 STOP_ALARM"""
    while True:
        alarm_looping.wait()
        if alarm_looping.is_set():
            tts_q.put("警告，警告，有非法人员闯入。")
            alarm_looping.wait(timeout=4.5) # 等待这句播完
        else:
            time.sleep(0.5)

threading.Thread(target=kws_worker, daemon=True).start()
threading.Thread(target=llm_worker, daemon=True).start()
threading.Thread(target=tts_synth_worker, daemon=True).start()
threading.Thread(target=tts_play_worker, daemon=True).start()
threading.Thread(target=alarm_worker, daemon=True).start()

print("待机中...")
try:
    with sd.InputStream(device=0, channels=2, samplerate=48000, dtype='float32', callback=audio_cb):
        while True:
            # 【安防触发】强制开启录音
            if auth_required and state == STATE_IDLE and not tts_playing and not alarm_looping.is_set():
                print("[安防] 强制开启 5 秒录音...")
                state = STATE_REC
                rec_buf = []
                silence_frames = 0
                has_speech = True # 强制等待 timeout
                rec_done.clear()

            if state == STATE_REC:
                print("[录音] 开始...")
                # 安防状态下强制 5 秒录音，正常对话走 VAD 静音检测 (10秒兜底)
                rec_done.wait(timeout=5.0 if auth_required else 10.0)
                state = STATE_IDLE
                if not rec_buf: continue
                audio = np.concatenate(rec_buf)
                rec_buf = []
                st = asr.create_stream()
                st.accept_waveform(16000, audio)
                asr.decode_stream(st)
                text = st.result.text.strip()
                print(f"[你] {text}")
                if text: llm_task_q.put(text)
            time.sleep(0.05)
except KeyboardInterrupt:
    print("\n退出...")
    import os
    os._exit(0)

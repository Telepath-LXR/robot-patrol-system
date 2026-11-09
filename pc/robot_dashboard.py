#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, time, subprocess, os
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, PoseWithCovarianceStamped
from std_msgs.msg import Bool, String
from vision_msgs.msg import Detection2DArray
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QTextEdit, QLabel, QLineEdit, 
                             QGroupBox, QSplitter, QSizePolicy, QComboBox)
from PyQt5.QtCore import QThread, pyqtSignal, QProcess, Qt, QTimer

RK_IP = os.environ.get("RK_IP", "192.168.1.100")  # RK3588 的局域网 IP，按实际修改
RK_USER = os.environ.get("RK_USER", "alientek")    # RK3588 用户名

# 本地存放图片的文件夹（自动创建）
SAFE_LOCAL_DIR = os.path.expanduser("~/safe_records")
DANGER_LOCAL_DIR = os.path.expanduser("~/danger_records")
os.makedirs(SAFE_LOCAL_DIR, exist_ok=True)
os.makedirs(DANGER_LOCAL_DIR, exist_ok=True)

class RosWorker(QThread):
    log_signal = pyqtSignal(str)
    alarm_signal = pyqtSignal() # 触发UI红灯信号

    def __init__(self):
        super().__init__()
        self.running = True
        rclpy.init()
        self.node = rclpy.create_node('dashboard_node')
        
        self.pub_cmd = self.node.create_publisher(Twist, '/cmd_vel_input', 10)
        self.pub_initialpose = self.node.create_publisher(PoseWithCovarianceStamped, '/initialpose', 10)
        self.pub_mode = self.node.create_publisher(String, '/system_mode', 10)

        self.sub_voice = self.node.create_subscription(Twist, '/cmd_vel_voice', self.voice_callback, 10)
        self.sub_voice_estop = self.node.create_subscription(Bool, '/voice_estop', self.voice_estop_callback, 10)
        self.sub_det = self.node.create_subscription(Detection2DArray, '/detections', self.det_callback, 10)
        self.sub_nav = self.node.create_subscription(Twist, '/cmd_vel', self.nav_callback, 10)
        self.sub_alarm = self.node.create_subscription(String, '/safety_alarm', self.alarm_callback, 10)

        self.target_v = 0.0
        self.target_w = 0.0
        self.last_voice_v = 0.0
        self.last_voice_w = 0.0

        self.nav_v = 0.0
        self.nav_w = 0.0
        self.nav_active = False

        self.estop_latched = False
        self.person_count = 0
        self.last_person_time = 0.0
        
        self.security_alarm_active = False # 安防警报锁存
        self._log_key = None
        self.log_signal.emit("🚀 仲裁线程已启动（急停 > 安防 > 行人 > Nav2 > 语音）")

    def alarm_callback(self, msg):
        if msg.data == "INTRUDER_DETECTED":
            self.security_alarm_active = True
            self.alarm_signal.emit() # 触发UI红灯
            self.log_signal.emit("🚨 收到安检警报，正在后台同步异常图片...")
            # 后台静默拉取 RK3588 的图片到本地
            cmd_safe = f"scp -r {RK_USER}@{RK_IP}:~/voice/safe_records/* {SAFE_LOCAL_DIR}/ 2>/dev/null"
            cmd_danger = f"scp -r {RK_USER}@{RK_IP}:~/voice/danger_records/* {DANGER_LOCAL_DIR}/ 2>/dev/null"
            subprocess.Popen(cmd_safe, shell=True)
            subprocess.Popen(cmd_danger, shell=True)

    def det_callback(self, msg):
        count = 0
        for det in msg.detections:
            for hyp in det.results:
                if hyp.hypothesis.class_id == 'person' and hyp.hypothesis.score >= 0.5:
                    count += 1
                    break
        self.person_count = count
        if count > 0:
            self.last_person_time = time.time()

    def voice_estop_callback(self, msg):
        if msg.data:
            if not self.estop_latched:
                self.estop_latched = True
                self.nav_active = False
                self.nav_v = 0.0
                self.nav_w = 0.0
                self.log_signal.emit('🚨 语音急停触发，已清空 Nav2')
        else:
            if self.estop_latched:
                self.estop_latched = False
                self.log_signal.emit('✅ 语音急停解除')

    def voice_callback(self, msg):
        v = float(msg.linear.x)
        w = float(msg.angular.z)
        v_changed = abs(v - self.last_voice_v) > 0.001
        w_changed = abs(w - self.last_voice_w) > 0.001
        if not v_changed and not w_changed:
            return
        if v_changed:
            self.target_v = v
        if w_changed:
            self.target_w = w
        self.last_voice_v = v
        self.last_voice_w = w

    def nav_callback(self, msg):
        if self.estop_latched:
            self.nav_active = False
            return

        v = float(msg.linear.x)
        w = float(msg.angular.z)
        self.nav_active = abs(v) > 0.001 or abs(w) > 0.001
        
        if self.nav_active:
            self.nav_v = v
            self.nav_w = w
            if self.person_count == 0 and (time.time() - self.last_person_time >= 2.0):
                self.target_v = 0.0
                self.target_w = 0.0

    def run(self):
        self.node.create_timer(0.1, self.control_loop)
        while self.running and rclpy.ok():
            rclpy.spin_once(self.node, timeout_sec=0.01)

    def control_loop(self):
        # 0) 安防警报强行阻断（优先级最高之一，必须人工确认解除）
        if self.security_alarm_active:
            self.pub_cmd.publish(Twist())
            self._log_change("🛑 [安防警报] 等待人工点击收到异常", key="alarm")
            return

        # 1) 急停锁存
        if self.estop_latched:
            self.pub_cmd.publish(Twist())
            self._log_change("🛑 [急停锁存] 彻底阻断", key="estop")
            return
            
        # 2) 行人刹车 (带 2 秒迟滞)
        if self.person_count > 0 or (time.time() - self.last_person_time < 2.0):
            self.pub_cmd.publish(Twist())
            self._log_change("🛑 [行人刹车] 临时避让", key="person")
            return
            
        # 3) Nav2 导航接管
        if self.nav_active:
            twist = Twist()
            twist.linear.x = self.nav_v
            twist.angular.z = self.nav_w
            self.pub_cmd.publish(twist)
            self._log_change(f"🧭 [Nav2导航] v={self.nav_v:.2f} w={self.nav_w:.2f}", key=f"nav_{self.nav_v:.2f}_{self.nav_w:.2f}")
            return
            
        # 4) 正常输出 target（语音/手动）
        twist = Twist()
        twist.linear.x = self.target_v
        twist.angular.z = self.target_w
        self.pub_cmd.publish(twist)
        if abs(self.target_v) > 0.001 or abs(self.target_w) > 0.001:
            self._log_change(f"🚗 v={self.target_v:.2f} w={self.target_w:.2f}", key=f"drive_{self.target_v:.2f}_{self.target_w:.2f}")
        else:
            self._log_change("💤 空闲", key="idle")

    def set_mode(self, mode_str):
        self.pub_mode.publish(String(data=mode_str))
        self.log_signal.emit(f"🔄 下发系统模式: {mode_str}")

    def _log_change(self, msg, key):
        if key != self._log_key:
            self.log_signal.emit(msg)
            self._log_key = key

    def stop(self):
        self.running = False
        try: self.node.destroy_node()
        except: pass
        try: rclpy.shutdown()
        except: pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("具身智能巡检机器人控制台")
        self.resize(1100, 950)
        self.ros_worker = RosWorker()
        self.ros_worker.log_signal.connect(lambda msg: self.append_log(msg, target="sys"))
        self.ros_worker.alarm_signal.connect(self.show_alarm)
        self.ros_worker.start()
        self.init_ui()
        self.active_processes = []

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # ============ 系统总控 ============
        sys_group = QGroupBox("🖥️ 系统总控")
        sys_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sys_layout = QHBoxLayout()
        
        self.btn_start_all = QPushButton("🚀 一键启动系统 (Gazebo + HIL + 视觉 + 串口 + Nav2)")
        self.btn_start_all.setStyleSheet("background-color: #4caf50; color: white; font-weight: bold; height: 30px;")
        self.btn_start_all.clicked.connect(self.start_all)
        sys_layout.addWidget(self.btn_start_all, stretch=2)
        
        self.btn_stop_local = QPushButton("⏹ 停止所有本地进程")
        self.btn_stop_local.setStyleSheet("height: 30px;")
        self.btn_stop_local.clicked.connect(self.stop_local_processes)
        sys_layout.addWidget(self.btn_stop_local, stretch=1)
        
        self.btn_rk_vision_stop = QPushButton("⏹ 停止视觉节点")
        self.btn_rk_vision_stop.clicked.connect(self.stop_rk_vision)
        sys_layout.addWidget(self.btn_rk_vision_stop)

        self.btn_rk_hil_stop = QPushButton("⏹ 停止串口桥接")
        self.btn_rk_hil_stop.clicked.connect(self.stop_rk_hil)
        sys_layout.addWidget(self.btn_rk_hil_stop)

        sys_group.setLayout(sys_layout)
        layout.addWidget(sys_group)

        # ============ 安防监控 (带模式切换) ============
        alarm_group = QGroupBox("🚨 安防监控")
        alarm_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        alarm_layout = QHBoxLayout()
        
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["巡航模式", "安防模式"])
        self.combo_mode.setStyleSheet("font-weight: bold; padding: 2px;")
        self.combo_mode.currentIndexChanged.connect(self.change_mode)
        
        self.lbl_alarm = QLabel("系统正常")
        self.lbl_alarm.setStyleSheet("background-color: green; color: white; font-weight: bold; padding: 5px;")
        self.lbl_alarm.setAlignment(Qt.AlignCenter)
        
        self.btn_ack = QPushButton("收到异常")
        self.btn_ack.clicked.connect(self.ack_alarm)
        self.btn_ack.setEnabled(False)
        
        self.btn_open_safe = QPushButton("📁 安全人员记录")
        self.btn_open_safe.clicked.connect(lambda: subprocess.Popen(["xdg-open", SAFE_LOCAL_DIR]))
        
        self.btn_open_danger = QPushButton("📁 危险人员记录")
        self.btn_open_danger.clicked.connect(lambda: subprocess.Popen(["xdg-open", DANGER_LOCAL_DIR]))
        
        alarm_layout.addWidget(QLabel("系统模式:"))
        alarm_layout.addWidget(self.combo_mode)
        alarm_layout.addWidget(self.lbl_alarm, stretch=1)
        alarm_layout.addWidget(self.btn_ack, stretch=1)
        alarm_layout.addWidget(self.btn_open_safe, stretch=1)
        alarm_layout.addWidget(self.btn_open_danger, stretch=1)
        
        alarm_group.setLayout(alarm_layout)
        layout.addWidget(alarm_group)

        # ============ AI 助手控制 ============
        ai_group = QGroupBox(f"🤖 AI 助手控制 (RK3588: {RK_IP})")
        ai_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        ai_layout = QHBoxLayout()
        self.btn_llm_start = QPushButton("▶ 启动 LLM 服务")
        self.btn_llm_start.setStyleSheet("background-color: #e3f2fd;")
        self.btn_llm_start.clicked.connect(self.start_llm_server)
        ai_layout.addWidget(self.btn_llm_start)
        
        self.btn_llm_stop = QPushButton("⏸ 停止 LLM 服务")
        self.btn_llm_stop.clicked.connect(self.stop_llm_server)
        ai_layout.addWidget(self.btn_llm_stop)
        
        self.btn_assist_start = QPushButton("▶ 启动语音助手")
        self.btn_assist_start.setStyleSheet("background-color: #e8f5e9;")
        self.btn_assist_start.clicked.connect(self.start_voice_assistant)
        ai_layout.addWidget(self.btn_assist_start)
        
        self.btn_assist_stop = QPushButton("⏸ 停止语音助手")
        self.btn_assist_stop.clicked.connect(self.stop_voice_assistant)
        ai_layout.addWidget(self.btn_assist_stop)
        
        ai_group.setLayout(ai_layout)
        layout.addWidget(ai_group)

        # ============ 运动控制 ============
        speed_group = QGroupBox("🎮 运动控制（急停 > 安防 > 行人 > Nav2 > 语音/手动）")
        speed_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        speed_main_layout = QVBoxLayout()
        linear_layout = QHBoxLayout()
        linear_layout.addWidget(QLabel("线速度 (m/s):"))
        self.speed_input = QLineEdit("0.3")
        linear_layout.addWidget(self.speed_input)
        self.btn_send_speed = QPushButton("应用线速度")
        self.btn_send_speed.clicked.connect(self.send_manual_speed)
        linear_layout.addWidget(self.btn_send_speed)
        self.btn_stop_robot = QPushButton("🛑 紧急停车")
        self.btn_stop_robot.setStyleSheet("background-color: red; color: white; font-weight: bold;")
        self.btn_stop_robot.clicked.connect(self.stop_robot)
        linear_layout.addWidget(self.btn_stop_robot)
        self.btn_release_estop = QPushButton("✅ 解除急停")
        self.btn_release_estop.setStyleSheet("background-color: #4caf50; color: white; font-weight: bold;")
        self.btn_release_estop.clicked.connect(self.release_estop)
        linear_layout.addWidget(self.btn_release_estop)
        speed_main_layout.addLayout(linear_layout)

        angular_layout = QHBoxLayout()
        angular_layout.addWidget(QLabel("角速度 (rad/s):"))
        self.angular_input = QLineEdit("1.2")
        angular_layout.addWidget(self.angular_input)
        self.btn_turn_left = QPushButton("⬅ 左转")
        self.btn_turn_left.clicked.connect(self.turn_left)
        angular_layout.addWidget(self.btn_turn_left)
        self.btn_turn_straight = QPushButton("⬆ 直行")
        self.btn_turn_straight.clicked.connect(self.turn_straight)
        angular_layout.addWidget(self.btn_turn_straight)
        self.btn_turn_right = QPushButton("➡ 右转")
        self.btn_turn_right.clicked.connect(self.turn_right)
        angular_layout.addWidget(self.btn_turn_right)
        speed_main_layout.addLayout(angular_layout)
        speed_group.setLayout(speed_main_layout)
        layout.addWidget(speed_group)

        # ============ 双终端 ============
        splitter = QSplitter(Qt.Horizontal)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        ai_widget = QWidget()
        ai_vbox = QVBoxLayout(ai_widget)
        ai_vbox.setContentsMargins(0, 0, 0, 0)
        ai_label = QLabel("🤖 LLM & 语音助手终端")
        ai_label.setStyleSheet("font-weight: bold; color: #333;")
        ai_vbox.addWidget(ai_label)
        self.log_text_ai = QTextEdit()
        self.log_text_ai.setReadOnly(True)
        self.log_text_ai.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: monospace;")
        ai_vbox.addWidget(self.log_text_ai)
        splitter.addWidget(ai_widget)

        sys_widget = QWidget()
        sys_vbox = QVBoxLayout(sys_widget)
        sys_vbox.setContentsMargins(0, 0, 0, 0)
        sys_label = QLabel("⚙️ 系统 & 视觉 & Nav2终端")
        sys_label.setStyleSheet("font-weight: bold; color: #333;")
        sys_vbox.addWidget(sys_label)
        self.log_text_sys = QTextEdit()
        self.log_text_sys.setReadOnly(True)
        self.log_text_sys.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: monospace;")
        sys_vbox.addWidget(self.log_text_sys)
        splitter.addWidget(sys_widget)

        splitter.setSizes([500, 500])
        layout.addWidget(splitter, stretch=1)

    def change_mode(self, index):
        mode_str = "security" if index == 1 else "cruise"
        self.ros_worker.set_mode(mode_str)

    def show_alarm(self):
        self.lbl_alarm.setText("⚠️ 有异常！发现闯入者")
        self.lbl_alarm.setStyleSheet("background-color: red; color: white; font-weight: bold; padding: 5px;")
        self.btn_ack.setEnabled(True)

    def ack_alarm(self):
        self.ros_worker.security_alarm_active = False
        # 【核心新增】发送 STOP_ALARM 给板子，停止无限报警
        msg = String()
        msg.data = "STOP_ALARM"
        self.ros_worker.node.create_publisher(String, '/safety_alarm', 10).publish(msg)
        
        self.lbl_alarm.setText("系统正常")
        self.lbl_alarm.setStyleSheet("background-color: green; color: white; font-weight: bold; padding: 5px;")
        self.btn_ack.setEnabled(False)
        self.append_log("✅ 人工确认：安防警报已解除，已通知板子停止报警")

    def append_log(self, msg, target="sys"):
        if target == "ai":
            self.log_text_ai.append(msg)
        else:
            self.log_text_sys.append(msg)

    def run_process(self, cmd, tag, is_local=False):
        process = QProcess(self)
        target = "ai" if "RK-LLM" in tag or "RK-Assist" in tag else "sys"
        
        process.readyReadStandardOutput.connect(lambda: self.on_process_output(process, tag, target))
        process.readyReadStandardError.connect(lambda: self.on_process_error(process, tag, target))
        process.finished.connect(lambda: self.on_process_finished(process, tag, target))
        self.active_processes.append(process)
        
        if is_local:
            full_cmd = f"source /opt/ros/humble/setup.bash && source ~/ros2_ws/install/setup.bash && {cmd}"
            self.append_log(f"[本地执行] {full_cmd}", target=target)
            process.start("bash", ["-c", full_cmd])
        else:
            self.append_log(f"[远程执行] {cmd}", target=target)
            process.start("ssh", [f"{RK_USER}@{RK_IP}", cmd])

    def on_process_output(self, process, tag, target):
        data = process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
        if data:
            for line in data.splitlines():
                if line.strip(): self.append_log(f"[{tag}] {line}", target=target)

    def on_process_error(self, process, tag, target):
        data = process.readAllStandardError().data().decode('utf-8', errors='ignore')
        if not data: return
        for line in data.splitlines():
            if not line.strip(): continue
            if '0x08 PWM' in line: continue
            self.append_log(f"[{tag}-ERR] {line}", target=target)

    def on_process_finished(self, process, tag, target):
        self.append_log(f"[{tag}] 进程已结束。", target=target)
        if process in self.active_processes:
            self.active_processes.remove(process)
        process.deleteLater()

    def start_all(self):
        self.append_log("🚀 正在一键启动底层与感知节点...")
        self.run_process("ros2 launch patrol_description gazebo_sim.launch.py", "Gazebo", is_local=True)
        self.run_process("python3 -u ~/hil_bridge_sim.py", "HIL-PC", is_local=True)
        
        self.append_log("⏳ 等待 Gazebo 初始化，6 秒后自动启动 Nav2...")
        QTimer.singleShot(6000, self.start_nav2)
        
        cmd_vision = "bash -c 'source /opt/ros/humble/setup.bash && source ~/miniconda3/bin/activate rknn && python3 -u ~/yolo11_rtsp_node.py'"
        self.run_process(cmd_vision, "RK-Vision", False)
        
        cmd_hil = "bash -c 'source /opt/ros/humble/setup.bash && python3 -u ~/hil_bridge.py'"
        self.run_process(cmd_hil, "RK-HIL", False)

        self.append_log("📊 8 秒后自动打开 RViz...")
        rviz_cmd = "rviz2 -d $(ros2 pkg prefix patrol_description)/share/patrol_description/rviz/patrol.rviz"
        QTimer.singleShot(8000, lambda: self.run_process(rviz_cmd, "RViz", is_local=True))

    def start_nav2(self):
        self.append_log("🧭 正在启动 Nav2 导航栈...")
        self.run_process("ros2 launch patrol_description nav2_bringup.launch.py", "Nav2", is_local=True)
        QTimer.singleShot(8000, self.publish_initial_pose)

    def publish_initial_pose(self):
        self.append_log("📍 正在自动设置 AMCL 初始位置...")
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = 'map'
        msg.header.stamp = self.ros_worker.node.get_clock().now().to_msg()
        msg.pose.pose.position.x = 0.0
        msg.pose.pose.position.y = 0.0
        msg.pose.pose.orientation.w = 1.0
        msg.pose.covariance = [
            0.25, 0.0, 0.0, 0.0, 0.0, 0.0,
            0.0, 0.25, 0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0685
        ]
        self.ros_worker.pub_initialpose.publish(msg)

    def stop_local_processes(self):
        self.append_log("⏹ 正在停止本地相关进程...")
        for p in self.active_processes:
            if p.state() != QProcess.NotRunning: p.terminate()

    def stop_rk_vision(self):
        self.run_process("pkill -9 -f yolo11_rtsp_node.py", "RK-Stop", is_local=False)

    def stop_rk_hil(self):
        self.run_process("pkill -9 -f hil_bridge.py", "RK-Stop", is_local=False)

    def start_llm_server(self):
        self.append_log("🚀 启动 LLM（等待 'Running on 8080' 再点语音助手）...", target="ai")
        self.run_process("pkill -9 -f flask_server.py", "RK-LLM-Clean", is_local=False)
        cmd = ("bash -c 'source ~/miniconda3/bin/activate rknn && "
               "cd ~/voice/rknn-llm/examples/rkllm_server_demo/rkllm_server && "
               "export LD_LIBRARY_PATH=~/voice/rknn-llm/rkllm-runtime/Linux/librkllm_api/aarch64:$LD_LIBRARY_PATH && "
               "python3 -u flask_server.py "
               "--rkllm_model_path ~/voice/qwen/RK3588/Qwen2.5-1.5B-Instruct_RK3588_w8a8.rkllm "
               "--target_platform rk3588'")
        self.run_process(cmd, "RK-LLM", is_local=False)

    def stop_llm_server(self):
        self.run_process("pkill -9 -f flask_server.py", "RK-LLM-Stop", is_local=False)

    def start_voice_assistant(self):
        self.append_log("🚀 启动语音助手（发 /cmd_vel_voice，PC 仲裁）...", target="ai")
        self.run_process("pkill -9 -f assistant.py", "RK-Assist-Clean", is_local=False)
        cmd = ("bash -c 'source /opt/ros/humble/setup.bash && "
               "source ~/miniconda3/bin/activate rknn && "
               "cd ~/voice && taskset -c 4-7 python3 -u ~/voice/assistant.py'")
        self.run_process(cmd, "RK-Assist", is_local=False)

    def stop_voice_assistant(self):
        self.run_process("pkill -9 -f assistant.py", "RK-Assist-Stop", is_local=False)

    def send_manual_speed(self):
        try:
            v = float(self.speed_input.text())
            self.ros_worker.target_v = v
            self.ros_worker.estop_latched = False
            self.append_log(f"✅ 手动 v={v}（w={self.ros_worker.target_w:.2f} 保持）")
        except ValueError:
            self.append_log("请输入合法的数字！")

    def stop_robot(self):
        self.ros_worker.estop_latched = True
        self.ros_worker.target_v = 0.0
        self.ros_worker.target_w = 0.0
        self.ros_worker.nav_active = False
        self.ros_worker.nav_v = 0.0
        self.ros_worker.nav_w = 0.0
        self.append_log("🚨 紧急停车（锁存，已清空 Nav2 状态）")

    def release_estop(self):
        self.ros_worker.estop_latched = False
        self.ros_worker.target_v = 0.0
        self.ros_worker.target_w = 0.0
        self.append_log("✅ 急停解除，target 归零，请重新下达导航指令")

    def turn_left(self):
        try:
            w = float(self.angular_input.text())
            self.ros_worker.target_w = abs(w)
            self.ros_worker.estop_latched = False
            self.append_log(f"⬅ 手动 w={abs(w)}")
        except ValueError:
            self.append_log("角速度输入错误")

    def turn_right(self):
        try:
            w = float(self.angular_input.text())
            self.ros_worker.target_w = -abs(w)
            self.ros_worker.estop_latched = False
            self.append_log(f"➡ 手动 w=-{abs(w)}")
        except ValueError:
            self.append_log("角速度输入错误")

    def turn_straight(self):
        self.ros_worker.target_w = 0.0
        self.append_log("⬆ 直行 w=0")

    def closeEvent(self, event):
        self.append_log("=" * 50)
        self.append_log("🧹 正在清理所有进程...")
        try:
            self.ros_worker.estop_latched = True
            self.ros_worker.stop()
        except: pass
        for p in list(self.active_processes):
            try:
                if p.state() != QProcess.NotRunning: p.terminate()
            except: pass
        self.active_processes.clear()

        for cmd in ["pkill -9 -f assistant.py", "pkill -9 -f flask_server.py",
                    "pkill -9 -f yolo11_rtsp_node.py", "pkill -9 -f hil_bridge.py"]:
            try:
                subprocess.run(["ssh", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no",
                                f"{RK_USER}@{RK_IP}", cmd], timeout=5, capture_output=True)
                self.append_log(f"[远程清理] {cmd}")
            except Exception as e:
                self.append_log(f"[远程清理失败] {cmd}: {e}")

        for cmd in ["pkill -9 -f 'gazebo_sim.launch.py'", "pkill -9 -f 'gzserver'",
                    "pkill -9 -f 'gzclient'", "pkill -9 -f hil_bridge_sim.py",
                    "pkill -9 -f 'nav2_bringup.launch.py'", "pkill -9 -f 'nav2'",
                    "pkill -9 -f 'rviz2'"]:
            try:
                subprocess.run(["bash", "-c", cmd], timeout=3, capture_output=True)
                self.append_log(f"[本地清理] {cmd}")
            except: pass

        self.append_log("✅ 清理完毕")
        self.append_log("=" * 50)
        event.accept()
        QApplication.instance().quit()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

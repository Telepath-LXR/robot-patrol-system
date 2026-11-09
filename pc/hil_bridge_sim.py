#!/usr/bin/env python3
import math
import time
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
from std_msgs.msg import Int32MultiArray, Int16MultiArray

class HilBridgeSim(Node):
    def __init__(self):
        super().__init__('hil_bridge_sim')
        self.r = 0.05
        self.L = 0.30
        self.cpr = 1560
        
        self.v_truth = 0.0
        self.w_truth = 0.0
        self.omega_left = 0.0
        self.omega_right = 0.0
        self.acc_left = 0.0
        self.acc_right = 0.0
        self.sent_left = 0
        self.sent_right = 0

        self.cmd_input_v = 0.0
        self.cmd_input_w = 0.0

        self.create_subscription(Odometry, '/odom', self._on_odom, 10)
        self.create_subscription(Int16MultiArray, '/hil_wheel_cmd', self._on_pwm, 10)
        self.create_subscription(Twist, '/cmd_vel_input', self._on_cmd_input, 10)
        
        self.pub_enc = self.create_publisher(Int32MultiArray, '/hil_enc', 10)
        self.pub_cmd = self.create_publisher(Twist, '/cmd_vel_sim', 10)
        
        self.create_timer(0.01, self._on_timer)
        self.get_logger().info('PC 端 HIL 节点启动！')
        
        self.last_pwm_time = time.time()
        self._force_brake_logged = False

    def _on_cmd_input(self, msg):
        self.cmd_input_v = msg.linear.x
        self.cmd_input_w = msg.angular.z

    def _on_odom(self, msg):
        self.v_truth = msg.twist.twist.linear.x
        self.w_truth = msg.twist.twist.angular.z

    def _on_pwm(self, msg):
        if len(msg.data) >= 2:
            self.last_pwm_time = time.time()
            
            # 如果上位机要求刹车，强行切断，给绝对安全兜底
            if abs(self.cmd_input_v) < 0.001 and abs(self.cmd_input_w) < 0.001:
                self.omega_left = 0.0
                self.omega_right = 0.0
                self.pub_cmd.publish(Twist())
                return

            pwm_l, pwm_r = msg.data[0], msg.data[1]
            
            # 假设 1000 的 PWM 对应 10.0 的电机轴角速度 (rad/s)
            tgt_l = (pwm_l / 1000.0) * 30.0
            tgt_r = (pwm_r / 1000.0) * 30.0
            
            # 【核心修复】把平滑系数改成 0.5，甚至 1.0（直接等于）
            # 真实的电机有惯性，0.3~0.5 比较真实。如果 STM32 的 PID 调得不好，直接改成 1.0（瞬间响应）
            self.omega_left += (tgt_l - self.omega_left) * 1.0
            self.omega_right += (tgt_r - self.omega_right) * 1.0
            
            cmd = Twist()
            cmd.linear.x = (self.omega_right + self.omega_left) * 0.5 * self.r
            cmd.angular.z = (self.omega_right - self.omega_left) / self.L * self.r
            self.pub_cmd.publish(cmd)

    def _on_timer(self):
        # 【第一步：刹车判断】
        is_braking = abs(self.cmd_input_v) < 0.001 and abs(self.cmd_input_w) < 0.001
        
        if is_braking:
            self.omega_left = 0.0
            self.omega_right = 0.0
            self.pub_cmd.publish(Twist()) # 100Hz 绝对刹车！
            if not self._force_brake_logged:
                self.get_logger().warn('💥 [PC端强制刹车] 定时器触发！强制向 Gazebo 发 0 速！')
                self._force_brake_logged = True
        else:
            self._force_brake_logged = False
            # 500ms 超时保护 (只有非刹车状态才判断)
            if time.time() - self.last_pwm_time > 0.5:
                self.pub_cmd.publish(Twist())

        # 【第二步：绝对核心！不管刹车还是行驶，必须向 STM32 发送编码器反馈！】
        # 如果刹车时这里被 return 掉，STM32 就会失去反馈死锁！
        wl = (self.v_truth - self.w_truth * self.L * 0.5) / self.r
        wr = (self.v_truth + self.w_truth * self.L * 0.5) / self.r
        self.acc_left += wl * 0.01 * self.cpr / (2.0 * math.pi)
        self.acc_right += wr * 0.01 * self.cpr / (2.0 * math.pi)
        
        dl = int(round(self.acc_left)) - self.sent_left
        dr = int(round(self.acc_right)) - self.sent_right
        self.sent_left += dl
        self.sent_right += dr

        msg = Int32MultiArray()
        msg.data = [dl, dr]
        self.pub_enc.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    rclpy.spin(HilBridgeSim())

if __name__ == '__main__':
    main()

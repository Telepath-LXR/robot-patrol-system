#!/usr/bin/env python3
"""ROS2 <-> STM32 串口桥节点."""
import math
import struct
import time

import serial
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState, Imu
from robot_interfaces.msg import MotorState

from robot_serial.protocol import (
    pack_vel_cmd, pack_heartbeat, FrameParser,
    TYPE_ODOM, TYPE_BATTERY, TYPE_HEARTBEAT_ACK,
)

class HilModeExit(Exception):
    pass

class SerialBridgeNode(Node):
    def __init__(self):
        super().__init__('serial_bridge_node')

        self.declare_parameter('port', '/dev/robot_mcu')
        self.declare_parameter('baud', 115200)
        self.declare_parameter('wheel_base', 0.30)
        self.declare_parameter('max_wheel_speed', 1.0)
        self.declare_parameter('cmd_timeout', 0.5)
        self.declare_parameter('hil_mode', False)
        self.declare_parameter('odom_frame', 'odom')
        self.declare_parameter('base_frame', 'base_link')
        self.declare_parameter('imu_frame', 'imu_link')

        port = self.get_parameter('port').value
        baud = self.get_parameter('baud').value
        self.wheel_base = self.get_parameter('wheel_base').value
        self.max_speed = self.get_parameter('max_wheel_speed').value
        self.cmd_timeout = self.get_parameter('cmd_timeout').value
        self.hil_mode = self.get_parameter('hil_mode').value
        self.odom_frame = self.get_parameter('odom_frame').value
        self.imu_frame = self.get_parameter('imu_frame').value

        if self.hil_mode:
            self.get_logger().warn(f'hil_mode=true: serial_bridge_node 主动退出, {port} 整体让位给 hil_bridge 节点.')
            raise HilModeExit()
        self.base_frame = self.get_parameter('base_frame').value

        try:
            self.ser = serial.Serial(port, baud, bytesize=8, parity='N', stopbits=1, timeout=0)
            try:
                self.ser.setDTR(False)
                self.ser.setRTS(False)
            except OSError:
                pass
        except serial.SerialException as e:
            self.get_logger().fatal(f'打开串口 {port} 失败: {e}')
            raise

        self.parser = FrameParser(self._on_frame)
        self.last_rx_time = time.monotonic()
        self.hb_send_cnt = 0
        self.hb_ack_cnt = 0
        self.cmd_cnt = 0
        self.last_cmd_time = 0.0
        self.cmd_active = False
        self.last_x = 0.0
        self.last_y = 0.0
        self.last_theta = 0.0
        self.last_voltage = 0.0
        self.last_odom_time = None

        qos_cmd = QoSProfile(depth=10)
        qos_tele = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=1)

        self.create_subscription(Twist, '/cmd_vel', self._on_cmd_vel, qos_cmd)
        self.pub_odom = self.create_publisher(Odometry, '/odom', qos_tele)
        self.pub_batt = self.create_publisher(BatteryState, '/battery_state', qos_tele)
        self.pub_imu = self.create_publisher(Imu, '/imu/data', qos_tele)
        self.pub_motor_state = self.create_publisher(MotorState, '/motor_state', qos_tele)

        self.create_timer(0.01, self._read_serial)
        self.create_timer(0.10, self._send_heartbeat)

        # 日志规范化
        self.get_logger().info(f'[Init] Port={port}, Baud={baud}, WheelBase={self.wheel_base}, MaxSpeed={self.max_speed}')
        self.get_logger().info(f'[Init] hil_mode={self.hil_mode}, cmd_timeout={self.cmd_timeout}')
        self.get_logger().info(f'[Init] 0x04 IMU 上行已启用')

    def _on_cmd_vel(self, msg: Twist):
        self.last_cmd_time = time.monotonic()
        self.cmd_active = True
        v = msg.linear.x
        w = msg.angular.z
        if not (math.isfinite(v) and math.isfinite(w)):
            self.get_logger().warn('收到 NaN/Inf 的 /cmd_vel, 丢弃', throttle_duration_sec=5.0)
            return

        v_left = v - w * self.wheel_base / 2.0
        v_right = v + w * self.wheel_base / 2.0
        v_left = max(-self.max_speed, min(self.max_speed, v_left))
        v_right = max(-self.max_speed, min(self.max_speed, v_right))

        try:
            self.ser.write(pack_vel_cmd(v_left, v_right))
            self.cmd_cnt += 1
        except serial.SerialException as e:
            self.get_logger().error(f'串口写失败: {e}', throttle_duration_sec=2.0)

    def _read_serial(self):
        try:
            data = self.ser.read(self.ser.in_waiting or 1)
        except serial.SerialException as e:
            self.get_logger().error(f'串口读失败: {e}', throttle_duration_sec=2.0)
            return
        if data:
            self.parser.feed(data)

    def _on_frame(self, ftype, payload):
        self.last_rx_time = time.monotonic()
        if ftype == TYPE_ODOM and len(payload) == 12:
            x, y, theta = struct.unpack('<fff', payload)
            self.last_x, self.last_y, self.last_theta = x, y, theta
            self._publish_odom(x, y, theta)
        elif ftype == TYPE_BATTERY and len(payload) == 4:
            (volt,) = struct.unpack('<f', payload)
            self.last_voltage = volt
            self._publish_battery(volt)
        elif ftype == TYPE_HEARTBEAT_ACK:
            self.hb_ack_cnt += 1
        elif ftype == 0x04 and len(payload) == 24:
            ax, ay, az, gx, gy, gz = struct.unpack('<ffffff', payload)
            self._publish_imu(ax, ay, az, gx, gy, gz)

    def _publish_odom(self, x, y, theta):
        msg = Odometry()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.odom_frame
        msg.child_frame_id = self.base_frame
        msg.pose.pose.position.x = x
        msg.pose.pose.position.y = y
        msg.pose.pose.orientation.z = math.sin(theta / 2.0)
        msg.pose.pose.orientation.w = math.cos(theta / 2.0)
        now = time.monotonic()
        if self.last_odom_time is not None:
            dt = now - self.last_odom_time
            if 0 < dt < 0.5:
                dx = x - self.last_x
                dy = y - self.last_y
                dtheta = theta - self.last_theta
                dtheta = math.atan2(math.sin(dtheta), math.cos(dtheta))
                v = math.hypot(dx, dy) / dt
                if math.cos(theta) * dx + math.sin(theta) * dy < 0:
                    v = -v
                msg.twist.twist.linear.x = v
                msg.twist.twist.angular.z = dtheta / dt
        self.last_odom_time = now
        self.pub_odom.publish(msg)

    def _publish_battery(self, volt):
        msg = BatteryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.base_frame
        msg.voltage = volt
        msg.present = True
        self.pub_batt.publish(msg)

    def _publish_imu(self, ax, ay, az, gx, gy, gz):
        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.imu_frame
        msg.linear_acceleration.x = ax
        msg.linear_acceleration.y = ay
        msg.linear_acceleration.z = az
        msg.angular_velocity.x = gx
        msg.angular_velocity.y = gy
        msg.angular_velocity.z = gz
        msg.orientation_covariance[0] = -1.0
        self.pub_imu.publish(msg)

    def _send_heartbeat(self):
        try:
            self.ser.write(pack_heartbeat())
            self.hb_send_cnt += 1
        except serial.SerialException as e:
            self.get_logger().error(f'心跳写失败: {e}', throttle_duration_sec=2.0)
            return

        if self.cmd_active and (time.monotonic() - self.last_cmd_time) > self.cmd_timeout:
            try:
                self.ser.write(pack_vel_cmd(0.0, 0.0))
                self.cmd_active = False
                self.get_logger().warn(f'/cmd_vel 超时 {self.cmd_timeout:.1f}s, 已发急停指令', throttle_duration_sec=2.0)
            except serial.SerialException:
                pass

        # 10Hz 发布 /motor_state
        msg = MotorState()
        msg.x = self.last_x
        msg.y = self.last_y
        msg.theta = self.last_theta
        msg.voltage = self.last_voltage
        self.pub_motor_state.publish(msg)

        silent = time.monotonic() - self.last_rx_time
        if silent > 1.0:
            self.get_logger().warn(f'STM32 失联 {silent:.1f}s', throttle_duration_sec=2.0)

    def destroy_node(self):
        try:
            self.ser.write(pack_vel_cmd(0.0, 0.0))
            self.ser.close()
        except Exception:
            pass
        self.get_logger().info(f'退出统计: cmd={self.cmd_cnt}, hb_send={self.hb_send_cnt}, hb_ack={self.hb_ack_cnt}')
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    try:
        node = SerialBridgeNode()
    except HilModeExit:
        rclpy.shutdown()
        return
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass

if __name__ == '__main__':
    main()

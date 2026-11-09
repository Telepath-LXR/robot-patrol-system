#!/usr/bin/env python3
import struct
import serial
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from std_msgs.msg import Int32MultiArray, Int16MultiArray
import math
import time

SERIAL_PORT = '/dev/ttyUSB0' 

def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc

class HilBridge(Node):
    def __init__(self):
        super().__init__('hil_bridge')
        self.ser = serial.Serial(SERIAL_PORT, 115200, timeout=0)
        
        # 【终极硬件修复】防止 PL2303 拉死 STM32
        self.ser.setDTR(False)
        self.ser.setRTS(False)
        
        self.rx_buffer = bytearray()
        
        self.create_subscription(Twist, '/cmd_vel_input', self._on_cmd, 10)
        self.create_subscription(Int32MultiArray, '/hil_enc', self._on_enc, 10)
        
        self.pub_wheel = self.create_publisher(Int16MultiArray, '/hil_wheel_cmd', 10)
        self.pub_odom = self.create_publisher(Odometry, '/stm32_odom', 10)
        
        self.create_timer(0.01, self._rx_loop)
        self.create_timer(0.1, self._send_heartbeat)
        self.get_logger().info('RK3588 HIL 桥接启动 (DTR/RTS 防死锁版)！')

        self.acc_dl = 0
        self.acc_dr = 0
        self.last_enc_time = time.time()
        self.last_cmd_time = 0

    def _pack(self, ftype, payload):
        body = bytes([ftype, len(payload)]) + payload
        crc = crc16(body)
        return bytes([0xAA, 0x55]) + body + struct.pack(">H", crc) + bytes([0x0D])

    def _on_cmd(self, msg):
        v_l = msg.linear.x - msg.angular.z * 0.30 / 2.0
        v_r = msg.linear.x + msg.angular.z * 0.30 / 2.0
        self.ser.write(self._pack(0x01, struct.pack("<ff", v_l, v_r)))
        self.get_logger().info(f'发送 0x01: v_l={v_l:.2f}, v_r={v_r:.2f}')

    def _on_enc(self, msg):
        if len(msg.data) >= 2:
            self.acc_dl += msg.data[0]
            self.acc_dr += msg.data[1]
            
            now = time.time()
            if now - self.last_enc_time >= 0.1:
                self.ser.write(self._pack(0x07, struct.pack("<ii", self.acc_dl, self.acc_dr)))
                self.acc_dl = 0
                self.acc_dr = 0
                self.last_enc_time = now

    def _send_heartbeat(self):
        self.ser.write(self._pack(0x05, b""))

    def _rx_loop(self):
        try:
            if self.ser.in_waiting > 0:
                raw_data = self.ser.read(self.ser.in_waiting)
                self.rx_buffer.extend(raw_data)
                
                if len(self.rx_buffer) > 2000:
                    self.rx_buffer = self.rx_buffer[-100:]
                
                while len(self.rx_buffer) >= 7:
                    if self.rx_buffer[0] != 0xAA or self.rx_buffer[1] != 0x55:
                        self.rx_buffer.pop(0)
                        continue
                    ftype = self.rx_buffer[2]
                    dlen = self.rx_buffer[3]
                    total = 7 + dlen
                    if len(self.rx_buffer) < total:
                        break
                    frame = self.rx_buffer[:total]
                    self.rx_buffer = self.rx_buffer[total:]
                    
                    if frame[-1] != 0x0D:
                        continue

                    if ftype == 0x08 and dlen == 8:
                        pwm_l, pwm_r, spd_l, spd_r = struct.unpack("<hhhh", frame[4:12])
                        msg = Int16MultiArray()
                        msg.data = [pwm_l, pwm_r]
                        self.pub_wheel.publish(msg)
                        self.get_logger().info(f'0x08 PWM: L={pwm_l}, R={pwm_r}')
                    elif ftype == 0x02 and dlen == 12:
                        x, y, theta = struct.unpack("<fff", frame[4:16])
                        odom = Odometry()
                        odom.header.stamp = self.get_clock().now().to_msg()
                        odom.header.frame_id = 'odom'
                        odom.child_frame_id = 'base_link'
                        odom.pose.pose.position.x = x
                        odom.pose.pose.position.y = y
                        odom.pose.pose.orientation.z = math.sin(theta * 0.5)
                        odom.pose.pose.orientation.w = math.cos(theta * 0.5)
                        self.pub_odom.publish(odom)
        except Exception as e:
            pass

def main(args=None):
    rclpy.init(args=args)
    rclpy.spin(HilBridge())

if __name__ == '__main__':
    main()

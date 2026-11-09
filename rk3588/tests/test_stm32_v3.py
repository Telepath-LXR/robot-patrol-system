#!/usr/bin/env python3
import sys, struct, time, threading
sys.path.insert(0, '~/pytest')

import serial
from robot_protocol import (pack_vel_cmd, pack_heartbeat, FrameParser,
                            TYPE_ODOM, TYPE_BATTERY, TYPE_HEARTBEAT_ACK)

PORT = '/dev/robot_mcu'
BAUD = 115200
stop = False

ser = serial.Serial(PORT, BAUD, bytesize=8, parity='N', stopbits=1, timeout=0.1)
ser.setDTR(False)
ser.setRTS(False)
print('[INIT] 串口已开 %s，DTR/RTS=False（robot_protocol.py 大端 CRC）' % PORT)

def on_frame(ftype, payload):
    if ftype == TYPE_ODOM and len(payload) == 12:
        x, y, theta = struct.unpack('<fff', payload)
        print('[ODOM] x=%.3f y=%.3f theta=%.3f' % (x, y, theta))
    elif ftype == TYPE_BATTERY and len(payload) == 4:
        (v,) = struct.unpack('<f', payload)
        print('[BATT] %.2fV' % v)
    elif ftype == TYPE_HEARTBEAT_ACK:
        print('[HB-ACK] payload=%s' % payload.hex())

def hb_thread():
    while not stop:
        ser.write(pack_heartbeat())
        time.sleep(0.1)

def tx_thread():
    while not stop:
        ser.write(pack_vel_cmd(0.3, 0.3))
        time.sleep(0.05)

def rx_thread():
    parser = FrameParser(on_frame)
    while not stop:
        try:
            chunk = ser.read(64)
        except serial.SerialException:
            break
        if chunk:
            parser.feed(chunk)

threading.Thread(target=hb_thread, daemon=True).start()
threading.Thread(target=tx_thread, daemon=True).start()
threading.Thread(target=rx_thread, daemon=True).start()

print('[RUN] 5 秒，盯着 STM32 LED0，亮度应稳定在中等偏亮')
try:
    time.sleep(5)
finally:
    stop = True
    time.sleep(0.2)
    ser.close()
    print('[DONE]')

#!/usr/bin/env python3
import serial, struct, time, threading, sys

def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def pack(ftype, payload=b''):
    body = bytes([ftype, len(payload)]) + payload
    return bytes([0xAA, 0x55]) + body + struct.pack('<H', crc16(body)) + bytes([0x0D])

# 打开串口
s = serial.Serial('/dev/robot_mcu', 115200, timeout=0.1)
# 项目17 踩过的坑：DTR/RTS 会触发 STM32 复位
s.dtr = False
s.rts = False
print('[INIT] 串口打开: /dev/robot_mcu, DTR=False RTS=False')

stop = False

def heartbeat_thread():
    """每 100ms 发一帧 0x05 心跳"""
    count = 0
    while not stop:
        s.write(pack(0x05))
        count += 1
        if count % 10 == 0:
            print('[HB] 已发心跳 %d 次' % count)
        time.sleep(0.1)

def tx_thread():
    """每 50ms 发一帧 0x01 指令，速度保持 0.3 m/s 直行"""
    while not stop:
        s.write(pack(0x01, struct.pack('<ff', 0.3, 0.3)))
        time.sleep(0.05)

def rx_thread():
    """接收并解析"""
    parser_buf = bytearray()
    while not stop:
        data = s.read(64)
        if not data:
            continue
        parser_buf.extend(data)
        # 简化解析：找 aa55 开头
        i = 0
        while i < len(parser_buf) - 5:
            if parser_buf[i] == 0xAA and parser_buf[i+1] == 0x55:
                ftype = parser_buf[i+2]
                dlen = parser_buf[i+3]
                if i + 4 + dlen + 3 > len(parser_buf):
                    break  # 数据不够，等下次
                payload = bytes(parser_buf[i+4:i+4+dlen])
                if ftype == 0x02 and dlen == 12:
                    l, r, tick = struct.unpack('<ffI', payload)
                    print('[ODOM] left=%.3f right=%.3f tick=%d' % (l, r, tick))
                elif ftype == 0x03 and dlen == 4:
                    (v,) = struct.unpack('<f', payload)
                    print('[BATT] %.2fV' % v)
                elif ftype == 0x05:
                    print('[HB] 收到 STM32 心跳')
                elif ftype == 0x06 and dlen == 1:
                    print('[ACK] 应答 TYPE=0x%02X' % payload[0])
                i += 4 + dlen + 3
            else:
                i += 1
        # 保留尾部
        parser_buf = parser_buf[i:]

threads = [
    threading.Thread(target=heartbeat_thread, daemon=True),
    threading.Thread(target=tx_thread, daemon=True),
    threading.Thread(target=rx_thread, daemon=True),
]
for t in threads:
    t.start()

print('[RUN] 发送心跳+速度指令中，观察 5 秒...')
print('[RUN] 盯着 STM32 LED0，亮度应稳定在中等偏亮')
try:
    time.sleep(5)
finally:
    stop = True
    time.sleep(0.2)
    s.close()
    print('[DONE] 测试结束')

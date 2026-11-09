#!/usr/bin/env python3
"""socat/pty 虚拟串口注入测试: 好帧/坏CRC/半帧/噪声/恢复."""
import sys
import struct
import time

sys.path.insert(0, '~/robot_ws/src/robot_serial/robot_serial')
from protocol import pack_vel_cmd, crc16, HEAD1, HEAD2, TAIL


def build_frame(ftype, payload=b''):
    body = bytes([ftype, len(payload)]) + payload
    crc = crc16(body)
    return bytes([HEAD1, HEAD2]) + body + struct.pack('>H', crc) + bytes([TAIL])


def main(port):
    f = open(port, 'wb', buffering=0)
    print('[INJ] 开始注入到', port)

    good_odom = build_frame(0x02, struct.pack('<fff', 0.1, 0.2, 0.3))
    f.write(good_odom)
    print('[INJ] ① 好帧 0x02: x=0.1 y=0.2 theta=0.3')
    time.sleep(0.5)

    bad = bytearray(build_frame(0x02, struct.pack('<fff', 9.9, 9.9, 9.9)))
    bad[-2] ^= 0xFF
    f.write(bytes(bad))
    print('[INJ] ② 坏 CRC 帧: 应被静默丢弃')
    time.sleep(0.5)

    half = build_frame(0x02, struct.pack('<fff', 0.5, 0.5, 0.5))[:5]
    f.write(half)
    print('[INJ] ③ 半帧: 状态机挂起')
    time.sleep(0.5)

    f.write(b'\x00\xff\x13\x37' * 4)
    print('[INJ] ④ 噪声 16 字节: 状态机重同步')
    time.sleep(0.5)

    good_recover = build_frame(0x02, struct.pack('<fff', 0.4, 0.4, 0.4))
    f.write(good_recover)
    print('[INJ] ⑤ 恢复帧 0x02: x=0.4')
    time.sleep(0.5)

    good_batt = build_frame(0x03, struct.pack('<f', 12.34))
    f.write(good_batt)
    print('[INJ] ⑥ 电压帧 0x03: 12.34V')

    f.close()
    print('[INJ] 注入结束')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/vser_b')

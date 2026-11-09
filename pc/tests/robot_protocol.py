"""具身智能巡检机器人 上下位机通信协议 v1.0 编解码模块。

帧格式: [0xAA][0x55][TYPE][LEN][DATA(N)][CRC16_H][CRC16_L][0x0D]
CRC: CRC-16/CCITT-FALSE (多项式 0x1021, 初值 0xFFFF)，
     计算范围为帧头之后、CRC 之前（TYPE+LEN+DATA），按大端传输。
多字节数据一律小端。本模块不含任何 I/O，供测试脚本与 ROS2 桥接节点复用。
阶段五 serial_bridge_node 将 import 本模块，禁止破坏 API。
"""
import struct

HEAD1, HEAD2, TAIL = 0xAA, 0x55, 0x0D
MAX_DATA = 32

TYPE_VEL_CMD = 0x01
TYPE_ODOM    = 0x02
TYPE_BATTERY = 0x03
TYPE_IMU     = 0x04
TYPE_HEARTBEAT     = 0x05
TYPE_HEARTBEAT_ACK = 0x06


def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE 计算法。校验向量: crc16(b'123456789') == 0x29B1。"""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def pack_frame(ftype: int, payload: bytes = b"") -> bytes:
    """打包一帧。CRC 高字节在前（协议规定 CRC 大端传输）。"""
    assert len(payload) <= MAX_DATA
    body = bytes([ftype, len(payload)]) + payload
    crc = crc16(body)
    return bytes([HEAD1, HEAD2]) + body + struct.pack(">H", crc) + bytes([TAIL])


def pack_vel_cmd(v_left: float, v_right: float) -> bytes:
    """0x01 速度指令帧：'<ff' 即两个小端 float。"""
    return pack_frame(TYPE_VEL_CMD, struct.pack("<ff", v_left, v_right))


def pack_heartbeat() -> bytes:
    return pack_frame(TYPE_HEARTBEAT)


class FrameParser:
    """8 态逐字节解析状态机，与 STM32 侧 protocol_parse.c 逻辑等价。"""

    (WAIT_HEAD1, WAIT_HEAD2, TYPE, LEN, DATA, CRC_H, CRC_L, TAIL_ST) = range(8)

    def __init__(self, on_frame):
        self.on_frame = on_frame
        self.state = self.WAIT_HEAD1
        self.ftype = 0
        self.length = 0
        self.buf = bytearray()
        self.crc_h = 0
        self.ok_cnt = 0
        self.crc_err = 0
        self.len_err = 0
        self.tail_err = 0

    def _resync(self, byte: int):
        self.state = self.WAIT_HEAD2 if byte == HEAD1 else self.WAIT_HEAD1
        self.buf.clear()

    def feed(self, chunk: bytes):
        for b in chunk:
            self._feed_byte(b)

    def _feed_byte(self, b: int):
        s = self.state
        if s == self.WAIT_HEAD1:
            if b == HEAD1:
                self.state = self.WAIT_HEAD2
        elif s == self.WAIT_HEAD2:
            if b == HEAD2:
                self.state = self.TYPE
            else:
                self._resync(b)
        elif s == self.TYPE:
            self.ftype = b
            self.state = self.LEN
        elif s == self.LEN:
            if b > MAX_DATA:
                self.len_err += 1
                self._resync(b)
            else:
                self.length = b
                self.buf.clear()
                self.state = self.CRC_H if b == 0 else self.DATA
        elif s == self.DATA:
            self.buf.append(b)
            if len(self.buf) >= self.length:
                self.state = self.CRC_H
        elif s == self.CRC_H:
            self.crc_h = b
            self.state = self.CRC_L
        elif s == self.CRC_L:
            crc_recv = (self.crc_h << 8) | b
            body = bytes([self.ftype, self.length]) + bytes(self.buf)
            if crc16(body) == crc_recv:
                self.state = self.TAIL_ST
            else:
                self.crc_err += 1
                self._resync(b)
        elif s == self.TAIL_ST:
            if b == TAIL:
                self.ok_cnt += 1
                self.on_frame(self.ftype, bytes(self.buf))
                self.state = self.WAIT_HEAD1
            else:
                self.tail_err += 1
                self._resync(b)
        else:
            self.state = self.WAIT_HEAD1
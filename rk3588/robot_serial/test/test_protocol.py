"""编解码离线对拍：全部通过才允许接真机."""
import struct
from robot_serial.protocol import crc16, pack_vel_cmd, FrameParser


def test_golden_vectors():
    assert crc16(b"123456789") == 0x29B1, "标准校验向量失败"
    assert crc16(bytes([0x05, 0x00])) == 0xE2FA, "心跳帧 CRC 与 STM32 侧不一致"
    golden = pack_vel_cmd(0.5, -0.5)
    assert golden.hex(" ") == "aa 55 01 08 00 00 00 3f 00 00 00 bf 98 a0 0d"
    print("黄金向量全部通过")


def test_parser_robustness():
    frames = []
    p = FrameParser(lambda t, d: frames.append((t, d)))
    good = pack_vel_cmd(1.0, 2.0)
    bad = bytearray(pack_vel_cmd(9.9, 9.9))
    bad[6] ^= 0x01                       # 翻转 DATA 中 1 bit，CRC 必然失败
    p.feed(b"\x11\x22\xaa" + good + bytes(bad) + good)
    assert len(frames) == 2, f"应解析出 2 帧，实际 {len(frames)}"
    assert frames[0][0] == 0x01
    v = struct.unpack("<ff", frames[0][1])
    assert abs(v[0] - 1.0) < 1e-6 and abs(v[1] - 2.0) < 1e-6
    assert p.crc_err == 1, "坏帧未被 CRC 拦截"
    print(f"健壮性通过: ok={p.ok_cnt} crc_err={p.crc_err}")


if __name__ == "__main__":
    test_golden_vectors()
    test_parser_robustness()

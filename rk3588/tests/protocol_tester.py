"""PC 端协议全链路测试脚本（项目17）。
用法: python protocol_tester.py COM5          (Windows)
      python protocol_tester.py /dev/ttyUSB0  (Linux / RK3588)
键盘: w/s 左轮速 +/-0.05, o/l 右轮速 +/-0.05, 空格急停, q 退出。
本脚本即阶段五 ROS2 serial_bridge_node 的前身。
"""
import sys
import threading
import time
import struct

import serial

from robot_protocol import (FrameParser, pack_vel_cmd, pack_heartbeat,
                            TYPE_ODOM, TYPE_BATTERY, TYPE_HEARTBEAT_ACK)

BAUD = 115200
HB_PERIOD = 0.1
RX_TIMEOUT_ALARM = 0.5
ODOM_PRINT_EVERY = 2          # [增强1] ODOM 解析 10Hz，显示 5Hz，防终端刷屏

v_left = 0.0
v_right = 0.0
lock = threading.Lock()
last_rx_time = time.monotonic()
running = True

# [增强2] 心跳抖动统计 + 应答计数，用于验收项 5
hb_send_ts = []
hb_send_cnt = 0
hb_ack_cnt = 0
stats_lock = threading.Lock()
_odom_cnt = 0


def on_frame(ftype, payload):
    global last_rx_time, hb_ack_cnt, _odom_cnt
    last_rx_time = time.monotonic()
    if ftype == TYPE_ODOM and len(payload) == 12:
        x, y, theta = struct.unpack("<fff", payload)
        _odom_cnt += 1
        if _odom_cnt % ODOM_PRINT_EVERY == 0:
            print(f"\r[ODOM] x={x:+.3f} m  y={y:+.3f} m  theta={theta:+.3f} rad   ",
                  end="", flush=True)
    elif ftype == TYPE_BATTERY and len(payload) == 4:
        (volt,) = struct.unpack("<f", payload)
        print(f"\n[BATT] {volt:.2f} V")
    elif ftype == TYPE_HEARTBEAT_ACK and len(payload) == 1:
        with stats_lock:
            hb_ack_cnt += 1
        if payload[0] != 0:
            print("\n[HB-ACK] 下位机处于报警状态")


def heartbeat_thread(ser):
    global hb_send_cnt
    while running:
        ser.write(pack_heartbeat())
        ts = time.monotonic()
        with stats_lock:
            hb_send_cnt += 1
            hb_send_ts.append(ts)
            if len(hb_send_ts) > 100:
                hb_send_ts.pop(0)
        time.sleep(HB_PERIOD)


def rx_thread(ser):
    global last_rx_time
    parser = FrameParser(on_frame)
    while running:
        try:
            chunk = ser.read(64)
        except serial.SerialException:
            break
        if chunk:
            parser.feed(chunk)
        if time.monotonic() - last_rx_time > RX_TIMEOUT_ALARM:
            print("\n[WARN] 500ms 未收到下位机任何数据，判定下位机异常！")
            last_rx_time = time.monotonic()


def send_vel(ser):
    with lock:
        ser.write(pack_vel_cmd(v_left, v_right))
    print(f"\n[TX] v_left={v_left:+.2f}  v_right={v_right:+.2f}")


def _set_cbreak():
    # [增强3] Linux 下 stdin 是行缓冲，必须切字符级原始模式
    if sys.platform == "win32":
        return None
    import termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    return fd, old


def _restore_tty(state):
    if state is None:
        return
    import termios
    fd, old = state
    termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main():
    global v_left, v_right, running
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    ser = serial.Serial(port, BAUD, bytesize=8, parity="N",stopbits=1, timeout=0.1)
    ser.setDTR(False)
    ser.setRTS(False)
    print(f"已打开 {port} @ {BAUD} 8N1")

    t_hb = threading.Thread(target=heartbeat_thread, args=(ser,), daemon=True)
    t_rx = threading.Thread(target=rx_thread, args=(ser,), daemon=True)
    t_hb.start()
    t_rx.start()

    tty_state = _set_cbreak()
    print("控制: w/s 左轮+/-  o/l 右轮+/-  空格急停  q退出")
    try:
        while True:
            ch = sys.stdin.read(1)
            if not ch:                     # EOF（Ctrl+Z / Ctrl+D）
                break
            if ch == "w":
                v_left += 0.05
            elif ch == "s":
                v_left -= 0.05
            elif ch == "o":
                v_right += 0.05
            elif ch == "l":
                v_right -= 0.05
            elif ch == " ":
                v_left = v_right = 0.0
            elif ch == "q":
                break
            else:
                continue
            send_vel(ser)
    finally:
        _restore_tty(tty_state)
        v_left = v_right = 0.0
        try:
            send_vel(ser)                  # [增强4] 退出前急停，防御性设计
        except serial.SerialException:
            pass
        running = False
        time.sleep(0.2)                    # 给 rx 线程退出窗口，避免 close 时抛异常
        ser.close()
        with stats_lock:                   # 退出统计，验收项 5 用
            n = len(hb_send_ts)
            if n >= 2:
                dts = [hb_send_ts[i+1] - hb_send_ts[i] for i in range(n-1)]
                avg = sum(dts) / len(dts)
                print(f"\n[STAT] HB 发送 {hb_send_cnt} 次，最近 {n-1} 个间隔 "
                      f"均值 {avg*1000:.1f} ms，min {min(dts)*1000:.1f}，"
                      f"max {max(dts)*1000:.1f}；HB-ACK {hb_ack_cnt} 次")


if __name__ == "__main__":
    main()
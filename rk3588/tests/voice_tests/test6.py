#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L0 + 扩展项 全量可用性测试（普通用户权限）"""
import os, glob, time, socket, subprocess, re
from datetime import datetime

def check(name, fn):
    try:
        val = fn()
        if val is None:
            print(f"  ❌ {name:12s} : 读不到")
            return False
        print(f"  ✅ {name:12s} : {val}")
        return True
    except Exception as e:
        print(f"  ❌ {name:12s} : {e}")
        return False

# ---------- 温度 ----------
def _read_thermal(kws):
    temps = []
    for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            ztype = open(f"{zone}/type").read().strip().lower()
            if any(k in ztype for k in kws):
                temps.append(int(open(f"{zone}/temp").read().strip()) / 1000.0)
        except Exception:
            continue
    return max(temps) if temps else None

# ---------- CPU 占用 ----------
def get_cpu_usage():
    def _snap():
        with open("/proc/stat") as f:
            p = list(map(int, f.readline().split()[1:]))
        idle = p[3] + (p[4] if len(p) > 4 else 0)
        return idle, sum(p)
    i1, t1 = _snap(); time.sleep(0.3); i2, t2 = _snap()
    dt = t2 - t1
    return f"{100.0 * (1 - (i2 - i1) / dt):.1f}%" if dt > 0 else "0%"

# ---------- 内存 ----------
def get_mem():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k] = int(v.strip().split()[0])
    used = info["MemTotal"] - info.get("MemAvailable", info["MemFree"])
    return f"{100.0 * used / info['MemTotal']:.1f}%"

# ---------- 磁盘 ----------
def get_disk():
    st = os.statvfs("/")
    return f"{st.f_bavail * st.f_frsize / (1024**3):.1f} GB"

# ---------- 运行时长 ----------
def get_uptime():
    with open("/proc/uptime") as f:
        return f"{float(f.read().split()[0]) / 3600.0:.2f} 小时"

# ---------- 负载 ----------
def get_load():
    with open("/proc/loadavg") as f:
        p = f.read().split()
    return f"1m={p[0]} 5m={p[1]} 15m={p[2]}"

# ---------- 日期时间 ----------
def get_datetime():
    now = datetime.now()
    wd = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日"]
    return f"{now.year}年{now.month}月{now.day}日 {wd[now.weekday()]} {now.hour}:{now.minute:02d}"

# ---------- CPU 频率 ----------
def get_freq():
    with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq") as f:
        return f"{int(f.read().strip()) / 1e6:.2f} GHz"

# ---------- CPU governor ----------
def get_gov():
    with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor") as f:
        return f.read().strip()

# ---------- IP ----------
def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip

# ---------- 进程数 ----------
def get_procs():
    return f"{sum(1 for p in os.listdir('/proc') if p.isdigit())} 个"

# ---------- NPU 负载（预期失败） ----------
def get_npu_load():
    try:
        with open("/sys/kernel/debug/rknpu/load") as f:
            return f.read().strip()
    except PermissionError:
        return None
    except Exception:
        return None

# ---------- STM32 设备 ----------
def get_stm32_port():
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    return ports[0] if ports else None

# ---------- STM32 占用（fuser 权限测试） ----------
def get_stm32_occupied():
    port = get_stm32_port()
    if not port:
        return "无设备"
    try:
        r = subprocess.run(["fuser", port], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            return f"被占用 PID={r.stdout.strip() or r.stderr.strip()}"
        else:
            return "未被占用"
    except Exception as e:
        return f"fuser 异常: {e}"

if __name__ == "__main__":
    print("=" * 50)
    print("全量可用性测试（当前用户: %s）" % os.popen("whoami").read().strip())
    print("=" * 50)

    print("\n[温度]")
    check("CPU 温度", lambda: f"{_read_thermal(['soc','cpu','bigcore','littlecore','cluster','center']):.1f} °C")
    check("NPU 温度", lambda: f"{_read_thermal(['npu']):.1f} °C")
    check("GPU 温度", lambda: f"{_read_thermal(['gpu']):.1f} °C")

    print("\n[负载 / 资源]")
    check("CPU 占用", get_cpu_usage)
    check("内存占用", get_mem)
    check("磁盘剩余", get_disk)
    check("运行时长", get_uptime)
    check("系统负载", get_load)
    check("CPU 频率", get_freq)
    check("CPU 调频", get_gov)
    check("进程数", get_procs)

    print("\n[日期 / 网络]")
    check("当前日期", get_datetime)
    check("本机 IP", get_ip)

    print("\n[NPU]")
    ok = check("NPU 负载", get_npu_load)
    if not ok:
        print("     → 需要 root，已确认放弃此项")

    print("\n[STM32]")
    check("串口设备", get_stm32_port)
    check("串口占用", get_stm32_occupied)

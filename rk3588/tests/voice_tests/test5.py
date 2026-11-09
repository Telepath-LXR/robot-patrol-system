#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L0 板子健康查询 - 独立验证脚本，不依赖 assistant.py"""
import os, glob, time

def _read_thermal(zone_keywords):
    """按 type 关键字匹配所有相关 zone，取最大值"""
    temps = []
    for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            ztype = open(f"{zone}/type").read().strip().lower()
            if any(k in ztype for k in zone_keywords):
                temps.append(int(open(f"{zone}/temp").read().strip()) / 1000.0)
        except Exception:
            continue
    return max(temps) if temps else None

def get_cpu_temp(): return _read_thermal(["soc", "cpu", "bigcore", "littlecore", "cluster", "center"])
def get_npu_temp(): return _read_thermal(["npu"])
def get_gpu_temp(): return _read_thermal(["gpu"])

def get_cpu_usage():
    def _snap():
        with open("/proc/stat") as f:
            p = list(map(int, f.readline().split()[1:]))
        idle = p[3] + (p[4] if len(p) > 4 else 0)
        return idle, sum(p)
    i1, t1 = _snap()
    time.sleep(0.3)
    i2, t2 = _snap()
    dt = t2 - t1
    return 100.0 * (1 - (i2 - i1) / dt) if dt > 0 else 0.0

def get_mem_usage():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k] = int(v.strip().split()[0])
    total = info["MemTotal"]
    used = total - info.get("MemAvailable", info["MemFree"])
    return 100.0 * used / total

def get_disk_free_gb(path="/"):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / (1024 ** 3)

def get_uptime_hours():
    with open("/proc/uptime") as f:
        return float(f.read().split()[0]) / 3600.0

def get_loadavg():
    with open("/proc/loadavg") as f:
        p = f.read().split()
    return float(p[0]), float(p[1]), float(p[2])

if __name__ == "__main__":
    print("=== thermal_zone 全部映射（确认编号） ===")
    for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        try:
            print(f"  {z}: type={open(z+'/type').read().strip():20s} "
                  f"temp={int(open(z+'/temp').read().strip())/1000.0:.1f}°C")
        except Exception as e:
            print(f"  {z}: 读取失败 {e}")

    print("\n=== 6 项功能验证 ===")
    print(f"  CPU 占用率 : {get_cpu_usage():.1f}%")
    print(f"  CPU 温度   : {get_cpu_temp()} °C")
    print(f"  NPU 温度   : {get_npu_temp()} °C")
    print(f"  GPU 温度   : {get_gpu_temp()} °C")
    print(f"  内存占用   : {get_mem_usage():.1f}%")
    print(f"  磁盘剩余   : {get_disk_free_gb():.1f} GB")
    print(f"  运行时长   : {get_uptime_hours():.2f} 小时")
    print(f"  负载均值   : 1m={get_loadavg()[0]} 5m={get_loadavg()[1]} 15m={get_loadavg()[2]}")

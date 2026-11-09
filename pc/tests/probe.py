import sys, time, serial

port = sys.argv[1] if len(sys.argv) > 1 else "COM4"

# 1. 先关掉 XCOM，再运行这个脚本
ser = serial.Serial(port, 115200, timeout=0.1)
print(f"已打开 {port}")

# 2. 关键：尝试拉低 DTR/RTS（很多板子需要低电平才能正常运行）
ser.setDTR(False)
ser.setRTS(False)
print("已将 DTR 和 RTS 拉低")

# 3. 疯狂读 2 秒钟，把原始字节打印出来
t0 = time.monotonic()
got = bytearray()
while time.monotonic() - t0 < 2.0:
    c = ser.read(64)
    if c:
        got.extend(c)
        
ser.close()
print(f"总共收到 {len(got)} 字节")
if got:
    print(f"原始数据头: {got[:20].hex(' ')} ...")
else:
    print("!!! 0 字节，如果 XCOM 能收到，请把上面的 setDTR(True) / setRTS(True) 再试一次")
import serial
import time

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
print("开始读取...")

# 先发一个心跳包 (0x05)，让 STM32 知道上位机还活着
# 帧格式: AA 55 05 00 [CRC_H] [CRC_L] 0D
heartbeat = bytes([0xAA, 0x55, 0x05, 0x00, 0x00, 0x00, 0x0D])

while True:
    ser.write(heartbeat)
    time.sleep(0.1)
    
    # 把读到的所有原始字节打印出来
    data = ser.read_all()
    if len(data) > 0:
        print(f"收到 {len(data)} 字节: {data.hex()}")

import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav

# 你的板载声卡是 48kHz、双声道
fs = 48000
seconds = 5
print("开始录音 5 秒，请对着板载麦克风说话...")
recording = sd.rec(int(seconds * fs), samplerate=fs, channels=2, dtype='int16')
sd.wait()
print("录音结束！")

wav.write('rk3588_test.wav', fs, recording)
print("已保存为 rk3588_test.wav")

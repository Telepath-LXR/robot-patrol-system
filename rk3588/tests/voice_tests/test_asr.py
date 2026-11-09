import sherpa_onnx
import wave
import numpy as np
from scipy.signal import resample_poly

# SenseVoice ONNX 模型路径（按你实际下载的目录改）
model_dir = "~/voice/sense-voice-onnx"

recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
    model=f"{model_dir}/model.int8.onnx",
    tokens=f"{model_dir}/tokens.txt",
    num_threads=2,
    use_itn=True,
    language="zh",
)

# 读取你之前录的 wav（48kHz 双声道）
wav_path = "~/voice/test_all.wav"
with wave.open(wav_path) as f:
    assert f.getnchannels() == 2, "需要双声道 wav"
    samples = f.readframes(f.getnframes())
    samples = np.frombuffer(samples, dtype=np.int16).astype(np.float32) / 32768.0
    samples = samples.reshape(-1, 2).mean(axis=1)  # 降混单声道
    sr = f.getframerate()

# 重采样到 16k
audio_16k = resample_poly(samples, up=16000, down=sr).astype(np.float32)

stream = recognizer.create_stream()
stream.accept_waveform(16000, audio_16k)
recognizer.decode_stream(stream)

print("识别结果:", stream.result.text)

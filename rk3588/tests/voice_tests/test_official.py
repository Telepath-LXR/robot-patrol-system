import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
import sherpa_onnx

model_dir = "~/voice/model"
kws = sherpa_onnx.KeywordSpotter(
    tokens=f"{model_dir}/tokens.txt",
    encoder=f"{model_dir}/encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    decoder=f"{model_dir}/decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    joiner=f"{model_dir}/joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    keywords_file=f"{model_dir}/keywords.txt",   # 模型自带词表
    num_threads=2,
)

wav_path = f"{model_dir}/test_wavs/0.wav"
audio, sr = sf.read(wav_path, dtype="float32")
print(f"wav: {wav_path}, sr={sr}, shape={audio.shape}, peak={np.max(np.abs(audio)):.4f}")

if sr != 16000:
    audio = resample_poly(audio, up=16000, down=sr).astype(np.float32)

stream = kws.create_stream()
stream.accept_waveform(16000, audio)
hits = []
count = 0
while kws.is_ready(stream):
    kws.decode_stream(stream)
    count += 1
    result = kws.get_result(stream)
    if result:
        hits.append(result)
        kws.reset_stream(stream)

print(f"解码次数: {count}")
print(f"官方词表命中结果: {hits}")

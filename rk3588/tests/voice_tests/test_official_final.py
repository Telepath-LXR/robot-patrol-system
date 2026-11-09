import wave
import numpy as np
import sherpa_onnx

model_dir = "~/voice/model"

# 1. 初始化 KeywordSpotter（使用官方测试词表）
kws = sherpa_onnx.KeywordSpotter(
    tokens=f"{model_dir}/tokens.txt",
    encoder=f"{model_dir}/encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    decoder=f"{model_dir}/decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    joiner=f"{model_dir}/joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    keywords_file=f"{model_dir}/test_wavs/test_keywords.txt",
    num_threads=2,
    provider="cpu",
)

# 2. 严格按照官方示例读取 WAV（必须是单声道、16bit）
wave_filename = f"{model_dir}/test_wavs/0.wav"
with wave.open(wave_filename) as f:
    assert f.getnchannels() == 1, "必须单声道"
    assert f.getsampwidth() == 2, "必须16bit"
    samples = f.readframes(f.getnframes())
    samples_float32 = np.frombuffer(samples, dtype=np.int16).astype(np.float32) / 32768.0
    sample_rate = f.getframerate()

print(f"音频加载成功: sr={sample_rate}, 时长={len(samples_float32)/sample_rate:.2f}s")

# 3. 官方标准流控：尾部补静音 -> 标记结束 -> 循环解码
tail_paddings = np.zeros(int(0.66 * sample_rate), dtype=np.float32)
s = kws.create_stream()
s.accept_waveform(sample_rate, samples_float32)
s.accept_waveform(sample_rate, tail_paddings)
s.input_finished()

hits = []
while kws.is_ready(s):
    kws.decode_stream(s)
    r = kws.get_result(s)
    if r != "":
        hits.append(r)
        kws.reset_stream(s)

print(f"\n✅ 官方测试用例命中结果: {hits}")

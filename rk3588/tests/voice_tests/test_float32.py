import wave
import numpy as np
import sherpa_onnx

model_dir = "~/voice/model"
kws = sherpa_onnx.KeywordSpotter(
    tokens=f"{model_dir}/tokens.txt",
    encoder=f"{model_dir}/encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
    decoder=f"{model_dir}/decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
    joiner=f"{model_dir}/joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
    keywords_file=f"{model_dir}/test_wavs/test_keywords.txt",
    num_threads=2,
    provider="cpu",
)

wave_filename = f"{model_dir}/test_wavs/0.wav"
with wave.open(wave_filename) as f:
    assert f.getnchannels() == 1
    assert f.getsampwidth() == 2
    samples = f.readframes(f.getnframes())
    samples_float32 = np.frombuffer(samples, dtype=np.int16).astype(np.float32) / 32768.0
    sample_rate = f.getframerate()

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

print(f"float32 模型命中结果: {hits}")

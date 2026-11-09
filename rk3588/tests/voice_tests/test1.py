import sounddevice as sd
import numpy as np
import sherpa_onnx
from scipy.signal import resample_poly
import queue
import threading

model_dir = "~/voice/model"
kws = sherpa_onnx.KeywordSpotter(
    tokens=f"{model_dir}/tokens.txt",
    encoder=f"{model_dir}/encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    decoder=f"{model_dir}/decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    joiner=f"{model_dir}/joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
    keywords_file="~/voice/my_keywords.txt",
    num_threads=2,
)
stream = kws.create_stream()

audio_queue = queue.Queue(maxsize=20)

def audio_cb(indata, frames, time, status):
    if status:
        pass
    try:
        audio_queue.put(indata.copy(), block=False)
    except queue.Full:
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            pass
        audio_queue.put(indata.copy(), block=False)

def process_audio():
    global stream
    while True:
        indata = audio_queue.get()
        if indata is None:
            break

        mono = np.mean(indata, axis=1)
        audio_16k = resample_poly(mono, up=1, down=3).astype(np.float32)
        audio_16k = np.clip(audio_16k * 50.0, -1.0, 1.0)

        peak = float(np.max(np.abs(audio_16k)))
        print(f"[sounddevice] 峰值={peak:.4f}", end="\r")

        stream.accept_waveform(16000, audio_16k)
        while kws.is_ready(stream):
            kws.decode_stream(stream)
            result = kws.get_result(stream)
            if result:
                print(f"\n🎉 实时命中: {result}")
                while not audio_queue.empty():
                    try:
                        audio_queue.get_nowait()
                    except queue.Empty:
                        break
                stream = kws.create_stream()
                break

thread = threading.Thread(target=process_audio, daemon=True)
thread.start()

print("开始监听麦克风，请说关键词...")
print("当前词表: ~/voice/my_keywords.txt")
try:
    with sd.InputStream(device=0, channels=2, samplerate=48000,
                        dtype='float32', callback=audio_cb):
        while True:
            sd.sleep(1000)
except KeyboardInterrupt:
    print("\n停止监听...")
    audio_queue.put(None)
    thread.join()

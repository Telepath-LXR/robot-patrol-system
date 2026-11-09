import sherpa_onnx
import soundfile as sf

model_dir = "~/voice/kokoro-v1.1"

config = sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(
        kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=f"{model_dir}/model.int8.onnx",
            voices=f"{model_dir}/voices.bin",
            tokens=f"{model_dir}/tokens.txt",
            # 指向你刚补齐的 espeak-ng-data 目录
            data_dir=f"{model_dir}/espeak-ng-data",
            # 如果仍然需要 dict 目录，可以尝试手动创建并移入相关文件，或者先注释掉这行
            # dict_dir=f"{model_dir}/dict",
            lexicon=f"{model_dir}/lexicon-us-en.txt,{model_dir}/lexicon-zh.txt",
        ),
        num_threads=2,
    ),
    max_num_sentences=1,
)

tts = sherpa_onnx.OfflineTts(config)
text = "你好，我是小A，前进指令已收到。This is a mixed-language test."
audio = tts.generate(text, sid=0, speed=1.0)
sf.write("~/voice/tts_kokoro_output.wav", audio.samples, audio.sample_rate)
print(f"已保存，采样率 {audio.sample_rate} Hz")

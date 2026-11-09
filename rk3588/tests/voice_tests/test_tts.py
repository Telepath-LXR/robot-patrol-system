import sherpa_onnx
import soundfile as sf

model_dir = "~/voice/tts_model"  # 改成你的实际路径

config = sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=f"{model_dir}/model.onnx",
            lexicon=f"{model_dir}/lexicon.txt",
            tokens=f"{model_dir}/tokens.txt",
        ),
        num_threads=2,
    ),
    rule_fsts=f"{model_dir}/date.fst,{model_dir}/phone.fst,{model_dir}/number.fst",
    max_num_sentences=1,
)

tts = sherpa_onnx.OfflineTts(config)
audio = tts.generate("你好，我是小A，前进指令已收到。", sid=0, speed=1.0)
sf.write("~/voice/tts_output.wav", audio.samples, audio.sample_rate)
print("已保存 tts_output.wav，采样率", audio.sample_rate)

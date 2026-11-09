# RK3588 端模型文件清单（约 3.5 GB，不入 Git 库）

以下模型为第三方预训练权重或官方发布物，**体积大且有各自的许可**，请自行下载/转换后放到对应路径。下面列的路径与代码中的实际默认值一一对应（代码里写作 `~/...` 即 RK3588 登录用户的家目录）。

## 1. YOLO11 目标检测（NPU）——`yolo11_rtsp_node.py`

| 文件 | 大小 | 代码默认路径 | 来源 |
|---|---|---|---|
| `yolo11.rknn` | ~4.2 MB | `~/yolo11.rknn` | [airockchip/rknn_model_zoo](https://github.com/airockchip/rknn_model_zoo) |

说明：项目最终使用**官方 COCO 80 类 FP16 多头**版本（9 个输出头，配合 `yolo11_rtsp_node.py` 中手写 NumPy DFL 解码 + 两级阈值 0.1/0.5 + NMS 0.45）。早期自训的 INT8 单头版本因量化异常（score=2.856>1）已废弃，不要从旧备份恢复。`yolo11n_rk3588.rknn`（7.7MB）是实验残留，最终代码不用。

## 2. 语音栈（sherpa-onnx）——`voice/assistant.py`

`pip install sherpa-onnx`（aarch64 有官方 wheel），再从 [k2-fsa/sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases) 下载模型：

| 目录 | 代码默认路径 | 大小 | 用途 |
|---|---|---|---|
| KWS 关键词唤醒（zipformer-wenetspeech-3.3M） | `~/voice/model/`（内含 encoder/decoder/joiner 三个 `*-epoch-12-avg-2-chunk-16-left-64.int8.onnx` + `tokens.txt`） | ~5 MB | 唤醒词检测，词表见 `my_keywords.txt` |
| SenseVoice ASR | `~/voice/sense-voice-onnx/`（`model.int8.onnx` + `tokens.txt`） | ~229 MB | 中粤英日韩多语识别 |
| MeloTTS | `~/voice/vits-melo-tts-zh_en/`（`model.onnx` + `tokens.txt` + `lexicon.txt` + `date.fst`/`number.fst`/`phone.fst`） | ~291 MB | 中文 TTS 合成 |

## 3. 大语言模型（RKLLM）——`voice/flask_server.py` + `voice/rkllm_ctypes.py`

| 文件 | 大小 | 路径 |
|---|---|---|
| `Qwen2.5-1.5B-Instruct_RK3588_w8a8.rkllm` | ~2.0 GB | `~/voice/qwen/RK3588/` |
| `librkllmrt.so`（RKLLM 运行时） | — | `~/voice/rknn-llm/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so` |

获取方式：
1. clone [airockchip/rknn-llm](https://github.com/airockchip/rknn-llm) SDK 到 `~/voice/rknn-llm/`（内含 `rkllm-runtime`、`rkllm-toolkit`、`rknpu-driver`）
2. 用 `rkllm-toolkit` 把 HuggingFace 的 `Qwen/Qwen2.5-1.5B-Instruct` 转换为 RK3588 w8a8 量化的 `.rkllm`
3. 本仓库的 `flask_server.py` 是基于该 SDK 自带 demo 修改的（增加项目所需接口），直接放到 `~/voice/` 下运行即可提供本地 LLM HTTP 服务（`assistant.py` 以 `model: "qwen"` 调用）

## 4. 已废弃 / 不需要下载

- `melotts-modelscope`（747MB）、`kokoro-*`（20MB）、`tts_model`（117MB）——TTS 最终统一到 vits-melo-tts-zh_en，历史模型不再需要
- `~/voice/sense-voice/`（非 onnx 目录）——历史版本
- 自训 YOLO11n INT8——量化翻车废弃（见项目总结第 7 章）

## 5. 检查清单

下载齐全后，RK 端应有：

```
~/yolo11.rknn                                        # YOLO FP16 多头
~/voice/model/{encoder,decoder,joiner}-*.int8.onnx   # KWS
~/voice/model/tokens.txt
~/voice/sense-voice-onnx/{model.int8.onnx,tokens.txt}   # ASR
~/voice/vits-melo-tts-zh_en/{model.onnx,tokens.txt,lexicon.txt,*.fst}  # TTS
~/voice/qwen/RK3588/Qwen2.5-1.5B-Instruct_RK3588_w8a8.rkllm            # LLM
~/voice/rknn-llm/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so
```

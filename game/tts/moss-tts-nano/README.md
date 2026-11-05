# MOSS-TTS-Nano runtime

本目录是语音组件 `tts_moss_nano` 使用的 MOSS-TTS-Nano 推理 runtime，在 SpacemiT EP 上运行。
它只提供推理代码和模型目录，不是独立的命令行工具，也不直接播放音频。
组件的使用、配置和管理见 [tts_moss_nano 语音组件](../../backend/components/tts_moss_nano/README.md)。

## 目录内容

| 路径 | 内容 | 来源 |
| --- | --- | --- |
| `src/` | 推理代码 `OnnxTtsRuntime` 与文本规范化 | 随源码提供 |
| `models/MOSS-TTS-Nano-100M-ONNX-xslim-dynq/` | 语音生成模型 | 由 `python3 tools/download_assets.py` 下载，目录中的清单文件随源码提供 |
| `models/MOSS-Audio-Tokenizer-Nano-ONNX/` | 音频编解码模型 | 同上 |
| `voice/`、`assets/` | 参考音频 | 由 `python3 tools/download_assets.py` 下载 |
| `licenses/` | MOSS-TTS-Nano 与 SpacemiT EP 的许可 | 随源码提供 |
| `SHA256SUMS` | 模型文件摘要 | 随源码提供 |

- 运行依赖 `python3-spacemit-ort`、`spacemit-onnxruntime`、`python3-sentencepiece` 和 `python3-soundfile`，由 `mm` 按 `package.xml` 提示安装。
- 由 `dice-arena` 启动时，合成输出写入 `SITE/dice_arena/moss-tts-outputs/`，不写入安装目录。

## 管理命令

在 SDK 根目录执行 `source build/envsetup.sh` 后：

```bash
dice-arena component start tts_moss_nano
dice-arena component health tts_moss_nano
dice-arena component stop tts_moss_nano
```

`dice-arena serve` 启动游戏前会自动启动语音服务，通常无需手动执行 `start`。

## 配置

运行参数只来自 `game/backend/components/tts_moss_nano/config.json`，字段说明见 [tts_moss_nano 参数](../../backend/components/tts_moss_nano/parameters.md)：

- `runtime.root` 相对 `game/`，`runtime.model_dir` 相对 `runtime.root`；
- `voice.mode` 为 `builtin` 或 `clone`，`clone` 模式需要 `voice.reference_audio`；
- `generation`、`startup`、`limits` 和 `execution_provider` 控制生成、启动和 EP 线程。

使用限制：

- 只支持 `speed=1.0`。
- 游戏使用的语音组件由游戏 manifest 和全局配置决定，网页请求不能更改。
- 更换模型变体见 [MODEL_VARIANTS.md](MODEL_VARIANTS.md)。

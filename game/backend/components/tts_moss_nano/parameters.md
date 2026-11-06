# tts_moss_nano 参数

`game/backend/components/tts_moss_nano/config.json` 配置本地 MOSS-TTS-Nano 语音服务。组件说明见 [README](README.md)。

## 生效方式

- 在源码中修改后，在应用目录执行 `mm`，安装到 `share/dice_arena/game/backend/components/tts_moss_nano/config.json`。
- 语音服务在 `dice-arena serve` 退出后保留，供下次启动复用；因此修改后须先停止语音服务，再重新启动 `dice-arena serve`，步骤见 [README](README.md) 的「修改配置后重启」。

## runtime（本地服务）

| 字段 | 当前值 | 说明 |
| --- | --- | --- |
| `kind` | `local` | 本地服务，由组件生命周期命令启停 |
| `root` | `tts/moss-tts-nano` | MOSS runtime 目录，相对 `game/`；模型与参考音频由 `python3 tools/download_assets.py` 下载，`mm` 安装 |
| `model_dir` | `models/MOSS-TTS-Nano-100M-ONNX-xslim-dynq` | 模型目录，相对 `root`，须含 `browser_poc_manifest.json`；留空时自动查找 |
| `host` | `127.0.0.1` | 服务监听地址，只允许回环地址 |
| `port` | `18082` | 服务端口；`dice-arena serve` 按该端口检查占用并复用语音服务。修改时须同步修改 `base_url` |
| `base_url` | `http://127.0.0.1:18082` | 后端访问服务的地址，只允许 `http://` 回环地址 |

## voice（音色）

| 字段 | 当前值 | 说明 |
| --- | --- | --- |
| `mode` | `clone` | `clone` 启动时加载参考音频并以其音色合成；`builtin` 使用内置音色，忽略参考音频 |
| `name` | `Junhao` | 音色名；台词的 `voice` 只能为 `default` 或该值 |
| `reference_audio` | `voice/warm.wav` | 参考音频，相对 `root`；`clone` 模式必填，可选用 `game/tts/moss-tts-nano/voice/` 下的 WAV |

## generation（生成）

| 字段 | 当前值 | 说明 |
| --- | --- | --- |
| `max_new_frames` | `120` | 单次生成的最大语音帧数 |
| `voice_clone_max_text_tokens` | `24` | 单个分块的文本 token 上限；启动时按模型容量下调 |
| `first_chunk_text_tokens` | `16` | 流式合成首个分块的文本 token 数，越小首段音频越早返回 |
| `seed` | `1234` | 随机种子，固定后同一文本合成结果稳定 |

## startup、limits（启动与请求）

| 字段 | 当前值 | 说明 |
| --- | --- | --- |
| `startup.warmup_text` | `你好。` | 启动时的预热合成文本，预热完成后服务才就绪 |
| `startup.start_timeout_seconds` | `300` | 等待服务就绪的最长时间，超时则停止启动中的进程 |
| `limits.request_timeout_seconds` | `120` | 单次合成请求超时 |

## execution_provider（SpacemiT EP）

| 字段 | 当前值 | 说明 |
| --- | --- | --- |
| `intra_thread_num` | `4` | EP intra 线程数 |
| `inter_thread_num` | `1` | EP inter 线程数 |
| `intra_thread_affinity` | `8;9;10;11` | intra 线程绑定的核，分号分隔 |
| `disable_op_type_filter` | `""` | 不交给 EP 执行的算子类型，空字符串表示不限制 |
| `process_affinity` | `8;9;10;11` | 服务就绪前，把绑定在该核集合之外的 EP 线程移入该集合；空字符串表示不调整。识别进程使用 14、15 核 |

进程环境中已设置 `SPACEMIT_EP_INTRA_THREAD_NUM`、`SPACEMIT_EP_INTER_THREAD_NUM`、`SPACEMIT_EP_INTRA_THREAD_AFFINITY` 或 `SPACEMIT_EP_DISABLE_OP_TYPE_FILTER` 时，以环境变量为准。

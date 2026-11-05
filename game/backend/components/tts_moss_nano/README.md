# tts_moss_nano 语音组件

本组件为 Dice Arena 提供本地语音合成，在 SpacemiT EP 上运行 `game/tts/moss-tts-nano/` 中的 MOSS-TTS-Nano runtime。
后端经本机 HTTP 服务（默认 `127.0.0.1:18082`）合成台词，按文本分块以流式方式返回 WAV 帧。
参数见 [tts_moss_nano 参数](parameters.md)，runtime 说明见 [MOSS-TTS-Nano runtime](../../../tts/moss-tts-nano/README.md)。

## 文件

| 文件 | 作用 |
| --- | --- |
| `manifest.json` | 组件声明与生命周期命令 |
| `config.json` | 组件参数 |
| `settings.py` | 参数解析与校验 |
| `provider.py` | 后端使用的语音组件入口 |
| `daemon.py` | 本机 HTTP 语音服务 |
| `launcher.py` | 启动、停止语音服务 |
| `scripts/start_tts.sh`、`scripts/stop_tts.sh` | 生命周期命令，调用 `launcher.py start`、`launcher.py stop` |

## 运行方式

- 全局配置 `providers.tts_local` 为 `tts_moss_nano` 时使用本组件（默认）。
- `dice-arena serve` 启动游戏前执行 `scripts/start_tts.sh`：启动语音服务，等待模型加载与预热完成，最长 `startup.start_timeout_seconds`。启动失败时输出 `warning: TTS provider tts_moss_nano is unavailable`，游戏照常运行但无法播报合成台词。
- 语音服务独立于游戏进程。Ctrl+C 停止游戏后语音服务保留，下次 `dice-arena serve` 直接复用；服务端口（默认 18082）被其他安装的语音服务占用时，`dice-arena serve` 拒绝启动。
- 运行文件位于 `SITE/dice_arena/`（`SITE` 默认为 `~/.local/share/spacemit-manipulation/site/`）：

| 文件 | 内容 |
| --- | --- |
| `moss-tts-<端口>.pid` | 语音服务进程号，默认端口时为 `moss-tts-18082.pid` |
| `moss-tts-<端口>.log` | 语音服务日志，默认端口时为 `moss-tts-18082.log` |
| `moss-tts-outputs/` | runtime 输出目录 |

## 限制

- 仅支持 `speed=1.0`，其他语速的合成请求被拒绝。
- 台词的 `voice` 只能为 `default` 或 `voice.name`；更换音色或参考音频须修改配置并重启语音服务。
- 服务串行处理请求，同一时间只合成一条台词。
- 按文本分块流式输出，每个分块生成后发送一帧 WAV。

## 修改配置后重启

从 SDK 根目录执行 `source build/envsetup.sh` 后：

```bash
cd application/native/dice_arena
mm
```

在运行 `dice-arena serve` 的终端按 Ctrl+C 停止游戏，然后停止语音服务并重新启动游戏：

```bash
dice-arena component stop tts_moss_nano
dice-arena serve
```

- 停止成功时输出 `MOSS-TTS bridge stopped: pid=...`；服务未运行时输出 `MOSS-TTS bridge is not running`。
- `dice-arena serve` 按新配置启动语音服务，启动进度输出到终端，详细日志见 `moss-tts-18082.log`。

## 状态检查

```bash
curl -s http://127.0.0.1:18082/health
dice-arena component health tts_moss_nano
tail -f ~/.local/share/spacemit-manipulation/site/dice_arena/moss-tts-18082.log
```

`/health` 返回 `"ready": true` 表示服务已就绪；启动中返回当前阶段 `startup_phase`，失败时返回 `error`。

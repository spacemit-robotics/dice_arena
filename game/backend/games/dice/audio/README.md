# 摇骰子游戏音频

本目录存放预录的 WAV 台词，由 `mm` 随游戏安装。音频文件由 `python3 tools/download_assets.py` 下载，不随源码提供。

在 `../manifest.json` 中以 `audio` 模式引用，路径相对 `game/backend/games/dice/`：

```json
{
  "action": "speech",
  "mode": "audio",
  "audio": "audio/停.wav",
  "text": "停！"
}
```

- 只支持未压缩的 PCM WAV。
- 路径须位于 `game/backend/games/dice/` 内，不能使用绝对路径或 `..`。
- `text` 为网页显示的文字。

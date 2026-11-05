# MOSS 模型变体

语音组件只读取 `game/backend/components/tts_moss_nano/config.json` 中 `runtime.model_dir` 指定的模型目录。
切换动态 KV 或固定 KV 模型时，把 `runtime.model_dir` 改为兼容当前 runtime 的模型目录，然后重启语音服务：

```bash
dice-arena component stop tts_moss_nano
dice-arena serve
```

- 模型目录必须包含 `browser_poc_manifest.json`，并与当前 `OnnxTtsRuntime` 接口和 SpacemiT EP 版本匹配。
- 不需要修改游戏后端或网页代码。
- 切换后，在 K3 上执行 `dice-arena component health tts_moss_nano`，再播放一句短台词，确认采样率、声道数与网页播放一致。

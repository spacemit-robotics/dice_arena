# 绿杯分割模型

`best_green.q.onnx` 是抓杯定位使用的绿杯分割模型，不用于骰子点数识别。

- **获取**：不随源码提供，在应用目录执行 `python3 tools/download_assets.py` 下载并校验。
- **SHA-256**：`66ab24e84bf97ce8ce01bf4118fc7ba03ab3839cc4a7ca910b7f2eb9eb74a34d`，与 `runtime_assets.json` 一致。
- **输入**：`[1, 3, 640, 640]`。
- **输出**：`[1, 38, 8400]` 和 `[1, 32, 160, 160]`。
- **类别**：`cap=0`、`ground=1`。

推理后端、置信度和几何质量检查由 `configs/green_cup.json` 配置。
更换模型后，须重新启动 `dice-arena cycle` 或 `dice-arena serve`，并在现场验证杯沿定位和抓取。

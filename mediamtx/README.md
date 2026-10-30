# mediamtx

网页实时视频的转发服务：骰子识别程序以 RTSP（8554）推流，浏览器以 WebRTC（8889，UDP 8189）播放。
由 `dice-arena serve` 启动，运行时文件（日志、自动生成的证书）在 `SITE/dice_arena/`。

- 程序：MediaMTX v1.20.1 官方 riscv64 发布版（https://github.com/bluenviron/mediamtx），MIT 许可，见 [LICENSE](LICENSE)。
- 配置：`mediamtx.yml` 为该版本默认配置，只关闭了游戏用不到的 RTMP、HLS、SRT 和 MoQ。

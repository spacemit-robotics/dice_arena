# YOLOv8 骰子识别程序

`yolov8_camera` 是视觉裁决组件 `vision_yolov8_objdetect` 使用的识别程序，负责摄像头采集、OpenCL 预处理、SpaceMIT EP 上的 YOLOv8 推理、稳定观测、稳定帧快照和 RTSP 推流。
分组、数量校验、胜负规则和失败诊断由 Python 组件完成。参数见 [vision_yolov8_objdetect 参数](../../backend/components/vision_yolov8_objdetect/parameters.md)，游戏侧参数见 [摇骰子游戏参数](../../backend/games/dice/parameters.md)。

## 数据流

```text
USB 摄像头（MJPEG）
  -> GStreamer 解码（优先硬件解码 spacemitdec，失败时回退 jpegdec）
  -> NV12 最新帧队列
  -> OpenCL：NV12 转 RGB、缩放、letterbox、归一化
  -> SpaceMIT ONNX Runtime EP 推理
  -> 检测事件、稳定观测与快照
  -> H.264 编码（优先 spacemith264enc，失败时回退 x264enc）
  -> RTSP 推送到 MediaMTX -> 浏览器 WebRTC 播放
```

## 构建与安装

识别程序随应用由 `mm` 在 K3 上构建。从 SDK 根目录执行 `source build/envsetup.sh` 后：

```bash
cd application/native/dice_arena
mm
ls "$PREFIX/share/dice_arena/game/vision/yolov8_objdetect/bin/yolov8_camera"
```

- 依赖 OpenCV（存在时使用 `/opt/opencv-spacemit/lib/cmake/opencv4`）、OpenCL、GStreamer（`gstreamer-1.0`、`gstreamer-video-1.0`、`gstreamer-app-1.0`）和 SpaceMIT ONNX Runtime 与 EP 开发文件。
- 未找到 `spacemit_ort_env.h` 时 CMake 输出 `dice recognition not built: SpacemiT ONNX Runtime development files not found`，不构建识别程序，`dice-arena serve` 拒绝启动。
- 安装位置为 `share/dice_arena/game/vision/yolov8_objdetect/bin/yolov8_camera`；`$PREFIX` 为安装目录，`source build/envsetup.sh` 后为 SDK 的 `output/staging`。

## 游戏中的启动方式

进入游戏时组件以预热模式启动识别程序，工作目录为 `SITE/dice_arena/vision/`（`SITE` 默认 `~/.local/share/spacemit-manipulation/site/`）。单机位时命令行为：

```text
share/dice_arena/game/vision/yolov8_objdetect/bin/yolov8_camera \
  --config share/dice_arena/game/backend/games/dice/adjudicator_config.json \
  --no-display --control-fd <控制管道> --event-fd <事件管道> --view-id default \
  --device /dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_<序列号>-video-index0 \
  --rtsp --rtsp-host 127.0.0.1 --rtsp-port 8554 --rtsp-path /dice/det \
  --prewarm --snapshot-dir /tmp/vision-runtime-default-<随机后缀>
```

- `--config` 取游戏 manifest 的 `vision_profile.runtime_config`。
- 配置中的 `camera` 含通配符时，组件将其解析为唯一的设备路径并通过 `--device` 传入；识别程序本身只打开确定的路径或序号。
- `--rtsp-path` 取游戏 manifest 的 `video.path`。
- 多机位时组件为每个机位启动一个进程，以 `--view-id` 区分，摄像头与推流路径取各机位配置。
- 控制管道关闭（服务退出）时识别程序随之退出。标准输出与标准错误仅为诊断日志，转发到服务输出。

## 控制与事件协议

控制管道与事件管道均为独立的 UTF-8 JSONL 文件描述符。组件发送的命令：

| 命令 | 作用 |
| --- | --- |
| `{"command":"START_ADJUDICATION","request_id":"...","profile_id":"dice"}` | 开始推理并重新计数 |
| `{"command":"STOP_ADJUDICATION","request_id":"..."}` | 停止推理，保持摄像头和推流 |
| `{"command":"FINAL_RESULT","request_id":"...","outcome":{"kind":"winner","value":"LEFT"},"source":"yolo_only","decision_source":"yolo_only"}` | 写入最终结果并停止推理 |
| `{"command":"CANCEL","request_id":"..."}` | 取消本次裁决 |

识别程序输出的事件：

| 事件 | 说明 |
| --- | --- |
| `started` | 启动，声明 `"protocol":"jsonl-events-v2"`；协议不符时回合以错误结束 |
| `phase` | `idle`（预热待命）或 `detecting`（推理中） |
| `ready` | 摄像头与推流就绪，含 `view_id` |
| `video` | 内部 RTSP 地址，如 `rtsp://127.0.0.1:8554/dice/det`；组件改写为网页 WebRTC 地址后再发给网页 |
| `progress` | 推理中连续计数变化时发送，含 `stable_count` 与 `stable_frames` |
| `diagnostic_snapshot` | 推理中每 250 ms 发送一次的最新画面与检测结果，`stable` 为 `false`，用于失败诊断 |
| `observation` | 稳定观测，`stable` 为 `true`，含 `detections`、`divider`、画面尺寸与快照路径 |
| `result` | 收到 `FINAL_RESULT` 后回显结果 |
| `cancelled` | 收到 `CANCEL` |

检测项格式为 `{"class_id":0,"label":"class_0","confidence":0.92,"bbox":[x1,y1,x2,y2]}`；`divider` 含 `found`、`horizontal`、`point`、`direction`、`normal`。

## 稳定观测

推理中每一帧须同时满足以下条件才计入连续计数，否则计数清零：

1. 开启 `divider_detection` 时，该帧检出分界线。
2. 至少检出一个目标，且类别组成与上一帧相同。

连续计数达到 `stable_frames` 时发布一次 `observation`，`stable_count` 不会超过 `stable_frames`。
每侧骰子数量由组件在稳定观测上校验，识别程序不检查。

## 分界线检测

- 按 `divider_colors` 识别桌布分区：`green_gray` 按色相区分绿色 `#B0E237` 与灰色 `#666666`，`red_blue` 按红蓝通道差区分。左右两侧颜色顺序不限，也可识别水平分界。
- 配色识别失败时，回退识别中央区域的深色竖线。
- 两者均失败时 `divider.found` 为 `false`，该帧不计入稳定计数。
- 检出位置随观测发送，组件以此作为左右分组的切分点。

## 视频与 MediaMTX

- MediaMTX 由 `dice-arena serve` 启动，配置为 `mediamtx/mediamtx.yml`，见 [MediaMTX 说明](../../../mediamtx/README.md)。识别程序以 RTSP 推流到 8554 端口，浏览器经 WebRTC（TCP 8889、UDP 8189）播放。
- 网页地址为全局配置 `video.webrtc_base_url` 加 `video.path`，默认 `http://<K3 地址>:8889/dice/det`；网页不使用识别程序事件中的 RTSP 地址。
- MediaMTX 的 HTTP API 未启用。推流状态查看日志 `SITE/dice_arena/mediamtx.log`，推流成功时出现 `is publishing to path 'dice/det'`；也可在浏览器直接打开上述网页地址。
- 检查 GStreamer 推流与编解码组件：

```bash
gst-inspect-1.0 rtspclientsink
gst-inspect-1.0 spacemith264enc
gst-inspect-1.0 spacemitdec
```

## 诊断

诊断命令直接访问摄像头，执行前先停止 `dice-arena serve`。以下命令在任意可写目录执行（OpenCL 缓存写入当前目录）：

```bash
GAME="$PREFIX/share/dice_arena/game"
CAMERA="$GAME/vision/yolov8_objdetect/bin/yolov8_camera"
CONFIG="$GAME/backend/games/dice/adjudicator_config.json"
DEVICE="$(ls /dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_*-video-index0)"

"$CAMERA" --help
"$CAMERA" --config "$CONFIG" --yolov8 --self-test --no-display --no-rtsp
"$CAMERA" --config "$CONFIG" --device "$DEVICE" --no-yolov8 --no-display --no-rtsp --max-frames 30
"$CAMERA" --config "$CONFIG" --device "$DEVICE" --yolov8 --no-display --no-rtsp --max-frames 30
"$CAMERA" --config "$CONFIG" --image frame.jpg
```

| 命令 | 验证内容 |
| --- | --- |
| `--yolov8 --self-test` | 不打开摄像头，用合成画面验证 OpenCL 预处理与 EP 推理，成功输出 `Self-test passed` |
| `--no-yolov8 --max-frames 30` | 只验证摄像头采集，输出采集帧数与帧率 |
| `--yolov8 --max-frames 30` | 验证采集与推理链路，输出处理帧数与耗时统计 |
| `--image frame.jpg` | 不打开摄像头，对单张图片做分界线检测并输出 JSON，检出时退出码为 0，否则为 1 |

命令行参数覆盖配置文件中的同名项。退出码：

| 退出码 | 含义 |
| --- | --- |
| `2` | 参数、配置文件或模型错误 |
| `3` | 摄像头打开失败 |
| `4` | OpenCL 初始化失败 |
| `5` | 模型或 EP 初始化失败 |
| `6` | 自检失败 |
| `7` | 显示窗口初始化失败 |
| `8` | RTSP 推流启动失败 |

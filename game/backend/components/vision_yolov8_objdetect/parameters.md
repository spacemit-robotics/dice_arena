# vision_yolov8_objdetect 参数

视觉裁决组件启动 YOLOv8 识别进程，读取稳定观测后按游戏规则判定胜负。参数分布在两个文件中：

| 文件 | 内容 | 生效方式 |
| --- | --- | --- |
| `game/backend/components/vision_yolov8_objdetect/config.json` | 识别程序路径与进程模式 | `mm` 安装后重启 `dice-arena serve` |
| `game/backend/games/dice/adjudicator_config.json` | 模型、检测参数、摄像头与推流 | `mm` 安装后，下一次进入游戏或下一次裁决时重建识别进程 |

类别映射、每侧数量、分组方式、胜负规则、视频路径和超时属于游戏 manifest 的 `vision_profile`，见 [摇骰子游戏参数](../../games/dice/parameters.md)。
识别程序的命令行、协议和诊断方法见 [YOLOv8 骰子识别程序](../../../vision/yolov8_objdetect/README.md)。

## 组件配置

`game/backend/components/vision_yolov8_objdetect/config.json`：

| 字段 | 当前值 | 说明 |
| --- | --- | --- |
| `schema_version` | `1` | 固定为 `1` |
| `runtime.binary` | `vision/yolov8_objdetect/bin/yolov8_camera` | 识别程序，相对 `game/`；`mm` 在 K3 上编译安装，缺失时 `dice-arena serve` 拒绝启动 |
| `runtime.working_dir` | `vision/yolov8_objdetect` | 不经 `dice-arena` 运行时的进程工作目录；由 `dice-arena serve` 运行时为 `SITE/dice_arena/vision/`。OpenCL 缓存写在工作目录 |
| `runtime.mode` | `resident` | `resident` 与 `prewarm_camera: true` 同时设置时，识别进程跨回合常驻复用；`per_request` 时每次裁决结束后停止 |
| `runtime.prewarm_camera` | `true` | 常驻模式下保持摄像头与推流 |
| `runtime.terminate_grace_seconds` | `5` | 代码不读取；停止识别进程时先发送 SIGTERM，2 秒未退出则强制结束 |
| `events.protocol` | `jsonl-events-v2` | 代码不读取；事件协议固定为 `jsonl-events-v2`，识别程序声明的协议不符时回合以错误结束 |

`SITE` 表示现场目录，默认 `~/.local/share/spacemit-manipulation/site/`。

## 识别进程配置

`game/backend/games/dice/adjudicator_config.json` 由识别程序通过 `--config` 读取。文件整体生效，不与其他配置合并；未写的键使用识别程序内置值。

| 字段 | 当前值 | 未写时 | 说明 |
| --- | --- | --- | --- |
| `_note` | 说明文字 | — | 注释，不参与运行 |
| `model` | `models/best.q.onnx` | `models/best.q.onnx` | 模型路径，相对本文件所在目录，即 `game/backend/games/dice/models/best.q.onnx`，由 `python3 tools/download_assets.py` 下载 |
| `conf` | `0.3` | `0.5` | 检测置信度阈值，范围 0～1 |
| `stable_frames` | `30` | `20` | 连续有效帧达到该数量时发布稳定观测 |
| `divider_detection` | `true` | `false` | 检测桌面分界线；开启时只有检出分界线的帧计入稳定帧，检出位置用作左右切分点 |
| `divider_colors` | `green_gray` | `red_blue` | 分界检测配色：`green_gray` 识别绿色 `#B0E237` 与灰色 `#666666` 桌布分区，`red_blue` 识别红蓝分区；配色识别失败时回退为深色分界线识别。只影响分界检测，不改变玩家归属与显示方向 |
| `camera` | `/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_*-video-index0` | 序号 `1` | 摄像头设备路径或 V4L2 序号。路径可含 `*`、`?`、`[]`，启动时须恰好匹配一个设备 |
| `device` | `""` | — | 非空时代替 `camera` |
| `width`、`height`、`fps` | `1280`、`720`、`24` | `1280`、`720`、`25` | MJPEG 采集模式，须为相机支持的模式 |
| `focus`、`zoom` | `-1`、`180` | `0`、`150` | UVC 对焦与变焦值，`-1` 表示不设置；设置对焦时同时关闭自动对焦。控制设置失败时摄像头打开失败，相机不支持的控制须设为 `-1` |
| `show_debug_text` | `false` | `true` | 在推流画面上叠加调试文字 |
| `intra_threads` | `2` | `2` | SpacemiT EP 推理线程数 |
| `ep_affinity` | `14;15` | `14;15` | EP 推理线程绑定的核，分号分隔，核数须等于 `intra_threads` |
| `queue_depth` | `2` | `2` | 帧队列深度，限制在 1～8 |
| `rtsp.enabled` | `true` | `false` | 向 MediaMTX 推送 H.264 |
| `rtsp.host`、`rtsp.port` | `127.0.0.1`、`8554` | `0.0.0.0`、`8554` | MediaMTX 的 RTSP 地址；推流路径取游戏 manifest 的 `video.path`（`/dice/det`） |

其他可用键：

- `video.webrtc_base_url`：网页 WebRTC 地址，仅在游戏 manifest 与全局配置均未设置时使用。
- `display_enabled`、`yolov8_enabled`、`self_test`、`max_frames`、`dump_input`：诊断运行使用；游戏启动时识别程序总是无窗口运行，并由组件控制推理。

写入其他键不影响运行，服务输出 `[vision] runtime config ...: unknown keys are ignored by the C++ runtime: ...`。

## 运行行为

- 进入游戏时以预热模式启动识别进程：打开摄像头并推流、加载模型，不推理；`analysis` 状态开始裁决后才推理。
- 一帧计入连续计数须同时满足：开启 `divider_detection` 时检出分界线；至少检出一个目标，且类别组成与上一帧相同。不满足时计数清零。
- 连续计数达到 `stable_frames` 后发布稳定观测。组件按检出的分界线把骰子分到左右两侧，任一侧数量不等于 `vision.expected_count` 时生成失败诊断。
- 在 `timeouts.yolo_detection_seconds` 内未得到稳定观测时，组件按最近一帧的检测结果生成失败诊断。
- 修改采集参数后，按 [YOLOv8 骰子识别程序](../../../vision/yolov8_objdetect/README.md) 的「诊断」一节在 K3 上验证。

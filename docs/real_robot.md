# 游戏服务与排障

应用、运行资源和现场配置须已安装。以下命令从 SDK 根目录开始：

```bash
source build/envsetup.sh
cd application/native/dice_arena
```

`SITE` 默认为 `~/.local/share/spacemit-manipulation/site/`。

## 1. 服务管理

游戏会控制真机。机械臂须未持物并位于 HOME、手部张开，装好骰子的杯子位于视觉工作区。
退出其他设备控制程序；现场须有人看护，急停按钮伸手可及。

```bash
dice-arena serve
```

- 服务依次启动视频转发、本地语音和游戏，网页地址为 `http://<主机地址>:8080/`。
- 仅允许本机访问时，使用 `dice-arena serve --host 127.0.0.1`。
- 按 Ctrl+C 停止游戏和视频服务，语音服务保留，供下次启动复用。
- 首次启动时生成 `SITE/dice_arena/config.json`；修改后自动重载，重新安装不覆盖。
- 机械臂获胜时做 V 手势，失败时做竖拇指手势，平局时做开合手势；每局正常结束后返回 HOME 并张开手部。
- 故障后应用不会自动归位或恢复。现场操作人员处理持物和设备后，执行 `dice-arena reset`，再重新启动游戏。

| 服务 | 默认端口 |
| --- | --- |
| 游戏网页 | TCP 8080 |
| 标定网页 | TCP 8091 |
| 本地语音 | TCP 18082 |
| 视频 RTSP / WebRTC 信令 | TCP 8554 / 8889 |
| WebRTC 媒体 | UDP 8189 |

## 2. 状态与持物确认

在另一终端从 SDK 根目录执行 `source build/envsetup.sh`，再查询服务：

```bash
dice-arena status
```

输出机械臂、语音和识别服务的状态。

开启 `grip_confirmation: operator` 时，按以下步骤确认持物：

1. 从 `dice-arena status` 输出的 `active_round.id` 取得本局标识 `ROUND_ID`。
2. 执行 `dice-arena events ROUND_ID` 读取本局事件。
3. 收到 `phase=await_grip_confirmation` 后，现场确认实际持杯，再执行 `dice-arena ack-grip TOKEN OUTPUT`；两个参数分别取本次事件的 `token` 和 `acknowledgement`。

## 3. 组件管理

`dice-arena component` 按现场配置管理游戏组件，常用命令：

```bash
dice-arena component list                    # 已注册组件及其健康状态
dice-arena component health tts_moss_nano    # 单个组件的健康状态
dice-arena component stop tts_moss_nano      # 停止保留的语音服务
```

组件的完整命令见 [组件包说明](../game/backend/components/README.md)。

## 4. 离线检查

以下命令不连接机械臂、相机或音频设备：

```bash
dice-arena mock
dice-arena check
manipulation check --profile vision
python3 tools/check_assets.py --verify
```

- `mock`：用 Mock 设备执行一次抓杯、摇杯和放杯；
- `check`：检查游戏使用的机械臂接口；
- `manipulation check --profile vision`：检查视觉依赖；
- `check_assets.py --verify`：校验运行资源的 SHA-256。

## 5. 常见问题

| 现象 | 处理 |
| --- | --- |
| 设备连接失败 | 用 `ip -details link show can0` 查看接口；配置要求 1 Mbps，机械臂须按设备规程供电、使能并进入位置控制模式 |
| 提示设备被占用 | 退出厂商 Web、遥操作、标定及其他控制程序；不要删除锁文件或接管运动中的设备 |
| 端口被占用 | 停止占用端口的游戏、视频或其他安装的语音服务；本应用保留的语音服务会被复用 |
| 缺少 `pyrealsense2` | 安装与主机架构、Python 版本匹配的 RealSense Python 绑定 |
| 缺少模型或视频程序 | 执行 `python3 tools/download_assets.py`，再执行 `mm --with-deps` |
| 桌面记录缺失或外参不匹配 | 退出游戏，在应用目录执行 `bash calibrate.sh table` 重新采集并登记 |
| 任务故障或取消 | 停止游戏，由现场操作人员处理持物和姿态，再执行 `dice-arena reset`；应用不会自动重试、张开手部或归位 |

视频服务日志位于 `SITE/dice_arena/mediamtx.log`。

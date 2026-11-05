# Dice Arena 骰子游戏

提供视觉抓杯、摇杯放杯、手眼标定、骰子识别、语音播报和网页游戏。

## 硬件准备

| 设备 | 型号或规格 | 连接与用途 |
| --- | --- | --- |
| 主控 | SpacemiT K3 开发板 | 运行 SDK、视觉规划、骰子识别、语音与游戏网页 |
| 机械臂 | 松灵 Nero 七轴机械臂 | 固定基座，通过 USB-CAN 适配器连接 K3，执行抓杯、摇杯与放杯 |
| 末端执行器 | Revo2 右手灵巧手，六个控制通道 | 安装在机械臂末端，经机械臂末端口接入，与机械臂共用控制器连接 |
| CAN 适配器 | 支持 SocketCAN 的 USB-CAN 适配器 | USB 连接 K3，CAN 连接机械臂，通信速率 1 Mbps |
| 抓杯与标定相机 | Intel RealSense D435i | USB 连接 K3，固定安装在机械臂外，用于杯体定位与手眼标定 |
| 骰子相机 | 支持 MJPEG 的 USB 相机，默认并已验证 Logitech C920 | USB 连接 K3，从上方拍摄双方杯内骰子，用于点数识别 |
| 标定板 | ChArUco 末端标定板与固定参考板各一块 | 分别固定在末端与桌面，尺寸、字典和格数与标定配置一致 |
| 音频输出 | 音箱，型号不限 | 接入 K3 的系统音频输出，用于规则讲解与结果播报 |
| 游戏道具 | 绿色杯子与骰子 | 杯体尺寸与抓杯配置一致，放置于相机可见的桌面工作区 |

随附的视觉规划、自动标定与手型参数适用于上述设备组合。
更换机械臂或末端需要适配驱动、规划、标定和手型，不能只替换设备配置。

## 安装

需要 Linux、C++17 编译器、CMake 3.16+、Python 3.10+，以及网络和系统依赖安装权限。
深度相机采集另需与主机架构、Python 版本匹配的 `pyrealsense2`。
从 SDK 根目录开始，在同一终端依次执行：

```bash
source build/envsetup.sh
bash components/thirdparty/pyagxarm/tools/setup_sdk.sh
cd application/native/dice_arena
```

后续命令均在应用目录执行。新终端须先在 SDK 根目录执行 `source build/envsetup.sh`。

## 运行资源

下载模型、设备网格、音频、默认标定示教数据和视频服务程序，然后构建安装应用：

```bash
python3 tools/download_assets.py
mm --with-deps
```

资源源站为 `https://archive.spacemit.com/ros2/manipulation/`，本应用的资源位于其中的 `dice_arena/` 目录。
清单 `runtime_assets.json` 记录每个文件的源站路径、本地路径、大小和 SHA-256，下载时逐个校验。
使用内网镜像时追加 `--base-url <镜像地址>`，镜像地址对应源站根目录 `https://archive.spacemit.com/ros2/manipulation/`，其下保持相同的 `dice_arena/` 目录结构；已下载的资源可用 `python3 tools/check_assets.py --verify` 复核。
`mm` 提示安装声明的系统依赖。骰子识别程序在 K3 上编译；随附 MediaMTX 适用于 Linux RISC-V 64 位。

## 配置设备

下文 `SITE` 表示现场目录，默认 `~/.local/share/spacemit-manipulation/site/`。
为随附的机械臂与灵巧手组合生成设备配置：

```bash
manipulation configure nero --variant revo2_right
```

配置保存到 `SITE/nero/device.yaml`，包含驱动、连接参数、关节限位和末端通道；已有文件不覆盖。
`configure` 同时把 Nero 设为当前设备。这台主机还配置过其他设备时，标定和生成抓杯配置前先执行
`manipulation use nero`；`dice-arena configure` 记录 Nero 的配置路径，之后的抓杯和游戏不受切换影响。

退出厂商 Web、遥操及其他控制程序，按实际接口名启用 CAN。随附配置使用 `can0`、1 Mbps：

```bash
sudo ip link set can0 up type can bitrate 1000000
```

机械臂按设备规程使能并进入位置控制模式；应用不自动使能或清错。
现场须有人看护、急停可达，工作区无人且无障碍。Nero 断电会坍塌，不用断电或失能代替软件停止。

## 手眼标定

固定相机、机械臂基座和两块标定板。在 `calibration/config/calibration_workflow.json` 中填写
相机序列号、标定板尺寸、空手起始位（HOME）和采集参数；工具中心点（TCP）须匹配实际安装。
标定与抓杯使用相同的分辨率、裁剪区域和相机内参，不复用其他安装的外参。

自动采样会驱动机械臂，须预留整条路线的运动空间。退出其他设备控制程序，设置工程师 PIN 并启动标定网页：

```bash
bash calibrate_web.sh --set-pin
bash calibrate_web.sh --host 0.0.0.0
```

浏览器打开 `http://<主机地址>:8091/`，按顺序完成：

1. 示教并设置标定板可见区域。
2. 生成路线，自动采样并求解外参。
3. 登记固定参考板，应用结果并采集、登记桌面。

结果保存在 `SITE/calibration/`，应用结果时生成 `SITE/green_cup.json`。
更换相机、基座或外参后须重新登记桌面。完成后按 Ctrl+C 退出标定网页。

## 抓杯与游戏

### 生成应用配置

完成标定和桌面登记并退出标定程序后执行：

```bash
dice-arena configure
```

配置保存到 `SITE/cup_application.json`，已有文件不覆盖。
HOME、TCP、杯体尺寸和手型须匹配当前安装。抓取和张开手型、手指动作时长取自 `SITE/green_cup.json`
（`grip_targets_0_100`、`open_targets_0_100`、`fast_finger_duration_s`，灵巧手刻度 `0` 张开、`100` 闭合）。

### 单次抓杯、摇杯和放杯

以下命令会驱动真机。机械臂须空手位于 HOME，杯子位于视觉工作区，操作者能观察完整动作：

```bash
dice-arena cycle
```

`cycle` 执行一次抓杯、摇杯和放杯。默认闭手后直接抬杯，不检测是否抓稳。
需要回 HOME 时，先排除持物和路径障碍，再执行 `dice-arena home`；该命令同时张手。
故障或持杯取消后不自动归位、张手或恢复。任务状态记录在 `SITE/runtime/task_state.json`，重启后仍拒绝运动；
现场操作者检查机械臂、灵巧手和杯子并处理后，执行 `dice-arena reset` 清除记录。

### 启动游戏

将装好骰子的杯子放在视觉工作区，机械臂位于 HOME 且手张开，启动游戏：

```bash
dice-arena serve
```

浏览器打开 `http://<主机地址>:8080/`。Ctrl+C 停止游戏和视频服务，语音服务保留供下次复用。

## 现场文件

| 文件 | 内容 |
| --- | --- |
| `SITE/nero/device.yaml` | 设备驱动、连接、关节限位与末端通道 |
| `SITE/green_cup.json` | 相机、外参、桌面、HOME、TCP、杯体与动作配方 |
| `SITE/cup_application.json` | 设备配置引用、规划器与持物确认方式 |
| `SITE/runtime/` | 需要人工处理的任务状态 `task_state.json`、抓杯采集数据（只保留最近 3 次启动、每次最近 20 次抓杯） |
| `SITE/dice_arena/config.json` | 游戏、语音与视频设置，首次启动游戏时生成 |

重新安装不覆盖现场配置和标定结果。

## 代码结构

```text
src/、include/                动作控制与持物状态管理
python/cup_shake/             抓杯规划与动作编排
python/spacemit_dice_arena/    dice-arena 统一命令入口
algorithms/                  抓杯算法、模型、TCP 和手部几何
calibration/                 手眼标定 CLI/Web、配置与示教路线
game/                        游戏后端、网页、语音与骰子识别
mediamtx/                    实时视频转发
config/、tools/、tests/       配置、部署工具与无硬件测试
```

## 参考文档

- [标定与抓杯操作](docs/grasp.md)：命令行标定、桌面更新与人工持物确认。
- [游戏服务与排障](docs/real_robot.md)：服务端口、状态查询与离线测试。
- [配置与接口](docs/configuration.md)：配置字段、动作参数与业务接口。

## License

本组件源码文件头声明为 Apache-2.0，最终以本目录 `LICENSE` 文件为准。第三方声明见 `NOTICE`。

# Dice Arena 骰子游戏

集成视觉抓杯、摇杯放杯、手眼标定、游戏网页、语音播报和骰子识别。
设备控制统一经过 `manipulation`；C++ 管理动作阶段，Python 负责视觉规划与游戏调度。

## 构建与模拟运行

在 SDK 根目录执行：

```bash
source build/envsetup.sh
bash components/thirdparty/pyagxarm/tools/setup_sdk.sh
cd application/native/dice_arena
mm --with-deps
dice-arena mock
dice-arena check
```

`mock` 检查抓、摇、放，`check` 检查游戏接口；均不连接机械臂、相机或音频设备。
需要 C++17、CMake 3.16+、Python 3.10+。`mm` 检查并提示安装声明的系统依赖；骰子识别在 K3 上编译。

## 运行资源

源码仓库不包含推理模型、机械臂与手部网格、MediaMTX 可执行文件。
按 [runtime_assets.json](runtime_assets.json) 列出的相对路径放置或链接资源，再校验并重新安装：

```bash
python3 tools/check_assets.py --verify
mm --with-deps
```

清单记录文件大小和 SHA-256；校验不连接设备。仓库不提供这些资源的下载地址。
缺少运行资源时只能运行 Mock，不能进行视觉抓杯或启动完整游戏。

## 硬件准备

Nero 通过 CAN 连接主机，右 Revo2 与机械臂共用连接；外置 RealSense 用于抓杯和标定，
C920 用于骰子识别，摄像头通过 USB 连接主机，并准备音箱。
先完成[设备配置与运动检查](https://github.com/spacemit-robotics/manipulation#3-连接-nero)。
Nero 断电会坍塌；现场须有人看护且可急停，不用断电代替软件停止。

## 手眼标定

从本应用目录启动标定网页或命令行，退出其他占用设备的程序：

```bash
bash calibrate_web.sh --host 0.0.0.0
```

网页地址为 `http://<K3地址>:8091/`，首次启动用 `--set-pin` 设置工程师 PIN。
也可使用命令行，不与标定网页同时操作设备：

```bash
bash calibrate.sh auto
bash calibrate.sh apply
```

`auto` 按示教路线采样和求解，`apply` 安装外参并采集、登记桌面；两者会访问真机。
`first/window/plan/register/restore/table/status` 分别提供示教、可见范围、路线、固定板、恢复、桌面和状态操作。
后台网页服务用 `bash calibration_web_service.sh start|stop|status` 管理。
参数在 `calibration/config/calibration_workflow.json`，结果保存在 `SITE/calibration/`。

## 抓杯与游戏

完成标定、桌面登记，确认 HOME、TCP、手型和杯体参数适用，退出标定程序后执行：

```bash
dice-arena configure
dice-arena inspect
dice-arena cycle
dice-arena serve
```

`cycle` 会驱动机械臂抓杯、摇杯和放杯；单次实体流程通过后再启动游戏。
游戏网页为 `http://<K3地址>:8080/`，Ctrl+C 停止游戏和视频；语音服务保持运行供下次复用。
首次启动显示语音模型加载和短句预热阶段。`dice-arena status` 查看游戏组件状态。
现场配置默认保存在 `~/.local/share/spacemit-manipulation/site/`，重新安装不覆盖。
`cup-shake` 保留为抓杯操作的兼容命令，不是独立应用包。

默认闭手后直接抬杯，没有力觉或触觉抓稳验证；需要人工确认时设置 `grip_confirmation: operator`。
故障或持杯取消后不自动归位、张手或恢复；先由操作者检查持物与机械臂状态。
完整操作见[抓杯操作](docs/grasp.md)、[游戏运行](docs/real_robot.md)，参数见[配置参考](docs/configuration.md)。

## 代码结构

```text
src/、include/                C++ 动作阶段与持物状态机
python/cup_shake/             抓杯视觉规划、动作编排和兼容接口
python/spacemit_dice_arena/    dice-arena 统一命令入口
algorithms/                  抓杯算法、模型、TCP 和手部几何
calibration/                 手眼标定 CLI/Web、配置与示教路线
game/                        游戏后端、网页、语音与骰子识别
mediamtx/                    实时视频转发
config/、tools/、tests/       配置、部署工具与无硬件测试
```

## 许可

自有控制与适配代码按 [Apache-2.0](https://github.com/spacemit-robotics/manipulation/blob/HEAD/LICENSE) 使用。
`algorithms/`、`calibration/` 与游戏源码的上游未声明统一许可证，抓杯和骰子识别模型未明确再分发授权；
对外分发前须确认。厂商 SDK 见 [pyAgxArm 许可](https://github.com/spacemit-robotics/pyagxarm/blob/HEAD/README.vendor.md)，
语音、字体、手部几何和视频服务见 [第三方许可](THIRD_PARTY.md)。

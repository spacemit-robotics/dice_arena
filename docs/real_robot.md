# Dice Arena 真机运行

以下命令从 SDK 根目录执行，并已执行 `source build/envsetup.sh`；
先按[运行资源](../README.md#运行资源)准备模型、网格和视频程序，再安装应用。
现场条件见[真机操作前提](https://github.com/spacemit-robotics/manipulation#3-连接-nero)。

## 1. 准备

- 完成[抓杯摇杯真机操作](grasp.md)，确认 `dice-arena cycle` 单次抓、摇、放通过。
- 机械臂在 HOME、手张开，装好骰子的杯子在视觉工作区；C920 摄像头对准骰子区，音箱已连接。
- 退出 `cup-shake` 等占用设备的程序。

## 2. 启动

```bash
dice-arena serve
```

依次启动视频服务 mediamtx（端口 8554、8889）、本地语音 MOSS-TTS（端口 18082，首次加载模型需几十秒）和游戏（端口 8080），与原启动脚本相同；浏览器打开 `http://<K3地址>:8080/`。
只监听本机时用 `dice-arena serve --host 127.0.0.1`。Ctrl+C 停止游戏和视频服务；本地语音服务保持运行，下次启动直接复用。
游戏配置为 `SITE/dice_arena/config.json`（首次启动时由默认配置生成，修改后游戏自动重新加载，重新安装不会覆盖）。

端口被占用时 `serve` 拒绝启动并说明原因；以前单独安装的视频服务或语音服务需先停止，例如
`systemctl --user disable --now mediamtx`。

进入游戏时后台连接设备并启动相机、模型和碰撞几何（与原应用常驻进程预热一致，由规则讲解时间覆盖），不使能、不运动。
结果反馈与原应用相同：机械臂赢做 V 手势、输做点赞、平局做开合手势（手臂与手指同时运动），每局结束回 HOME 并张手。
出错后不会自动回 HOME：可能还持杯，需人工处理。

## 3. 检查

在另一终端检查服务，不启动第二个设备控制端：

```bash
dice-arena status
```

核对语音播报、骰子识别和机械臂各组件的健康字段。故障后不自动重试；先停止游戏，核对持物状态和机械臂实际姿态，
不删除资源锁或用其他程序接管运动中的设备。

开启人工持物确认（抓杯应用配置 `grip_confirmation: operator`）时，用 `dice-arena events ROUND_ID` 观察当前局，
收到 `phase=await_grip_confirmation` 后用该事件的 `token` 和 `acknowledgement` 路径执行 `dice-arena ack-grip TOKEN OUTPUT`。

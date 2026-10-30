# 抓杯摇杯真机操作

执行前检查手型、标定与安全条件。故障后不自动归位或恢复任务。

先完成[运动控制验证](https://github.com/spacemit-robotics/manipulation#3-连接-nero)，并退出标定与独立设备控制程序。
以下命令从 SDK 根目录执行，并已执行 `source build/envsetup.sh`。
模型和网格须按[运行资源](../README.md#运行资源)准备；算法、TCP 和 HOME 配置随应用安装。

## 1. 手眼标定与桌面登记

按[手眼标定](../README.md#手眼标定)完成采样、求解和固定板登记，再执行 `calibrate.sh apply`（或网页“应用”）：
备份后把结果安装到 `SITE/calibration/handeye_result.json`，首次运行时创建 `SITE/green_cup.json`，并重新采集、登记桌面。
桌面登记失败时用 `calibrate.sh table` 重试；登记完成前 `dice-arena cycle` 拒绝运行。

核对当前安装的工具中心点（TCP）、空手起始位（HOME）、手型、杯体尺寸和相机采集参数。
HOME 用 `dice-arena home` 到达（原应用的 `home` 动作，回 HOME 同时张手）；不能把任意当前姿态改名为 HOME。
抓杯中途出错时手可能还持杯：先人工确认杯子状态再执行。

## 2. 检查场景

清理桌面工作区，保持基座、相机和桌面固定；桌布颜色、工作区和桌面几何参数须与 `SITE/green_cup.json` 一致。
更换外参后必须重新登记桌面，不手工修改桌面记录的摘要。

## 3. 生成应用配置

```bash
dice-arena configure
```

配置保存到 `SITE/cup_application.json`。生成过程不连接设备。复核应用配置中的 `open_positions`、`grip_positions` 和结果手型，
确认六通道方向、接触及保持方式与当前右手和杯体一致。默认位置数组需按当前安装与杯体调整。

## 4. 单独验证一次抓、摇、放

以下命令会驱动真机。须满足[现场安全前提](https://github.com/spacemit-robotics/manipulation#3-连接-nero)，机械臂和空手位于已验证的 HOME，
杯子位于已确认的视觉工作区，操作者能观察接近、闭手、抬杯和放杯。

```bash
dice-arena inspect
dice-arena cycle
```

`inspect` 仅检查连接与状态，不证明视觉、手型或场景正确。
与原应用一致，闭手后直接抬杯，程序不检测是否抓稳；首次运行请在急停旁观察接近、闭手和抬杯。
应用配置设置 `"grip_confirmation": "operator"` 时，闭手后等待输入 `CONFIRM` 才抬杯。

抓、摇、放三段均需返回 `status=completed`，并由操作者确认真实持杯、摇杯、放杯和最终姿态。
输出中的 `physical_grip_verified` 始终为 `false`：系统没有力觉或触觉抓稳验证。
实体流程未通过前，不运行游戏。

通过单次实体流程后，按[Dice Arena 真机运行](real_robot.md)运行骰子游戏。

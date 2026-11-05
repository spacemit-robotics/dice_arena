# 标定与抓杯操作

适用于已安装应用和运行资源的现场。以下命令从 SDK 根目录开始：

```bash
source build/envsetup.sh
cd application/native/dice_arena
```

`SITE` 默认指 `~/.local/share/spacemit-manipulation/site/`。
标定使用当前设备，须为 Nero；不是时先执行 `manipulation use nero`。退出其他设备控制程序，不同时运行网页与命令行标定。

## 1. 命令行标定

固定相机、基座和标定板。在 `calibration/config/calibration_workflow.json` 中填写相机序列号、
标定板实测尺寸、HOME 和采集参数。HOME 和 TCP 须匹配当前安装，不能把任意当前姿态当作 HOME。

自动采样会驱动机械臂。现场须有人看护、急停可达，整条路线内无人、无障碍；不以断电或失能代替软件停止。
依次执行，按提示遮挡或露出对应标定板：

```bash
bash calibrate.sh first
bash calibrate.sh window
bash calibrate.sh plan
bash calibrate.sh auto
bash calibrate.sh register
bash calibrate.sh apply
```

| 命令 | 作用 |
| --- | --- |
| `first` | 手动示教、采样并求解初始外参 |
| `window` | 设置标定板可见区域 |
| `plan` | 生成自动采样路线 |
| `auto` | 沿路线运动、采样并求解 |
| `register` | 登记固定参考板 |
| `apply` | 备份并安装外参，生成现场算法配置，采集并登记桌面 |
| `solve` | 用已有数据集重新求解外参，不采样 |
| `restore` | 相机移动后，回 HOME 并通过固定参考板恢复外参 |
| `status` | 只读，显示当前配置和标定进度 |

各步骤加 `--dry-run` 只显示将执行的操作，不访问设备。

结果保存在 `SITE/calibration/`，现场算法配置为 `SITE/green_cup.json`。

标定网页也可以在后台运行：`bash calibration_web_service.sh start` 启动，`status` 查询，`stop` 停止。

## 2. 更新桌面

相机、基座或外参变化后，重新采集并登记桌面：

```bash
bash calibrate.sh table
```

保持相机、基座和桌面固定；桌布颜色、工作区和杯体尺寸须与 `SITE/green_cup.json` 一致。
桌面记录缺失或与外参不匹配时，抓杯任务拒绝运行。不手工修改记录摘要。

## 3. 人工持物确认

默认闭手后直接抬杯，不使用力觉或触觉判断是否抓稳。在 `SITE/cup_application.json` 中设置
`"grip_confirmation": "operator"` 后，每次闭手后等待人工确认。

以下命令会驱动真机。机械臂须空手位于 HOME，杯子位于视觉工作区，操作者能观察完整动作：

```bash
dice-arena cycle
```

确认实际持杯后输入 `CONFIRM` 才抬杯；输入其他内容则停止任务。
人工确认不能替代力觉或触觉检测。
故障或持杯取消后不自动张手、归位或恢复，由现场操作者处理。

## 4. 回到 HOME

仅在空手且路径无障碍时执行；该命令同时张手：

```bash
dice-arena home
```

可能持杯或故障锁定时拒绝执行。故障锁定会记录在 `SITE/runtime/task_state.json`，重启后仍然有效。现场操作者检查机械臂、灵巧手和杯子并处理后，清除记录：

```bash
dice-arena reset
```

该命令不连接设备、不运动，只删除记录；之后重新启动 `dice-arena cycle` 或 `dice-arena serve`。

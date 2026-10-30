# 抓杯摇杯配置参考

本页对应 `python/cup_shake/runtime.py` 与 `python/cup_shake/planners.py`。
设备连接与命令结果见[组合设备接口参考](https://github.com/spacemit-robotics/manipulation/blob/HEAD/docs/reference.md)。

## 1. 配置与业务接口

`CupApplication` 顶层要求以下字段，未知字段拒绝。

| 字段 | 默认 / 含义 |
| --- | --- |
| `schema_version` | 必填 `1` |
| `executable` / `device_plan` / `policy_library` | 必填路径，相对配置文件或绝对路径 |
| `planner` | 必填策略配置，已实现 `fixture`、`legacy_green` |
| `speed_scale` | 必填 `(0,0.1]` 倍率，仅用于 Fixture；`legacy_green` 使用算法配置中的 FAST 速度 |
| `open_positions` / `grip_positions` | 必填非空归一化通道数组 |
| `duration_s` | 必填 `(0,2.55]` s，手指动作时长；`configure` 取算法配置的 `fast_finger_duration_s` |
| `home_tolerance_rad` | 可选，默认 0.5°（原应用判定已在 HOME 的容差），范围 `(0,0.01]` rad |
| `grip_confirmation` | 可选 `none`（默认，与原应用一致：闭手指令完成即抬杯）或 `operator`（每次等待人工确认） |
| `grip_ack_directory` | `operator` 模式的确认文件目录 |
| `gestures` | 可选，名称到归一化手型的映射；完成后回空手手型 |

Fixture 字段为 `home_rad` 和各阶段 `targets`。它仅用于 Mock。
`legacy_green` 只有 `source_root`、`config`、`session_directory` 三项，相对应用配置文件解析。
碰撞几何首次计算后保存在 `session_directory` 同级的 `geometry/`，按其全部源文件内容校验；源文件变化时重新计算。
各阶段运动与原应用 FAST 模式一致，参数都来自算法配置（`green_cup.json`）：

| 阶段 | 执行方式 |
| --- | --- |
| 接近、回 HOME | 梯形速度曲线连续发送，`fast_phase_speed_percent`（100%）× 控制器实时关节速度，加速度上限 `joint_delivery.acceleration_cap_rad_s2` |
| 抬杯 | 同上，`fast_speed_percent`（30%），抬起 `lift_mm` |
| 摇杯 | `joint_test_config`（`configs/actions/joint_shake.json`）配方：关节、幅度、速度、加速度、周期数、200 Hz 混合指令 |
| 放杯 | `lower_command_mode: controller_endpoint`：控制器规划的点位运动，速度 100%，偏差超过 0.5° 期间每 50 ms 重发同一目标，连续两次反馈在 0.5° 内即张手；到位偏差超过 `place_arrival_tolerance_mm` 时按 `precision_error_action` 记录或中止 |
| 手指 | `grip_targets_0_100` / `open_targets_0_100`，时长 `fast_finger_duration_s` |

与原应用的 FAST 衔接一致：接近、抬杯、摇杯、回 HOME 发完最后一个指令即进入下一段，机械臂随后在收尾中衔接；
放杯在 0.5° 内即张手。灵巧手动作期间，机械臂可以继续收尾到上一段的目标（与原应用一致）；其他移动不得超过 1°（原应用 `hand_start_tolerance_deg`）。

业务入口为 `command(name, on_event=..., is_cancelled=..., timeout_seconds=120)`，
期限范围 `(0,180]` 秒。返回 `completed` 或 `failed`；失败包含 reason 和任务状态。
`grip_confirmation: operator` 时，真机抬杯前要求包含本次 token、操作者和时间戳的持物确认；`physical_grip_verified` 始终为 `false`。
`query_pose` 只读 HOME 探测。`reset_home` 执行原应用的 `home` 动作（机械臂回 HOME 同时张手）；
`ensure_home` 已在 HOME 且手已张开时不运动，否则同样执行 `home` 动作；`grasp_cup` 开始时不在 HOME 也先执行它（原应用的 HOME 阶段）。
三者只在空闲任务状态执行：可能持杯或故障锁定后拒绝，需人工处理。
`gesture:win`、`gesture:lose`、`gesture:draw` 执行原应用的结果反馈手势（`configs/actions/gestures/result_feedback.json`，
即 `yeah`、`thumbs-up`、`tie`）：机械臂以配方速度沿五次曲线移到手势姿态，从第一条手臂指令起按配方发出手指动作，
完成后保持该姿态，由随后的 `ensure_home` 回 HOME。

## 2. 操作命令

命令入口为 `dice-arena`。默认现场目录是 `~/.local/share/spacemit-manipulation/site/`，算法与模型随应用安装在 `share/dice_arena/algorithms/`。

| 命令 | 行为 |
| --- | --- |
| `dice-arena configure` | 离线生成 `cup_application.json`，算法配置使用 `SITE/green_cup.json`（由 `calibrate.sh apply` 创建） |
| `dice-arena inspect` | 连接并读取设备，无运动 |
| `dice-arena home` | 原应用的 `home` 动作：机械臂以 100% 速度沿五次曲线回 HOME，同时张手（先做桌面碰撞检查，不启动相机） |
| `dice-arena cycle` | 执行一次抓、摇、放；`operator` 确认模式下闭手后输入 `CONFIRM`，`--operator NAME` 记录确认人（默认当前登录用户） |

`--site` 和 `--source` 写在子命令前；`configure` 拒绝覆盖已有输出。
手眼标定与桌面登记使用 `calibrate.sh`，见 [README](../README.md#手眼标定)。
流程与前提见[抓杯操作](grasp.md)。

`share/cup_shake` 仅用于兼容旧现场配置；新配置引用 `share/dice_arena`。
安装不会删除已有的旧资源目录，也不覆盖 `SITE` 中的配置或标定数据。

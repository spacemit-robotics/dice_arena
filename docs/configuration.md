# 抓杯摇杯配置参考

抓杯应用的配置字段、动作参数和操作命令。

## 1. 配置与业务接口

`CupApplication` 顶层要求以下字段，未知字段拒绝。

| 字段 | 默认 / 含义 |
| --- | --- |
| `schema_version` | 必填 `3` |
| `executable` / `device_plan` / `policy_library` | 必填路径，相对配置文件或绝对路径 |
| `planner` | 必填策略配置，已实现 `fixture`、`green_cup` |
| `speed_scale` | 必填 `(0,0.1]` 倍率，仅用于 Fixture；`green_cup` 使用算法配置中的 FAST 速度 |
| `open_positions` / `grip_positions` / `duration_s` / `gestures` | 仅 Fixture 必填：张开、抓取手型（`0` 闭合、`1` 张开）、手指动作时长 `(0,2.55]` s 和结果手型；`green_cup` 不接受这些字段，手型和时长取自其算法配置 |
| `state_file` | 可选，需要人工处理的任务状态的记录文件；`configure` 设为 `runtime/task_state.json` |
| `home_tolerance_rad` | 可选，默认 0.5°，范围 `(0,0.01]` rad |
| `grip_confirmation` | 可选 `none`（默认，闭手指令完成即抬杯）或 `operator`（每次等待人工确认） |
| `grip_ack_directory` | `operator` 模式的确认文件目录 |

Fixture 字段为 `home_rad` 和各阶段 `targets`。它仅用于 Mock。
`green_cup` 只有 `source_root`、`config`、`session_directory` 三项，相对应用配置文件解析。
碰撞几何首次计算后保存在 `session_directory` 同级的 `geometry/`，按其全部源文件内容校验；源文件变化时重新计算。
各阶段参数来自算法配置 `green_cup.json`：

| 阶段 | 执行方式 |
| --- | --- |
| 接近、回 HOME | 梯形速度曲线连续发送，`fast_phase_speed_percent`（100%）× 控制器实时关节速度，加速度上限 `joint_delivery.acceleration_cap_rad_s2` |
| 抬杯 | 同上，`fast_speed_percent`（30%），抬起 `lift_mm` |
| 摇杯 | `joint_test_config`（`configs/actions/joint_shake.json`）配方：关节、幅度、速度、加速度、周期数、200 Hz 混合指令 |
| 放杯 | `lower_command_mode: controller_endpoint`：控制器规划的点位运动，速度 100%，偏差超过 0.5° 期间每 50 ms 重发同一目标，连续两次反馈在 0.5° 内即张手；到位偏差超过 `place_arrival_tolerance_mm` 时按 `precision_error_action` 记录或中止 |
| 手指 | `grip_targets_0_100` / `open_targets_0_100`，时长 `fast_finger_duration_s`；沿用灵巧手刻度（`0` 张开、`100` 闭合），应用连接时换算为 `0` 闭合、`1` 张开 |

接近、抬杯、摇杯和回 HOME 发完最后一个指令即进入下一段，机械臂可继续完成上一段运动；
放杯在 0.5° 内即张手。灵巧手动作期间，机械臂可继续接近上一段目标；其他移动不得超过 1°。

业务入口为 `command(name, on_event=..., is_cancelled=..., timeout_seconds=120)`，
期限范围 `(0,180]` 秒。返回 `completed` 或 `failed`；失败包含 reason 和任务状态。
`grip_confirmation: operator` 时，真机抬杯前要求包含本次 token、操作者和时间戳的持物确认；`physical_grip_verified` 始终为 `false`。
`query_pose` 只读 HOME 探测；手指没有位置反馈时，本进程张开过手指后才算在 HOME。`reset_home` 回 HOME 并同时张手；
`ensure_home` 已在 HOME 且手已张开时不运动，否则执行回 HOME 和张手；`grasp_cup` 开始时不在 HOME 也先执行该动作。
三者只在空闲任务状态执行：可能持杯或故障锁定后拒绝，需人工处理。
动作发出前的失败（如没有识别到杯子、命令被拒绝或开始前取消）不改变任务状态，可以直接重试。动作发出后的失败使任务进入故障锁定，并把任务状态记录到 `state_file`；程序重启后仍拒绝运动，直到现场操作者检查机械臂、灵巧手和杯子，执行 `dice-arena reset` 清除记录。
`gesture:win`、`gesture:lose`、`gesture:draw` 执行结果反馈手势（`configs/actions/gestures/result_feedback.json`，
即 `yeah`、`thumbs-up`、`tie`）：机械臂以配方速度沿五次曲线移到手势姿态，从第一条手臂指令起按配方发出手指动作，
完成后保持该姿态，由随后的 `ensure_home` 回 HOME。

## 2. 操作命令

命令入口为 `dice-arena`。默认现场目录是 `~/.local/share/spacemit-manipulation/site/`，算法与模型随应用安装在 `share/dice_arena/algorithms/`。

| 命令 | 行为 |
| --- | --- |
| `dice-arena configure` | 离线生成 `cup_application.json`，算法配置使用 `SITE/green_cup.json`（由 `calibrate.sh apply` 创建） |
| `dice-arena inspect` | 连接并读取设备，无运动 |
| `dice-arena home` | 机械臂以 100% 速度沿五次曲线回 HOME，同时张手；先做桌面碰撞检查，不启动相机 |
| `dice-arena cycle` | 执行一次抓、摇、放；`operator` 确认模式下闭手后输入 `CONFIRM`，`--operator NAME` 记录确认人（默认当前登录用户） |

`--site` 和 `--source` 写在子命令前；`configure` 拒绝覆盖已有输出。
手眼标定与桌面登记使用 `calibrate.sh`。

安装不覆盖 `SITE` 中的配置或标定数据。

## 3. 相关接口

- [组合设备接口参考](../../../../components/control/manipulation/docs/reference.md)
- [标定与抓杯操作](grasp.md)

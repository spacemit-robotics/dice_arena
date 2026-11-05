# 抓杯摇杯配置参考

抓杯应用的配置字段、动作参数、业务接口和操作命令。

## 1. 应用配置

`SITE/cup_application.json` 由 `dice-arena configure` 生成，`CupApplication` 读取。未知字段一律拒绝。

| 字段 | 默认 / 含义 |
| --- | --- |
| `schema_version` | 必填，`3` |
| `executable` / `device_plan` / `policy_library` | 必填路径，相对配置文件或绝对路径 |
| `planner` | 必填，规划器配置，可选 `fixture`、`green_cup` |
| `speed_scale` | 必填，`(0,0.1]` 倍率，仅用于 `fixture`；`green_cup` 使用算法配置中的 FAST 速度 |
| `open_positions` / `grip_positions` / `duration_s` / `gestures` | 仅 `fixture` 必填：张开手型、抓取手型（`0` 为闭合，`1` 为张开）、手指动作时长 `(0,2.55]` s 和结果手型；`green_cup` 不接受这些字段，手型和时长取自其算法配置 |
| `state_file` | 可选，记录需要人工处理的任务状态；`configure` 设为 `runtime/task_state.json` |
| `home_tolerance_rad` | 可选，默认 0.5°，范围 `(0,0.01]` rad |
| `grip_confirmation` | 可选，`none`（默认，手部闭合指令完成即抬杯）或 `operator`（每次等待人工确认） |
| `grip_ack_directory` | `operator` 模式的确认文件目录 |

规划器配置：

- `fixture`：字段为 `home_rad` 和各阶段的 `targets`，仅用于 Mock。
- `green_cup`：字段为 `source_root`、`config`、`session_directory`，相对应用配置文件解析。
  碰撞几何首次计算后保存在 `session_directory` 同级的 `geometry/`，按全部源文件的内容校验，源文件变化时重新计算。

## 2. 动作参数

`green_cup` 各阶段的参数来自算法配置 `green_cup.json`：

| 阶段 | 执行方式 |
| --- | --- |
| 接近、返回 HOME | 梯形速度曲线连续发送，速度为 `fast_phase_speed_percent`（100%）× 控制器实时关节速度，加速度上限为 `joint_delivery.acceleration_cap_rad_s2` |
| 抬杯 | 同上，速度为 `fast_speed_percent`（30%），抬起高度为 `lift_mm` |
| 摇杯 | 按 `joint_test_config`（`configs/actions/joint_shake.json`）配方执行：关节、幅度、速度、加速度、周期数，200 Hz 混合指令 |
| 放杯 | `lower_command_mode: controller_endpoint`：控制器规划的点位运动，速度 100%；偏差超过 0.5° 期间每 50 ms 重发同一目标，连续两次反馈在 0.5° 内即张开手部；到位偏差超过 `place_arrival_tolerance_mm` 时，按 `precision_error_action` 记录或中止 |
| 手指 | `grip_targets_0_100` / `open_targets_0_100`，默认值在抓杯策略 `vision/strategy/green_cup.json`，可在 `green_cup.json` 中覆盖；张开手型须全为 `0`。时长为 `fast_finger_duration_s`。使用灵巧手刻度（`0` 为张开，`100` 为闭合），应用连接时换算为 `0` 闭合、`1` 张开 |

- 接近、抬杯、摇杯和返回 HOME 发送完最后一条指令即进入下一阶段，机械臂可继续完成上一阶段的运动。
- 放杯在 0.5° 内即张开手部。
- 灵巧手动作期间，机械臂可继续向上一阶段的目标收拢；其他移动不得超过 1°。

## 3. 业务接口

业务入口为 `command(name, on_event=..., is_cancelled=..., timeout_seconds=120)`，期限范围 `(0,180]` 秒。
返回 `completed` 或 `failed`；失败时包含原因和任务状态。

| 命令 | 行为 |
| --- | --- |
| `grasp_cup` | 识别、抓取并抬起杯子；开始时不在 HOME，则先执行 `reset_home` |
| `shake_dice` | 摇动已抬起的杯子 |
| `settle_dice` | 放下杯子、张开手部并返回 HOME |
| `query_pose` | 只读，判断是否位于 HOME；手指没有位置反馈时，本进程张开过手部后才算位于 HOME |
| `reset_home` | 返回 HOME 并同时张开手部 |
| `ensure_home` | 已在 HOME 且手部张开时不运动，否则同 `reset_home` |
| `gesture:win` / `gesture:lose` / `gesture:draw` | 结果反馈手势，见下文 |

- **执行条件**：`reset_home`、`ensure_home`、`grasp_cup` 只在空闲任务状态下执行；可能持杯或故障锁定时拒绝，须人工处理。
- **失败与锁定**：
  - 动作发出前失败（如未识别到杯子、命令被拒绝或开始前取消）不改变任务状态，可以直接重试；
  - 动作发出后失败，任务进入故障锁定，并把任务状态记录到 `state_file`；
  - 程序重启后仍拒绝运动，直到现场操作人员检查机械臂、灵巧手和杯子，并执行 `dice-arena reset` 清除记录。
- **人工持物确认**：`grip_confirmation: operator` 时，真机抬杯前要求持物确认，确认内容包含本次 token、操作人员和时间戳。`physical_grip_verified` 始终为 `false`。
- **结果手势**：`gesture:win`、`gesture:lose`、`gesture:draw` 分别执行 `configs/actions/gestures/result_feedback.json` 中的 `yeah`、`thumbs-up`、`tie`。
  机械臂以配方速度沿五次曲线移到手势姿态，从第一条机械臂指令起按配方发出手指动作；完成后保持该姿态，由随后的 `ensure_home` 返回 HOME。

## 4. 操作命令

命令入口为 `dice-arena`。现场目录默认为 `~/.local/share/spacemit-manipulation/site/`，算法与模型随应用安装在 `share/dice_arena/algorithms/`。

| 命令 | 行为 |
| --- | --- |
| `dice-arena configure` | 离线生成 `cup_application.json`；算法配置使用 `SITE/green_cup.json`（由 `calibrate.sh apply` 创建） |
| `dice-arena inspect` | 连接并读取设备，不运动 |
| `dice-arena home` | 机械臂以 100% 速度沿五次曲线返回 HOME，同时张开手部；先做桌面碰撞检查，不启动相机 |
| `dice-arena cycle` | 执行一次抓杯、摇杯和放杯；`operator` 确认模式下，手部闭合后输入 `CONFIRM`，`--operator NAME` 记录确认人（默认为当前登录用户） |
| `dice-arena reset` | 现场处理完毕后清除 `state_file` 中的任务状态记录；不连接设备、不运动 |
| `dice-arena mock` | 用 Mock 设备执行一次抓杯、摇杯和放杯，不连接硬件 |

- `--site` 和 `--source` 写在子命令之前。
- `configure` 不覆盖已有文件；安装不覆盖 `SITE` 中的配置和标定数据。
- 手眼标定与桌面登记使用 `calibrate.sh`，见 [标定与抓杯操作](grasp.md)。

## 5. 相关文档

- [机械臂组件接口参考](../../../../components/control/manipulation/docs/reference.md)
- [标定与抓杯操作](grasp.md)

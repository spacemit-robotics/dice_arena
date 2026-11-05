# 结果手势

`result_feedback.json` 定义摇骰子的结果手势和返回 HOME 动作，`aliases` 把游戏结果映射到手势：

- `win` → `yeah`（V 手势）；
- `lose` → `thumbs-up`（竖拇指）；
- `draw` → `tie`（开合手势）。

`home` 是返回 HOME 动作：机械臂返回 HOME，同时六路手指张开。

每个手势的字段：

| 字段 | 说明 |
| --- | --- |
| `joints_deg` | 机械臂七个关节的目标角度，单位为 ° |
| `hand_0_100` | 六路手指目标，使用灵巧手刻度：`0` 张开，`100` 闭合 |
| `speed_percent` | 机械臂速度，为控制器关节速度上限的百分比 |
| `execution` | `mode: together` 表示机械臂运动时同时发送手指目标，`delay_s` 为手指相对机械臂的启动延时 |
| `finger_speed_mode`、`finger_duration_s`、`finger_max_wait_s` | 手指速度档位、执行时长和等待时间；手指没有位置反馈，等待时间不是到位测量 |
| `hand_sequence` | 可选，手指往复动作，如平局的开合 |

- 文件顶层的 `speed_percent`、`finger_duration_s` 等字段是本文件内各手势的默认值。
- 修改后重新执行 `mm` 安装。运行中的进程检测到文件变化后拒绝继续执行，须重新启动 `dice-arena cycle` 或 `dice-arena serve`。

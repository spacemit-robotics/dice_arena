# 摇骰子游戏参数

`game/backend/games/dice/manifest.json` 定义摇骰子游戏的基本信息、语音触发词、视觉裁决参数和状态机。
识别进程的模型、检测参数、摄像头与推流在 `game/backend/games/dice/adjudicator_config.json`，见 [视觉裁决组件参数](../../components/vision_yolov8_objdetect/parameters.md)。
全局设置见 [全局配置参数](../../parameters.md)。

## 生效方式

在源码中修改后，从 SDK 根目录执行 `source build/envsetup.sh`，再重新安装：

```bash
cd application/native/dice_arena
mm
```

- 服务按修改时间自动重载安装后的 manifest，无需重启 `dice-arena serve`。
- 状态机、台词和触发词在新建回合时生效；进行中的回合（含「再来一局」）沿用创建时的配置，返回游戏列表后重新进入即使用新配置。
- `vision_profile` 在下一次裁决时读取。
- 校验失败的 manifest 不替换已加载的配置，服务输出 `[games] skip ...` 和 `[games] reload skipped ...`；服务启动时 manifest 无效则不加载该游戏。
- 游戏音频放在 `game/backend/games/dice/audio/`，同样由 `mm` 安装。

## 1. 基本信息

| 字段 | 当前值 | 说明 |
| --- | --- | --- |
| `id` | `dice` | 游戏 id，须与目录名一致 |
| `name` | `摇骰子` | 游戏列表显示名 |
| `icon` | `🎲` | 游戏列表图标 |
| `description` | `双方各 5 颗 · 比较点数总和` | 游戏列表副标题 |
| `enabled` | `true` | 是否启用；全局 `games_enabled` 声明了该游戏时以全局为准 |

`providers`、`voice`、`speed` 未声明，使用全局配置。声明后覆盖全局值，单条台词可再覆盖。

## 2. asr（语音触发词）

`asr.phrases` 把状态机意图映射到触发词。键须是状态机 `on_intent` 中声明的意图，词表非空且不重复。

| 意图 | 触发词 |
| --- | --- |
| `confirm` | `确认`、`确定`、`OK`、`明白了`、`准备好了`、`yes`、`confirm`、`got it`、`start` |
| `start_shake` | `开始`、`确定`、`start`、`OK`、`begin`、`go` |
| `repeat` | `重复`、`再来一遍`、`再听一次`、`repeat`、`again`、`say it again`、`one more time` |
| `retry` | `重试`、`重新`、`重新来一遍`、`retry`、`try again`、`again` |
| `new_round` | `再来一局`、`再来一句`、`下一局`、`下一句`、`next round`、`play again`、`new round`、`one more round`、`one more game` |
| `back` | `返回`、`退出`、`back`、`go back`、`exit`、`quit` |

- 识别文本去除空格、转为小写后按子串匹配。
- 同一个词可对应多个意图，由当前状态接受的意图生效。
- 台词播放期间的识别结果被忽略。
- 语音输入由全局 `asr_enabled` 和 `providers.asr` 决定；SDK 未包含语音识别组件。

## 3. vision_profile（视觉裁决）

| 字段 | 当前值 | 说明 |
| --- | --- | --- |
| `schema_version` | `1` | 固定为 `1` |
| `game_id` | `dice` | 须与游戏 `id` 一致 |
| `runtime_config` | `backend/games/dice/adjudicator_config.json` | 识别进程配置文件，必填；路径相对 `game/`（安装后为 `share/dice_arena/game/`），不能为绝对路径或含 `..` |
| `vision.class_map` | `"0"`→`"1"` … `"5"`→`"6"` | 模型类别 id 到骰子点数 |
| `vision.participants` | `["LEFT", "RIGHT"]` | 源画面左右两侧；玩家为 `LEFT`，机械臂为 `RIGHT` |
| `vision.expected_count` | `5` | 每侧骰子数；稳定观测中任一侧数量不符时裁决失败 |
| `vision.grouping` | `divider_regions` | `divider_regions` 按识别进程检出的分界线分左右；`x_midpoint` 按画面中线 |
| `vision.divider.position` | 未设置（`0.5`） | 当帧未检出分界线时的切分比例，范围 (0, 1) |
| `vision.divider.orientation` | 未设置（`vertical`） | 兜底切分方向：`vertical` 或 `horizontal` |
| `multi_view.enabled` | `true` | 多机位开关 |
| `multi_view.min_views` | `1` | 裁决所需的最少稳定机位数 |
| `multi_view.views` | 未设置 | 机位列表，每项含 `id`、`camera`、`video.path`、`video.enabled`；未设置时使用单机位 `default`，摄像头取 `adjudicator_config.json` 的 `camera` |
| `rule.kind` | `numeric_compare` | 双方点数求和比较；可选 `higher_wins`（缺省 `true`）、`tie_value`（缺省 `TIE`） |
| `video.enabled` | `true` | 向网页发送实时画面 |
| `video.path` | `/dice/det` | 识别进程向 MediaMTX 推流的路径，也是网页播放路径。网页地址为全局 `video.webrtc_base_url` 加该路径，默认 `http://127.0.0.1:8889/dice/det` |
| `lifecycle.pre_adjudication_wait_seconds` | `0` | 开始识别前的等待时间，0～300 秒，不计入裁决预算 |
| `lifecycle.post_result_hold_seconds` | `0` | 得出结果后、进入 `result` 前保持实时画面的时间，0～300 秒 |
| `timeouts.yolo_detection_seconds` | `8` | 等待稳定观测的时间，须容纳 `stable_frames` 个连续有效帧；超时后按最近画面生成失败诊断 |
| `timeouts.adjudication_seconds` | `30` | 整次裁决的总预算 |

- `vision` 中不接受 `model`、`conf`、`confidence`、`stable_frames`、`divider_detection`，这些参数在 `adjudicator_config.json` 中配置，写入 manifest 时校验失败。
- 多机位时各机位分别得出胜负，按严格多数确定结果；没有严格多数时回合以错误结束。
- 裁决失败时进入 `analysis_failed`，失败原因为 `INCOMPLETE_OBJECTS`（数量不符）、`NO_OBJECTS_DETECTED`（未检出目标）、`SCENE_GEOMETRY_UNCLEAR`（分界线不清）或 `UNSTABLE_DETECTION`（检测不稳定）。

## 4. state_machine（状态机）

`schema_version` 固定为 `1`，`initial` 为回合起始状态，当前为 `rules`。
状态名匹配 `[A-Za-z0-9_-]+`。转换指向未声明的状态时 manifest 校验失败；不可达的状态只输出警告。

### 状态字段

| 字段 | 说明 |
| --- | --- |
| `ui` | 仅 `view`、`title`、`copy`。`view` 为网页视图名，当前使用 `rules`、`ready`、`game_start`、`countdown`、`shaking`、`analysis`、`result`、`arm_failed`、`rehome` |
| `on_enter` | 进入状态时按顺序执行的动作 |
| `duration` | 计时秒数，范围 (0, 300]；`on_enter` 动作发出后开始计时，`await` 台词须先播放完成 |
| `tick_seconds` | 计时节拍，范围 (0, 60]，缺省 1；网页按「剩余时间 ÷ 节拍」向上取整显示倒计时 |
| `on_expire` | 计时结束时的转换，须与 `duration` 同时声明 |
| `on_intent` | 意图到转换的映射。意图名匹配 `[a-z][a-z0-9_]*`；`speech_done`、`speech_started` 为播放回执保留 |
| `on_event` | 内部事件到转换的映射：`adjudication.result`、`adjudication.diagnosis`、`robot.<command>.completed`、`robot.<command>.failed` |

### 转换

每个转换只能含以下一项：

- `{"to": "<状态>"}`：进入指定状态。
- `{"exit": true}`：结束回合，返回游戏列表。
- `{"actions": [...]}`：停留在当前状态并播放其中的台词，例如 `rules` 的 `repeat`。只接受不带 `await` 的 `speech` 动作；机械臂、裁决等动作须放在目标状态的 `on_enter` 中，用 `to` 进入。

`on_intent` 的转换可加 `"after_speech": true`：当前状态 `on_enter` 台词播放完成前拒绝该意图。当前状态机未使用。

### speech 动作

| 字段 | 说明 |
| --- | --- |
| `mode` | `tts_local`（缺省）、`tts_remote` 或 `audio` |
| `text` | `tts_*` 模式必填，最多 4000 字符；`audio` 模式为显示文本 |
| `audio` | `audio` 模式必填：相对 `game/backend/games/dice/` 的 `.wav` 路径，不能为绝对路径或含 `..` |
| `await` | `true` 时等待播放回执后再执行后续动作和计时，最长等待 30 秒 |
| `voice`、`speed` | 覆盖默认音色和语速；`speed` 范围 0.25～4，`tts_moss_nano` 仅支持 `1.0` |
| `provider` | 指定语音组件 id，覆盖槽位选择；`audio` 模式不可用 |
| `select_by`、`cases` | `select_by: "winner_role"` 时按裁决结果选择台词，`cases` 须含 `PLAYER`、`AGENT`、`TIE`，每项含 `mode`、`text` 等字段；此类台词不能 `await` |

台词可使用裁决结果中的标量字段作为占位符，如 `{player_score}`、`{agent_score}`、`{winner_role}`；未知占位符原样输出。

### adjudicate 动作

`{"action": "adjudicate"}` 执行一次视觉裁决。成功时按 `adjudication.result` 转换，失败诊断按 `adjudication.diagnosis` 转换；所在状态缺少对应转换时回合以错误结束。

### robot 动作

`{"action": "robot", "command": "<命令>"}` 由全局或 manifest 的 `providers.robot_arm` 组件执行。

| 命令 | 动作 |
| --- | --- |
| `grasp_cup` | 识别杯子、抓取并抬起，不摇动；开始时不在 HOME，则先返回 HOME 并张开手部 |
| `shake_dice` | 摇动已抬起的杯子，摇动结束即完成 |
| `settle_dice` | 放回杯子、张开手部并返回 HOME |
| `feedback` | 按裁决结果做手势并保持到下一次返回 HOME：`win` 为 V 手势，`lose` 为竖拇指，`draw` 为开合手势 |
| `reset_home` | 返回 HOME 并张开手部；可能持杯时拒绝执行 |
| `ensure_home` | 已在 HOME 且手部张开时不动作，否则同 `reset_home` |

- 动作在后台执行，不能声明 `await`；状态计时照常进行。命令串行执行，后发命令等待前一条完成。
- `timeout_seconds` 可选，`feedback` 除外；范围 (0, 180] 秒，缺省 120，包含排队等待。
- `feedback` 须声明 `select_by: "winner_role"`，`cases` 把 `PLAYER`、`AGENT`、`TIE` 映射到 `win`、`lose`、`draw`（机械臂视角）。
- 命令结束后，按命令完成时所在状态的 `on_event` 路由 `robot.<command>.completed` 或 `robot.<command>.failed`；未声明的路由被忽略。
- 动作发出后失败（含超时和回合取消）时，抓杯任务进入故障锁定，此后的机械臂命令均被拒绝，`arm_failed` 中的重试与归位也不执行。动作发出前失败（如未识别到杯子）不锁定，可以重试。故障处理见 [游戏服务与排障](../../../../docs/real_robot.md)。
- `feedback`、`reset_home`、`ensure_home` 不因回合结束而中断。
- 进入游戏时机械臂组件在后台连接设备，不运动；回合结束（退出、取消或出错）后执行一次 `ensure_home`。

## 5. 当前状态流程

按键：绿色对应 Enter，蓝色对应 ↓，红色对应 Esc；未列出按键的状态不响应按键。

| 状态 | 进入时动作 | 转换 |
| --- | --- | --- |
| `rules`（起始） | 播报规则 | `confirm`（绿）→ `ready`；`repeat`（蓝）重播规则；`back`（红）退出 |
| `ready` | 播报开始提示 | `start_shake`（绿）→ `game_start`；`back`（红）→ `rules` |
| `game_start` | `grasp_cup`，超时 30 秒 | 3.0 秒后 → `shake_countdown`；`robot.grasp_cup.failed` → `arm_failed` |
| `shake_countdown` | 播放 `audio/warm_321开始.wav`；计时 2.4 秒，节拍 0.8 秒 | 计时结束 → `shaking`；`robot.grasp_cup.failed` → `arm_failed` |
| `shaking` | `shake_dice`，超时 90 秒 | `robot.shake_dice.completed` → `stop_call`；`robot.shake_dice.failed` → `arm_failed` |
| `stop_call` | 播放 `audio/停.wav`（不等待）；`settle_dice`，超时 90 秒 | `robot.settle_dice.completed` → `analysis`；`robot.settle_dice.failed` → `arm_failed` |
| `analysis` | 视觉裁决 | `adjudication.result` → `result`；`adjudication.diagnosis` → `analysis_failed` |
| `analysis_failed` | 播报识别失败；`reset_home`，超时 30 秒 | `retry`（蓝）→ `analysis`；`new_round`（绿）→ `ready`；`back`（红）退出 |
| `result` | 按胜负播报双方点数；`feedback` 手势 | `new_round`（绿）→ `rehome`；`back`（红）退出 |
| `rehome` | `reset_home`，超时 120 秒 | `robot.reset_home.completed` 或 `robot.reset_home.failed` → `ready` |
| `arm_failed` | 播报机械臂失败；`reset_home`，超时 30 秒 | `retry`（蓝）→ `game_start`；`back`（红）退出 |

- 抓杯与 `game_start` 过场、`shake_countdown` 倒计时同时进行；`shaking` 下发的 `shake_dice` 在抓杯完成后执行。
- 「停」的播放与放杯同时进行，放杯完成后开始裁决。
- `result` 中「再来一局」先经 `rehome` 返回 HOME，再进入 `ready`。

# 组件包

`game/backend/components/` 下每个目录是一个组件包。服务启动时扫描并注册组件；游戏通过槽位选择组件，不直接引用具体实现。

## 当前组件

| 组件 id | 类型 | 槽位 | 功能 | 参数 |
| --- | --- | --- | --- | --- |
| `vision_yolov8_objdetect` | `vision`，角色 `adjudicator` | `vision_adjudicator` | YOLOv8 骰子识别与胜负裁决 | [参数](vision_yolov8_objdetect/parameters.md) |
| `tts_moss_nano` | `tts` | `tts_local` | 本地 MOSS-TTS-Nano 语音合成 | [说明](tts_moss_nano/README.md)、[参数](tts_moss_nano/parameters.md) |
| `robot_arm_spacemit` | `robot` | `robot_arm` | 执行机械臂命令，读取 `SITE/cup_application.json` | [配置参考](../../../docs/configuration.md) |

`SITE` 表示现场目录，默认 `~/.local/share/spacemit-manipulation/site/`。

## 组件选择

- 全局配置 `providers` 为所有游戏指定默认组件，见 [全局配置参数](../parameters.md)。
- 游戏 manifest 的 `providers` 覆盖全局值；台词的 `provider` 字段覆盖槽位选择，见 [摇骰子游戏参数](../games/dice/parameters.md)。
- 所有启用游戏只能引用同一个本地语音组件。

## 目录结构

```text
game/backend/components/<组件 id>/
├── manifest.json   # 组件声明
├── provider.py     # 入口类
├── config.json     # 组件参数；语音组件必须提供
└── scripts/        # 可选，生命周期命令
```

新增或删除组件后，执行 `mm` 安装并重启 `dice-arena serve`。

## manifest.json 字段

| 字段 | 说明 |
| --- | --- |
| `id` | 组件 id，只含字母、数字、`_`、`-`，须与目录名一致 |
| `type` | `vision`、`tts`、`asr`、`robot` 或 `command` |
| `role` | 仅 `vision` 使用：`adjudicator`（裁决）或 `localizer`（定位） |
| `name`、`version` | 显示名称与版本 |
| `enabled` | `false` 时不注册该组件，缺省 `true` |
| `entry` | 入口，格式 `模块.py:类名`，模块位于组件目录内；入口类的 `id`、`type`、`role` 须与 manifest 一致 |
| `capabilities` | 能力标签，字符串数组，不重复 |
| `config` | 组件目录内的参数文件，`tts` 类型必填 |
| `lifecycle.start`、`lifecycle.stop` | 可选，启停本地进程的命令数组，路径相对 `game/`，在 `game/` 目录下执行 |

## 接口

| 类型 | 基类 | 必须实现 |
| --- | --- | --- |
| `vision` / `adjudicator` | `core.vision.VisionAdjudicatorProvider` | `adjudicate(request, *, on_log, on_event, is_cancelled, timeout_seconds)`；可选 `start_streaming`、`stop_streaming` |
| `vision` / `localizer` | `core.vision.VisionLocalizerProvider` | `locate(request, *, on_log, on_event, is_cancelled, timeout_seconds)` |
| `tts` | `core.tts.TtsProvider` | `synthesize(payload)`，返回 WAV 与响应头；可选 `stream(payload, write_frame)` 分段输出 |
| `robot` | `core.robot.RobotProvider` | `grasp_cup`、`shake_dice`、`settle_dice`、`feedback(kind)`；`reset_home`、`ensure_home` 的缺省实现不执行任何动作，接入真机时须实现 |
| `asr` | `core.asr.AsrProvider` | 麦克风监听会话与识别结果回调；SDK 未包含该类型组件 |

- **裁决组件**：返回源画面中的物理结果 `LEFT`、`RIGHT` 或 `TIE`，玩家与机械臂的对应关系由游戏处理。失败时返回含 `"diagnosed": true` 的诊断结果。进度和结果通过 `on_event` 上报，`on_log` 仅输出诊断文本。
- **语音组件**：单次文本最多 4000 字符。
- **机械臂组件**：
  - 命令返回 `{"status": "completed"}` 或 `{"status": "failed", "reason": "..."}`，不向外抛出异常；
  - `is_cancelled()` 为真时尽快中止并返回失败；
  - `robot_arm_spacemit` 的结果手势、`reset_home` 和 `ensure_home` 不因取消而中途停止，以免机械臂停在 HOME 之外；
  - 进度通过 `on_event({"event": "robot", ...})` 上报。

## 生命周期与组件命令

`dice-arena serve` 启动游戏前，对配置引用的语音组件执行 `lifecycle.start`。
`dice-arena component` 使用与 `dice-arena serve` 相同的现场配置和运行目录管理组件：

```bash
dice-arena component list
dice-arena component health tts_moss_nano
dice-arena component selected vision_adjudicator --game dice
dice-arena component referenced tts
```

- 现场配置为 `SITE/dice_arena/config.json`，尚未生成时读取安装默认值。
- 语音服务的进程号和日志保存在 `SITE/dice_arena/`。

| 命令 | 作用 |
| --- | --- |
| `list` | 列出已注册组件及其健康状态 |
| `health <组件 id>` | 输出组件健康状态 |
| `start <组件 id>`、`stop <组件 id>` | 执行组件的 `lifecycle.start`、`lifecycle.stop`；未声明时不执行 |
| `selected <槽位> [--game <游戏 id>]` | 输出游戏在该槽位使用的组件 id |
| `start-selected <槽位>`、`stop-selected <槽位>` | 对槽位选中的组件执行启停 |
| `referenced tts` | 输出全局配置与启用游戏引用的全部语音组件 |

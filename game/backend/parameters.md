# 全局配置参数

全局配置描述部署级设置：组件选择、语音默认值、视频地址、待机与输入方式、屏幕方向，对所有游戏生效。
游戏玩法见 [摇骰子游戏参数](games/dice/parameters.md)，组件参数见 [组件包说明](components/README.md)。

下文 `SITE` 表示现场目录，默认 `~/.local/share/spacemit-manipulation/site/`。

## 配置文件与生效方式

| 文件 | 作用 |
| --- | --- |
| `SITE/dice_arena/config.json` | 现场配置，游戏运行时读取的唯一副本 |
| `game/backend/config.json` | 安装默认值，`mm` 安装到 `share/dice_arena/game/backend/config.json` |

- `dice-arena serve` 启动时，若现场配置不存在，则从安装默认值复制一份；启动时打印 `game configuration: <路径>`。
- 后端通过环境变量 `DICE_ARENA_CONFIG` 读取现场配置。重新安装不覆盖现场配置；修改安装默认值只影响新生成的现场配置。
- 直接编辑现场配置，保存后自动重载。内容无效时保留上一份有效配置，服务输出 `[arena] keep last good config: ...`。
- `providers.tts_local` 在服务启动时确定，修改后需重启 `dice-arena serve`；其余字段的生效时机见字段说明。
- 恢复默认值时，停止 `dice-arena serve`，删除现场配置后重新启动：

```bash
rm "$HOME/.local/share/spacemit-manipulation/site/dice_arena/config.json"
dice-arena serve
```

## 字段说明

默认值为 `game/backend/config.json` 中的值。

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `schema_version` | `1` | 固定为 `1` |
| `games_enabled` | `{"dice": true}` | 按游戏 id 启停，优先于游戏 manifest 的 `enabled`；未列出的游戏使用 manifest 的值。停用的游戏不在网页列表显示，也不能进入。刷新网页后生效 |
| `providers.tts_local` | `tts_moss_nano` | 本地语音合成组件，台词 `mode: tts_local` 使用。所有启用游戏只能引用同一个本地语音组件，否则服务拒绝启动。修改后重启 `dice-arena serve` |
| `providers.vision_adjudicator` | `vision_yolov8_objdetect` | 视觉裁决组件，下一次裁决生效 |
| `providers.robot_arm` | `robot_arm_spacemit` | 机械臂组件，读取 `SITE/cup_application.json`（由 `dice-arena configure` 生成）。未配置或组件不可用时机械臂命令返回失败，按状态机的失败路由处理 |
| `providers.tts_remote`、`providers.asr` | 未配置 | 远程语音合成与语音识别槽位；SDK 未包含对应组件 |
| `voice` | `default` | 默认音色；`default` 表示使用语音组件配置的音色 |
| `speed` | `1.0` | 默认语速；`tts_moss_nano` 仅支持 `1.0` |
| `video.webrtc_base_url` | `http://127.0.0.1:8889` | 浏览器播放实时画面的 WebRTC 地址（主机与 MediaMTX 端口），格式为 `http(s)://主机:端口`，不含路径和查询。从其他设备访问网页时改为 K3 的局域网地址。下一次进入游戏生效，不重建识别进程 |
| `asr_enabled` | `false` | 语音输入总开关。为 `true` 且配置 `providers.asr` 时，服务启动前预热语音识别组件，预热失败则拒绝启动 |
| `vision_always_on` | `false` | 识别视频流的生命周期。进入游戏时总是启动摄像头与推流（不推理）；`false` 时回合结束（退出、取消或出错）后停止，`true` 时保持到服务退出。每个回合开始时读取 |
| `standby.enabled` | `true` | 启用待机页 |
| `standby.idle_seconds` | `120` | 游戏列表页空闲多少秒进入待机，范围 5～3600。共享会话中，停在 `rules`、`ready`、`result`、`analysis_failed`、`arm_failed` 且无播报的回合空闲同样时长后结束，返回游戏列表 |
| `standby.boot_standby` | `true` | 打开网页时先显示待机页；`false` 时显示游戏列表 |
| `standby.wake_phrases` | `游戏`、`你好`、`在不`、`开始游戏`、`hello`、`wake up`、`start game`、`start the game` | 待机页语音唤醒词，命中后回到游戏列表；按键和触摸唤醒始终可用 |
| `game_select.phrases` | `dice`：`摇骰子`、`骰子`、`dice` | 按游戏 id 声明的语音选游戏词，在游戏列表页和待机页命中后直接进入该游戏，优先于唤醒词；未声明的游戏不能语音选择 |
| `game_select.confirm_phrases` | `进入游戏`、`玩这个`、`进入这个游戏`、`开始这个游戏`、`play this`、`enter the game`、`enter this game`、`start the game`、`start this game` | 游戏列表页进入当前选中游戏的语音词，等同绿色键；空列表表示关闭 |
| `display.player_side` | `RIGHT` | 网页上玩家所在一侧，见[屏幕方向](#屏幕方向) |
| `display.video_rotation_deg` | `{"dice": 0}` | 各游戏源画面转为玩家在左所需的网页顺时针旋转角度，取 `0`、`90`、`180`、`270`；未列出的游戏为 `0` |
| `input_board_enable` | `true` | 板端键盘与共享会话开关，见[板端键盘与共享会话](#板端键盘与共享会话) |

`standby.wake_phrases` 和 `game_select` 词表需要语音识别组件并开启 `asr_enabled` 才生效。
识别文本去除空格、转为小写后按子串匹配。

## 屏幕方向

- 识别使用源画面坐标：玩家固定在 `LEFT`，机械臂固定在 `RIGHT`，与屏幕显示方向无关。
- `player_side: "LEFT"`：网页显示玩家在左、机械臂在右。
- `player_side: "RIGHT"`：网页显示玩家在右、机械臂在左，视频在 `video_rotation_deg` 的基础上再旋转 180°，结果卡片同步换位。
- 显示方向只影响网页视频和结果卡片，不改变识别区域、点数归属和胜负播报。
- 修改后重新进入游戏生效，进行中的回合保持原显示。

## 板端键盘与共享会话

`input_board_enable: true` 时：

- 服务直接读取 `/dev/input/event*` 的按键：Enter 为绿色确认，Esc 为红色返回，↑ 为黄色，↓ 为蓝色。
- 运行服务的用户须属于 `input` 组，加入后重新登录：`sudo usermod -aG input "$USER"`。
- 板端按键、网页点击、网页键盘和语音输入进入同一个共享会话。所有网页通过 `GET /api/session`、`GET /api/session/stream` 和 `POST /api/session/actions` 共享选中游戏、回合状态和结果；并发确认只创建一个回合。
- 刷新或关闭单个网页不取消回合；全部网页断开 45 秒后结束回合。
- 台词由服务合成，经板端默认 PipeWire 输出播放，同时发送给网页播放；网页静音或播放失败不影响游戏进度。
- 待机页的第一次按键只唤醒到游戏列表；之后方向键选择游戏，绿色键进入。
- `dice-arena status` 输出中的 `board_input` 和 `shared_audio` 显示设备、权限与板端播放状态。

`input_board_enable: false` 时，服务不读取板端按键，各网页直接创建回合，同一时间只保留最新创建的回合。

修改该开关后，服务在 2 秒内启停按键读取；共享会话模式在当前回合结束、返回游戏列表后切换。

## 优先级

| 参数 | 优先级（高 → 低） |
| --- | --- |
| 组件槽位 | 台词的 `provider` 字段 > 游戏 manifest 的 `providers` > 全局 `providers` |
| `voice`、`speed` | 台词字段 > 游戏 manifest > 全局配置 |
| WebRTC 地址 | 游戏 manifest 的 `vision_profile.video.webrtc_base_url` > 全局 `video.webrtc_base_url` > 识别进程配置的 `video.webrtc_base_url` |
| 语音输入开关 | 仅全局 `asr_enabled` |
| 视频流生命周期 | 仅全局 `vision_always_on` |

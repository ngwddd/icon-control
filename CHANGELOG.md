## [0.4.3] - 2026-10-27

**快慢双层导航：把我从内环挪到外环。**

用户原话：「你就做不到像那个实时屏幕共享的实时读取了。就是提高你的思考回馈路径。
可以设计点新东西，干什么都行，能解决这个问题就行。」

### 问题的数学
```
模型      0.2–0.5 次/秒决策（每次 2–5 s 生成）
人类/豆包  20–60 次/秒视觉伺服
差距 100×  —— 把 sense() 从 10 ms 压到 1 ms 也救不了，瓶颈是 token 生成
```

### Added `navigator.py`（三层）
| 层 | 类 | 职责 | 频率 |
|---|---|---|---|
| M1 | `WorldState` | 画面 → 结构化状态（小地图网格 / 玩家格 / 目标格 / 提示 / 电量） | 15–20 Hz |
| M2 | `Servo` | 目标格 → 动作（每步重算方位误差并修正） | 20–30 Hz |
| M3 | `Supervisor` | 跑计划，只在「达成/卡住/不确定/新事件」时回到模型 | 事件驱动 |

**三个关键设计**
- **小地图自动标定**：列投影求格子间距（实测 10.5 px），不硬编码坐标
- **朝向自校准**：不读罗盘 —— 走一小步，看玩家标记在地图上的**位移方向**，
  就得到朝向（`Servo.estimate_heading`），任何有地图的游戏都能用
- **只在卡住时交回**：`approach` 防振荡（连续 6 步没更近就退出），
  `Supervisor` 返回一页状态文本（<300 token），不是一张图

### 新工具（73 → 76）
`world_state` / `servo`（calibrate·face·approach·forward·turn）/ `navigate`（跑计划）

### 单测抓出的 3 个真 bug
| bug | 现象 | 修法 |
|---|---|---|
| 角度符号反了 | 转完朝向变成 `2*have - want`，越走越远 | `face_deg(-diff)`（鼠标右移 = 数学角减小） |
| stuck 检测错 | 拿 `history[-1]` 比 `history[-3]`，"转向+前进"交替被误判成卡死 | 只比较相邻两次 |
| 对角振荡 | 在 `(8,2) ↔ (6,4)` 之间来回晃，dist 恒 1.41 | 容差 1.0→1.5 + 6 步无进展就退出 |

### Tests
118 → **127**（新增 `tests/test_v06_navigator.py` 9 项：地图解码 / 朝向自校准 /
走到目标 / 卡住上报 / 计划完成 / 卡住交回 / 急停中止）

## [0.4.2] - 2026-10-27

**新增保留策略：这个助手跑起来不再产生垃圾文件。**

用户原话：「你要考虑我以后这个鼠标助手跑起来不会产生垃圾文件。」

问题不是「有临时文件」，而是**没人负责删**：`_draw/` 每次截图都多一张、
`recordings/` 每次录制一个目录、`%TEMP%` 崩一次留一堆。

### Added — `retention.py`
```
区域                上限                      超了删什么
_draw               80 个文件 / 80 MB / 3 天   最老的先删
recordings          10 个目录 / 300 MB / 7 天  最老的目录整个删
vision/baselines    40 个文件 / 30 天          最老的先删
%TEMP% 自己的东西   vh-* / canity_* / t_*.py   超过 6 小时的
```
**资产永不删除**：`macros/`、`recipes/`、`templates/`、`vision/glyphs.json`、`_patched/`。

### 什么时候自动跑（不用你记得清）
- `capture_daemon start` —— 每次开始接管屏幕时
- `snapshot` 写完图之后
- `record` 存完录制之后

### 新工具
- **`housekeeping`**：`action=status` 看用量（只读）、`action=sweep` 清扫（可 dry_run）

### Fixed
- `%TEMP%` 清理名单里**移除了 `dsh-`**：那是 DSH 宿主自己的临时目录
  （`dsh-spill-*` / `dsh-subprocess-*`），删了会影响运行中的会话
- `templates/` 一度被写进"可裁剪"策略里 —— 它是资产，测试当场抓出来了

### Tests
108 → **118**（新增 `tests/test_v05_retention.py` 10 项：按数量/天龄裁剪、
最新保留、资产不动、录制目录上限、%TEMP% 只碰自己前缀、housekeeping 契约）

## [0.4.1] - 2026-10-27

补上 v0.4.0 漏掉的东西，并让仓库自带的测试第一次真正跑通。

### Added
- `doctor.py`（环境体检，6 组检查）与 `panic_watch.py`（急停看守进程）——
  这两个文件 v0.4.0 没跟进来，仓库里的不变量测试一直在等它们
- `tests/_bootstrap.py`：没有装 `computer_mcp` 的机器上，整组测试**明确跳过**
  （以前是几十个 ImportError，把「没环境」误报成「测试失败」）

### Fixed
- 仓库测试的 `PROJECT` 解析：优先 `DSH_DESKTOP_MCP` → 本机默认位置 → 跳过
- `test_copies_match`：区分「未脱敏文件必须字节相等」与「脱敏文件只查结构」——
  发布版把真实应用名换成了中性示例（ChatClient / app-01_send），
  要求字节相等是误报
- `test_sanitized_keeps_public_api`：新增，脱敏可以改名但不能删公开接口
- 过期断言：`auto_bot*.py` 已移除 → 缺失时跳过；配方清单改为按实际文件校验

### Tests
仓库测试 **109 项**（跳过 7）在本机 venv 下全绿。

## [0.4.0] - 2026-10-27

架构升级：**把"看屏幕"从每动作一张图，改成常驻采集 + 端上感知 + 端上闭环**。

### Added — 采集守护
- `capture_daemon.py`：常驻线程按 12~20 fps（静止时降到 3~5 fps）抓屏，
  缩放到 0.5 放进 120 帧环形缓冲；每帧算平均差异、脏区矩形、哈希、前台窗口标题
- 隐私护栏：命中"密码/登录/凭据/1password"等标题的帧**不保存像素**
- `wait(predicate)`：事件等待，替代"sleep + 再截图"

### Added — 感知原语（0.1~3 ms）
- `perceive.py`：`prompt`（亮字占比）、`bar`（彩色条填充率）、`openness`（视野开阔度）、
  `color_blob`、`diff_region`、**`locate_rows`（按颜色自动定位 HUD 行）**
- 实测：`probe(prompt)` 0.155 ms、`probe(openness)` 0.301 ms、
  `sense()` **0.010 ms**（读内存）

### Added — 数字识别（P2）
- `digits.py`：切字 → 归一化 5×7 → 模板匹配；内置 0-9 标准点阵 + **运行时学习**（`glyph` 工具）
- 实测读像素字体 1.3~2.6 ms；Windows OCR 在同一 HUD 上读出 "L E E L 1" 且要 120~180 ms

### Added — 端上闭环（P1）
- `micro.py`：微脚本解释器（key/press/turn/move/click/sleep/loop/if/until/log），
  条件在本地求值，带步数与时长预算、嵌套深度上限
- 实测：41 步闭环 **0.41 s**（走模型往返约 123 s）

### Added — 工具与证据
- 14 个新工具（58 → 72）：`capture_daemon` / `sense` / `watch` / `probe` / `hud` /
  `snapshot` / `run_script` / `act_until` / `frame_mark` / `frame_diff` / `trace` /
  `glyph` / `read_digits` / `record`
- `record` 把环形缓冲落盘（JPEG q80，实测 PNG 9.4 MB → JPEG 0.3 MB 量级）

### Fixed
- 数字读取默认走**全分辨率区域抓取**（缩放帧上的字形太小，5×7 会抹平）
- `hud` 自动定位：窗口从 806×640 变成 537×427 后，硬编码坐标当场失效

### Tests
- 新增 `tests/test_v04_live.py`：22 项（原语 / 数字 / 解释器 / 守护 / 工具契约）
- 合计 **86 → 108** 项，venv 与系统 Python 双绿

## [0.3.2] - 2026-10-26

修复脱敏脚本造成的**语法错误** —— 发布之后由验证助手 v1.10.5 扫出来的真问题。

### Fixed
- **环境变量名被替换成中文**：`DSH_E2E` 曾变成 `对话壳（***）_E2E`，成了非法标识符 → 还原 ASCII
- **类名被替换成中文**：`TestBilibiliRecipe` 一类同样被替换 → 统一改为 ASCII 命名
- **失效引用**：`recipes/***.json` 指向不存在的文件 → 改指真实的 `app-03.json`
- 影响 33 个文件；修复后全仓 `ast.parse` 通过，验证助手判定 PASS

### Changed
- 版本 0.3.2

# Changelog

所有改动记录在此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.3.1] - 2026-10-26

修 v0.3.0 里三个会让通道「看起来接了、其实没通」的问题。

### Fixed
- **客户端模块改动不随刷新生效**：DSH Host 缓存了 client 模块，F5 无效。
  → `_authorized` 改为**来源校验（Origin 或 Referer）**，无 token 也可接受，
  这样 Host 里那份旧模块也能立刻上报；带 token 的请求一旦出现，自动收紧为「只收带 token」。
- **图片信标没有 Origin**：`<img>` 请求不带 Origin，只靠 Origin 校验等于对任何站点敞开。
  → 加本机 token（`state/bridge-token.txt`，不进源码/仓库；仓库里只有 `__BRIDGE_TOKEN__` 占位符）。
- **client.js 被写成乱码**：读写文件时混用了系统编码。
  → 整文件按 UTF-8 重写，并加体检（UTF-8 合法性、token 存在性、`/beacon?k=` 存在性）。

### Added
- `GET /beacon?k=<token>&granted=1|0` 图片信标通道：不受 fetch 的 CSP/CORS 限制
- 心跳从「组件 effect」提到「插件级」：热重载/重挂不会再把它清掉
- `visibilitychange` / `focus` 补发：Electron 节流后台定时器时尽快恢复
- 桥日志记录 `REJECT`（路径 / 来源 / token），排查时不用猜

### Changed
- 测试仍 **86 项**（断言已跟上新实现：`DEFAULT_PORT` / `const BRIDGE` / `/beacon`）

## [0.3.0] - 2026-10-26

把「有没有授权」从**看屏幕像素**改成**走程序层通道**。

### Added — 授权状态通道（本地桥）
- `computer_mcp/permission_bridge.py`：只听 `127.0.0.1:18765` 的小服务
  - GUI 插件每 5 秒把真实授权状态 POST 过来，Host 直接读状态文件
  - **无 token**：改校验 `Origin`（只接受 `dsh-app://` / `file://` / `127.0.0.1` / `localhost`）
    —— token 写死在源码里，发布即公开；Origin 由浏览器设置，普通网页改不了
  - 只写一个 JSON 状态文件，源码里没有任何执行命令的调用
- 客户端插件：挂载即上报 + 5 秒心跳 + 点击立即上报（`no-cors` 简单请求，无预检）
- 闸门（`permission.py`）**桥优先**：新鲜桥状态 0.1 ms 直接用；桥没起来会**自愈拉起**；
  OCR 仅作后备，且有效期从 45 s 缩到 **15 s**（桥挂了不会一直"以为已授权"）

### Fixed — 一个方向最危险的假阳性
- 旧实现里扫描区域第三条是 `(0,1000,2560,440)`（整个窗口下 1/3），
  OCR 会读到**聊天正文里**的「鼠标·已授权」字样，再撞上一处绿色像素 → 判成已授权
- 修法：扫描区收窄到输入框工具栏（高度 ≤ 200）；正面判定必须
  「检测到绿色胶囊」**且**「文字含 鼠标 + 已授权」同时成立；否则 unknown → 按未授权处理
- `tools/mouse_permission.py` 不再自己 OCR，改为调 `permission.status()`，与闸门同源

### Changed
- 测试 **75 → 86** 项（新增 11 项守桥：模块常量、写入/读取、无秘密、Origin 校验、
  TTL 短于 OCR、新鲜状态不触发 OCR、过期状态不信任、插件三处上报、CLI 同源、扫描区高度）
- 工具数仍 **58**（桥是支撑进程，不是 MCP 工具）

## [0.2.0] - 2026-10-25

把 v0.1 的"能力面"补成"可治理面"：**授权下沉到执行点**、**验证变成分级留证**。

### Added — 权限硬闸门（Host 侧）
- `computer_mcp/permission.py`：输入类工具的**统一闸门**
  - 未授权时在 `call_tool` 路由之前直接返回结构化拒绝，**不产生任何鼠标/键盘动作**
  - **fail closed**：读不到授权状态时按未授权处理
  - 45 s 缓存（命中约 0 ms，不给每次点击加 IO）
  - `DSH_MOUSE_GATE=off` 仅供自动化测试关闭；`DSH_MOUSE_STATE` 可指向别的状态文件
  - 状态来源：GUI 上那个「鼠标·已授权 / 未授权」胶囊（OCR 读取），只读不写
- 覆盖 19 个输入类工具（`click` / `type` / `key_press` / `batch` / `macro_run` / `ui_click` /
  `click_template` / `hover_probe` …）；只读工具（截图、OCR、模板匹配、状态查询）不受影响

### Added — 分级验证 `verify_flow`
- 新工具 `verify_flow`：**按级验证、遇错即停、每级留证据**
- 五种断言：`text`（区域 OCR + 容错）/ `template`（模板命中）/ `baseline`（基线偏离）/
  `stable`（连采稳定）/ `file`（存在 + 内容包含）
- 报告含每级耗时、每条断言的具体证据（OCR 片段 / 置信度 / diff / 文件大小）
- `stop_on_fail=False` 时跑完全部，`failed_stage` 记**第一处**失败，`failed_stages` 记全部
- 可写 JSON 报告留档（`report_path`）
- 只做验证、不做动作 —— "动作做了没生效"与"根本没做"能在报告里分开

### Changed
- 工具总数 **57 → 58**
- 测试 **64 → 75** 项（新增 11 项守闸门与分级验证）
- `verify_flow` 的失败语义修正：多级失败时 `failed_stage` 不再被最后一级覆盖

### Fixed
- 清掉 6 处未使用的 import（两个演示脚本 / 三个测试文件）
- 探测性 import 显式标注用途，避免静态检查误报

### Docs
- 文档与示例统一脱敏：应用名以「软件性质（***）」表示，不含个人信息

## [0.1.0] - 2026-10-25

首个公开版本。能力面打通：**能看、能点、能验、能停、能授权**。

### Added — 采集与感知
- 采集层重写：默认 0.5 倍缩放 + JPEG q75，单次截图 **128 ms → 61 ms**、**962 KB → 121 KB**
- `screen_state`（不带图，43 ms，回报 changed / diff / hash）
- `wait_for_change`（事件驱动等待，替代模型轮询）
- `capture_config`（运行时改 scale / quality / format / diff_threshold / mask_bottom）

### Added — 执行层
- `batch`：一串动作合成一次调用（20 步协议层 2 ms，往返 20 → 1）
- UI Automation 五件套：`ui_tree` / `ui_find` / `ui_click` / `ui_invoke` / `ui_set_text`
- 宏引擎 `macro_run`：相对坐标、`anchor:"br"`、`expect` 校验、自动 restore、越界拒点、
  `retry` / `repeat` / `ensure_chat` / `assert_text` / `assert_file` / `clipboard_*` / `paste`
- OCR 三件套：`ocr_read` / `find_text` / `click_text`，支持 `upscale` + `boost` 认小字与灰字

### Added — 视觉状态判据（本版核心）
- `capture_template` / `match_template` / `wait_template` / `click_template`：灰度模板自学 + 匹配
- `set_baseline` / `diff_baseline` / `wait_baseline_change`：区域偏离基线的程度
- `sample_stable`：连采多次一致才算数，防动画中途误判
- `hover_probe`：悬停 → 等待 → 比较 → 移开，识别"悬停才出现"的控件
- `vision_list`：模板/基线清单 + 运行统计（calls / failures / retries / failure_rate）
- 工具总数 **31 → 57**

### Added — 应用生命周期
- `appkit.launch`（走 Explorer shell，规避 Electron 静默秒退）
- `appkit.wait_window` / `appkit.exit_app`（关窗 ≠ 退出，托盘进程显式结束）
- `appkit.activate`（AttachThreadInput 强攻前台，SetForegroundWindow 常被拒）

### Added — 安全
- 急停：`panic.PanicSwitch`（1.5 s 内连按两次 ESC 立即硬停，粘住不复位）
- `panic_watch.py`：进程外看守，触发即杀掉所有自动化进程
- 鼠标接管授权闸门：GUI 插件 `@local/dsh-mouse-permission`（灰色 = 无权限 / 绿色 = 可接管）
  + 只读检查器 `mouse_permission.py`（退出码 0 / 2 / 3）

### Added — 工程保障
- 64 项不变量测试，系统 Python 与 venv Python 双跑全绿
- `doctor.py` 六组体检（身份 / 显示 / 输入 / 驱动 / 补丁 / 记忆库）
- `diag_input.py`：用"TextEditor打字 + 剪贴板回读"当唯一可信判据
- `clean.py`：白名单清理临时文件，不碰宏、补丁、用户目录
- `recipes/`：每个已验证应用一份配方（ChatClient / 某ChatApp / GamePlatform / SecurityApp / TextEditor / VideoClient / MusicClient）
- `_patched/reapply.py`：重装依赖后一键重放所有补丁

### Fixed
- `_patched/appkit.py` 与安装副本漂移（旧版 14,653 B 缺评分匹配、启动前校验、`activate`）→ 已同步并留备份
- 补丁脚本全部改为"先 assert 旧片段存在再替换"，避免静默失效
- 截图变化检测默认遮掉底部 60 px，否则任务栏时钟会让静止画面被判成一直在变

### Known limitations
- 仅在 Windows 11 验证；DPI 150% 下必须 `SetProcessDpiAwareness(2)`
- 授权闸门的状态存在浏览器本地（客户端无法直连 Host），agent 通过读界面文字判定
- 第三层（逆向）默认关闭，需要逐次授权

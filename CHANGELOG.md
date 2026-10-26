## [0.8.1] - 2026-10-27

**真实任务跑出来的三处修正（微信 / Steam / QQ）。**

### 修的

| 修正 | 依据 |
|---|---|
| Steam 订阅验证改读 `workshop_log.txt` | ACF 的 mtime 停在 03:53，而订阅发生在 03:55（滞后 2 分钟），用它判断会误判"没订上" |
| 依赖弹窗用**固定坐标**点「仅订阅此项目」 | 弹窗打开时页面不响应悬停，OCR 判它是否打开会漏判 |
| 取消订阅 = 再点同一个绿按钮 | 日志会写 `Unsubscribed from item` + `removing unused item` |
| `selector.score_line` 支持**截断前缀** | 微信会话行显示成「文件传...」，query「文件传输助手」原本匹配不上 |
| `selector` 支持 OCR `upscale` | 输入框占位符是灰字，1× 读不出（ocr_read 支持 upscale/boost） |

### 实测记录

```
微信  03:52「自动化验证 · 软选择器跑通」已发出（主窗口流程）
      method 统计：会话行=rel，输入框=rel → 软选择器在该界面尚未生效（已修）
Steam 03:55 订 2 张（the awakend army / Pumpkin Patch），03:55:52、03:55:56 全部取消
QQ    QQNT 没有可用窗口，且按键落到 QQ音乐 → 跳过硬编码
```

### 测试

214 → **217** 项（selector 17 项，新增截断/前缀 3 条）
## [0.8.0] - 2026-10-27

**第 1 步落地：软选择器（selector）—— 按语义找控件，找不到才退回坐标。**

用户要求：「先做小、能验证的那一步；可以用就放大，不行再想办法。」

### 新增 `selector.py`

```
三级降级：text（OCR 找那一行）→ template（cv2 匹配图标）→ rel（比例坐标兜底）
返回值带 method，便于统计"退化率"（rel 占比高 = 这套在该应用上没起作用）
```

动作里这样用：
```json
{"kind":"click","find":{"text":"文件传输助手","within":[0.06,0.1,0.24,0.9],"rel":[0.142,0.331]}}
```

### 可复现 A/B（`tools/selector_demo.py`）

自己开 Tk 窗口当靶子，量一次 → 挪走+改尺寸 → 三种各点一次，**由被点窗口自己记账**：

```
A 硬坐标（旧绝对位置）   ✗ 点空
B 软选择器·文本          ✓ 命中「发 现」score=1.0
C 软选择器·模板          ✓ 模板 score=1.00
```

### 做的过程中踩到并修掉的两个真 bug

| bug | 现象 | 修法 |
|---|---|---|
| OCR 行是扁平 `{text,x,y,w,h}`，我按嵌套 `rect` 取坐标 | 文本选择器永远失败（但 OCR 明明读到了） | `_geom()` 兼容三种形态 |
| `cv2.imread` 读中文路径返回 None | 模板永远匹配不上，还不报错 | `imdecode(np.fromfile(...))` |

（另外：Tk 不能跑在子线程 → 演示脚本改成双进程；子进程残留会互相覆盖 state → 每轮独立文件名）

### 测试

213 → **216** 项（`test_v11_selector.py` 15 项：文本归一化/LCS、候选打分、
同分选小控件、within 过滤、rel 兜底、嵌套 rect 兼容）
## [0.7.0] - 2026-10-27

**把这几轮实验里所有弱点和踩坑，全部收进 skill（9 个分册）。**

用户原话：「会踩坑的那些东西、记忆库那些东西、agent 那些东西，还有这几次实验下来的
那些弱的东西缺点，全部写进优化之后的 skill 里。」

### 新增两个分册

| 分册 | 内容 |
|---|---|
| `references/pitfalls.md` | **事实**：启动（ShellExecuteW vs cmd start 管道）、窗口（鬼影/SW_HIDE 毁输入）、DPI、输入（丢字/对话框/UWP）、Shell（UTF-8/解释器/pip/curl）、性能（实测毫秒数） |
| `references/failures.md` | **我的病历**：30 条「症状 → 真因 → 正确做法」，分 A看/判断、B时间、C状态输入、D工程流程、E收尾 |

### SKILL.md 重写

```
顶部加「失败模式速查」10 行表（卡住先看这张）
核心循环 / 三条铁律 / 判活三连 / 输入方式 / 工具分层 / 收尾 / 分册索引
```

### 分册补写（这轮真跑出来的）

- `wechat.md`：**会话开在独立窗口里**（标题=聊天名，919×971）—— 点会话行后主窗口右侧
  永远是空白，看起来像"没反应"。附实测发出的完整流程。
- `train.md`：v0.7 实战补丁 9 条 —— 每步置顶+置前、scroll 的 `at_rel_frac`、
  `changed` 改锁存、第一帧不算变化、文本归一化+LCS、默认整窗、对话框特征词、
  ShellExecuteW 启动、滚动类判据用 `stable`。

### 这次迁移掉的 AGENTS.md 内容

```
长期记忆约定 / 清理与保留策略 / 验证助手用法 / 本机工具链与解释器 / UTF-8 改文件规则
→ 全部进 references/toolbox.md
AGENTS.md 只留指针 + 用户偏好
```

### 测试

199 / 200 项全绿（desktop-mcp / 仓库）
## [0.6.1] - 2026-10-27

**修 0.6.0 的一个致命命名 bug + 加一次性自测脚本。**

### bug：`self._stop` 覆盖了 `threading.Thread._stop()`

```
FrameWheel 里把停止事件命名为 self._stop
→ Thread.join() 内部会调用 self._stop() → TypeError: 'Event' object is not callable
→ 任何 track/selfcheck 在收尾时崩溃
```
单元测试抓不到（它们不启动真线程），是**一次性自测脚本第一枪**打出来的。
改名 `_stop_evt`。

### 新增 `tools/track_oneshot.py`（用户只需要跑这一条）

```
① 抓帧自检 6 秒      → fps / 环形上限 / 线程异常
② 记事本轨道 3 步    → 点击 → 粘贴 → 文本断言 → 稳定
③ 看门狗演练         → 故意超预算，验证会报异常并在 2 次后停车
④ 清理               → 关掉记事本
退出码 0=全过；11 项检查
```

### 实测（自测脚本输出）

```
① 27.8 fps · 环形 167 帧 / 3490 KB（有上限）· 线程无异常
② status=done · 3/3 步 · 0.8 秒 · 异常 0 · 对话框 0 · 拼图 6 KB
③ anomalies=2 · status=stall · 2.0 秒停车
```
## [0.6.0] - 2026-10-27

**列车（track）：三轮回转 + 看门狗。用户原话：「指令是轨道，截图是轮子，
车要一直开，不是做一次卡一次。」**

### 新增 `train.py`（三层轮子，一个工具）

```
轮子1 入帧   抓**目标窗口**（不是全屏）+ numpy 块平均 → 灰缩小图 + JPEG → 环形缓冲
轮子2 处理   差分 → 变化块 → 状态机 STABLE/TRANSITION → 事件（SETTLED/STALL/ANOMALY）
轮子3 出     最新稳定帧 + 变化块拼图 + 事件时间线（交回模型的约 7–30 KB）
看门狗       每步 budget_ms；>3× 判异常并出拼图；连续 2 次异常停车
对话框检测   OCR 读到「是否保留/要创建新文件/另存为…」→ 记 ANOMALY，别再无脑重试
```

**工具只加 1 个**：`track(action=run|start|status|stop|selfcheck)`。
`start` 后台跑，`status` 随时取新鲜摘要（含一张新拼图）——我思考期间车不熄火。

### 实测（2560×1440，本机）

```
抓帧        29.8 fps（目标 30）   单帧 18.2 ms = 抓窗口 13.7 + 块平均 4.5
环形缓冲    150 帧 / 0.4–0.7 MB   恒定（帧上限与字节上限都验证过）
进程内存    128.5 MB，60 秒一条直线，不增长
3 步轨道    0.9 秒跑完（点击 → 粘贴 → 文本断言 → 稳定）
看门狗      6.1s / 7.5s 准确触发（2.0s / 2.5s 预算的 3 倍）
```

### 这轮修掉的 5 个真 bug（都是自测抓出来的）

| bug | 现象 | 修法 |
|---|---|---|
| OCR 每 20 ms 调一次 | 全车被拖慢，判据挤占抓帧 | 贵判据限频 150 ms |
| 文本直接 `in` 比对 | OCR 把 `TRACK-OK-2152` 读成 `TRACKOK2152` → 永远不成立 | 归一化 + LCS 0.8 |
| `region` 写小 | 把目标排除在区域外，静默失败 | 不传 region 默认整窗 |
| 记事本残留「是否保留更改」 | 后续按键全被吞 | 自动识别模态对话框并报 `dialog_hits` |
| 全屏抓 + PIL 缩放 | 17.8 fps，且我一度以为方案不可行 | 抓窗口 + numpy 块平均 → 29.8 fps |

### 测试

162 → **199 项**（`test_v10_train.py` 37 项：块平均 / 变化块 / 环形上限 /
事件上限 / 看门狗阈值与停车 / 轨道解析 / 拼图 / 文本归一化与 LCS）
## [0.5.1] - 2026-10-27

**修 0.5.0 的自测断链：规则搬走后，仓库里那条不变量还在看 AGENTS.md。**

验证助手直接判 FAIL：
```
测试【高】退出码 1
  test_agents_md_mentions_close_windows → 断言 AGENTS.md 里有「关窗/收尾」
```

### 修法（两边都改，不是放宽断言）

1. **测试跟着规则搬家**：改成 `test_rules_live_in_skill_not_agents_md`
   - 规则本体必须在 `skill/desktop-operator/SKILL.md`（含收尾/关窗）
   - `AGENTS.md` 必须留 `desktop-operator` 指针（断链也算失败）
2. **skill 补上确切词**：§5 收尾原来写"关掉/最小化"，没有 `close_windows`/「关窗」这两个词。
   改成写明 `close_windows`（只发 WM_CLOSE，不杀进程）与「关窗」，并补上边界
   （只关自己开的窗口、有未保存改动先问用户）。

### 结果
```
仓库测试 163 项 OK（skipped 7）
```
## [0.5.0] - 2026-10-27

**新增 Skill `desktop-operator`：把「规则」从 AGENTS.md 搬进可复用的技能，随本包一起发布。**

用户原话：「你缺一个 SKILL……把规则从 AGENTS.md 里删除，迁移到这个 skill 里，
然后把它一起上线开源平台，跟这个 MCP 在同一个包里面。」

### 为什么搬

AGENTS.md 里光桌面部分就 22 KB，越堆越长、每次都要整份加载，而且**混在通用记忆里**。
搬到 skill 后：
```
AGENTS.md   31.2 KB → 8.3 KB  （-73%）
skill       一个入口 + 4 个分册，按需读，不再每次全量加载
```

### 包内结构

```
skill/desktop-operator/
  SKILL.md               入口：开工顺序 / 三条铁律 / 判活三连 / 假阴性清单 / 工具分层
  references/wechat.md   微信 4.x：进入微信面板、主窗口比例坐标、发消息、朋友圈
  references/steam.md    Steam 创意工坊：卡片网格、+ 位置、只点一次、ACF 验证
  references/uwp-cef.md  UWP(记事本)/CEF/Electron 的通用判据与陷阱
  references/coords.md   DPI、四种坐标系、rel_frac、判活三连、读图预算
```

### 安装（一条命令）

```powershell
Copy-Item -Recurse "图标控制\skill\desktop-operator" "$env:USERPROFILE\.dsh\skills\"
```
装好后在 DSH 里直接说「帮我给微信发…」就会命中它。

### 这次迁移掉的（AGENTS.md）

```
· 开工顺序（配方 → 宏 → 工具 → 手写）
· 接管桌面 / 桌面 MCP 是手和眼
· 急停约定、鼠标授权开关说明
· v0.4 采集守护、快慢双层导航、布局标定与记忆
· 微信窗口唤不醒三条硬规则
→ 全部并入 skill（内容保留，位置变了）
```

### 同时修掉

- `diag_input.py`：L3 打不进去时不再断言「被系统拦截」，改判 **UNKNOWN** 并列出假阴性排查项
- `recipes/wechat.json`：补上实测通过的 15 步流程与比例坐标

## [0.4.5] - 2026-10-27

**把「零件」装回「会走路的车」。用户原话：「怎么感觉还变弱了呢？给他全部修好。」**

### 诊断
底层确实快了 100-300 倍（sense 0.010 ms / probe 0.155 ms / 41 步 0.41 s），
但任务级效率退步：

   微信发两段    宏本来 4.7 s    实际绕 1 小时（DPI、鬼影窗口、重复实例）
   Steam 订地图  配方本来 3 步   实际 1 小时只订上 1 张（还点两次取消了 1 张）

根因：新层与旧路（配方+宏）并行、入口没有仲裁、配方里的事实没沉淀进代码。

### 修法一：按比例坐标（让旧宏抗缩放）
宏引擎新增 `rel_frac: [fx, fy]` 与 `region_frac: [fx, fy, fw, fh]`（0~1）。
旧宏用绝对像素，窗口从 600x700 变 1566x1054 后 `type_verified` 整体偏移而失败。
新增 `macros/wechat_send_frac.json`：ensure_chat -> 点输入框（按比例）-> 剪贴板粘贴
-> 回车 -> 断言气泡。任何窗口尺寸都能用。

### 修法二：配方里的事实变成机器可读
`recipes/steam.json` 新增 `workshop_subscribe`：
卡片网格（按窗口宽的比例）、+ 按钮在缩略图右下角（0.776, 1.19 of card）、
每张只点一次（再点就是取消）、验证走 appworkshop_<appid>.acf + content/<fileid>、
依赖弹窗三个按钮的比例坐标。

`recipes/wechat.json` 新增 `send_message`（按比例路径）与 `window_sizes_seen`。

### 修法三：入口仲裁写进 AGENTS.md 第一条
    ① 配方有 -> 照抄   ② 宏有 -> macro_run   ③ 都没有 -> 才用新层   ④ 再没有 -> 手工
工具分层：78 个里只有 6 个是入口（macro_run/batch/ocr_read/find_text/layout_mem/sense）。

### 修掉的 bug
- 宏占位符 `${text_assert}` 没有默认值 -> 不变量测试抓到，改用 `${text}`
- `layout_mem.py` 未使用的 `import os` -> 验证助手 imports 检查抓到

### Tests
154 -> **162**（desktop-mcp）/ 163（仓库）：新增 `test_v09_frac_coords.py` 8 项
（按比例坐标在两种窗口尺寸下的换算、绝对 rel / br 锚点回归、区域最小 1px）

### 验证
    desktop-mcp  verify_start -> PASS（0 未回应）
    图标控制      verify_start -> PASS（收敛）

## [0.4.4] - 2026-10-27

**布局标定与记忆（走 A 路线）：看一眼 → 记住 → 复用。**

用户原话：「我要改的是通用的……我要提升自己的综合能力，不是专项化能力。
我就喜欢搞这种革命性的，而不是按着一个架构一直改。」

### 为什么不做「自动识别布局」
实测（3 张真实截图，四个探测器）：
```
内容区（去黑边）   应该 806x640      → 判成整窗 1233x1019
HUD 文字行         应该 3 行          → 0 行
网格面板（小地图） 应该 pitch≈11      → 0 个 / 误报 pitch=4
进度条             应该 2 根          → 12 根（全是抗锯齿噪线）
```
结论：纯像素启发式打不过真实画面，再调阈值只是对单张图作弊。
`screen_model.py` 保留为**实验性**（默认关闭，docstring 写明实测结论）。

### Added `layout_mem.py`（通用，不绑应用）
```
① 人对着一张截图看一次，报 4 个区域的**归一化坐标**（相对画布 0~1）
② 存成档案，键 = 应用名（标题去版本号）+ 画布尺寸
③ 之后窗口缩放/移动 → resolve 按档案换算成像素框，每次 0 成本
④ 换应用 = 再看一次（2 分钟），不是"再写一套常量"
```
两种缩放模式（这是踩出来的）：
- `fixed`（默认）：程序以固定尺寸绘制并贴左上角（游戏常见）→ 用档案画布，不按客户区裁剪
- `fit`：随窗口拉伸（编辑器/浏览器）→ 用当前客户区

### 新工具（76 → 78）
- **`layout_mem`**：`save` / `list` / `resolve` / `delete`
- `world_state` 现在会自动套用匹配的档案（调用时不用再传坐标）
- `screen_layout`：通用布局探测（实验性）

### 端到端验证（真实游戏窗口，800x600 客户区）
```
save  → key=canity, regions={map,prompt,bar,hud}
resolve → map=[1410,772,268,248] prompt=[1128,878,298,47] bar=[1005,928,189,22]
裁图核对 → hud 区域正好是 LEVEL 1 / SANITY 4% / FUSES 0/2 ✅
```

### Tests
137 → **154**（`test_v08_layout_mem.py` 15 项：去版本号 / 区域校验 /
存取 / 匹配 / fixed 与 fit 两种缩放 / 最小 1px；另加 clamp 回归）

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

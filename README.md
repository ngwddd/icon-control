# 图标控制 · Icon Control

> **一个把"让 AI 真正接管你的鼠标和屏幕"做成可落地产物的项目。**
> 不是又一个截图 + 坐标点击的 demo —— 它有性能基准、有验证纪律、有急停开关、有界面上的授权闸门，
> 并且每一条规则都是被真实任务打出来的。

- **版本**：v0.2.0
- **平台**：Windows 11（2560×1440 @150%）
- **底座**：[computer-mcp](https://github.com/)（MIT，31 个工具）+ 本项目补丁层扩到 **72 个工具**
- **对话壳**：Shell（Shell）Web GUI
- **许可证**：MIT

---

## 它解决什么问题

通用 agent 想操作桌面，通常卡在三件事：

1. **慢** —— 每个动作都附一张全分辨率截图，一次 128 ms / 962 KB，还动辄要模型往返好几秒；
2. **瞎** —— UI Automation 对某即时通讯软件 4.x（***）、Electron、CEF、自绘 UI、游戏几乎完全无效；
3. **不敢** —— 没有急停、没有授权闸门、没有"点错了怎么办"的纪律，一旦失控就在用户机器上乱点。

**图标控制**针对这三点逐层加码，并且把"怎么验证"写进了规则里，而不是靠模型自觉。

---

## 三个数字（都是实测，不是估算）

| 指标 | 改造前 | 改造后 |
|---|---|---|
| 单次截图耗时 | 128 ms | **61 ms** |
| 单次截图体积 | 962 KB | **121 KB** |
| 工具数量 | 31 | **72** |
| 不变量测试 | 0 | **86 项**（系统 Python / venv Python 双跑全绿） |
| 20 步动作的模型往返 | 20 次 | **1 次**（`batch`，协议层 2 ms） |

---

## 架构（三层策略 + 两条安全线）

```
┌─────────────────────────── 第一层：确定性最高 ───────────────────────────┐
│  ui_invoke > ui_click > ui_set_text     按控件名操作原生控件              │
│  batch                                  多步合成一次调用（往返 20→1）     │
│  macro_run                              整段回放（相对坐标 + expect 校验） │
└──────────────────────────────────────────────────────────────────────────┘
                                    ↓ 控件不存在 / 自绘 UI
┌─────────────────────────── 第二层：像素与文字 ───────────────────────────┐
│  ocr_read / find_text / click_text      区域 OCR（PrintWindow 被遮挡也能读）│
│  screen_state / wait_for_change         只问"变没变"，43 ms，不带图        │
│  capture_template / match_template      灰度模板自学 + 匹配（自绘 UI 通用）│
│  set_baseline / diff_baseline           区域偏离基线的程度                 │
│  sample_stable                          连采两次一致才算数（防动画误判）   │
│  hover_probe                            悬停后是否出现新东西（悬停菜单）    │
└──────────────────────────────────────────────────────────────────────────┘
                                    ↓ 前两层彻底用尽
┌─────────────────────── 第三层：逆向（隐藏层，默认关闭）───────────────────┐
│  读应用数据库 / 私有协议 / CLI / 内存 ……                                  │
│  ★ 进入条件：先举证（前两层各试了什么、为何失败）+ 说明影响面 + 先备份      │
│    + 用户逐次明确授权 + 只读优先                                          │
│  ★ 红线：不碰凭据、不篡改安全软件、不改系统服务/驱动、不绕 DRM            │
└──────────────────────────────────────────────────────────────────────────┘

安全线 A：连按两下 ESC = 立刻松手（脚本内 panic + 进程外 panic_watch 看守）
安全线 B：GUI 上的「鼠标·已授权 / 未授权」开关（灰色 = 无权限，绿色 = 可接管）
```

---

## 功能清单（58 个工具，按组）

| 组 | 工具 | 说明 |
|---|---|---|
| 采集 | `screenshot` `screen_state` `wait_for_change` `capture_config` | 默认 0.5 倍 JPEG、带 changed/diff；`screen_state` 不带图，43 ms |
| 批量 | `batch` | 一串动作一次调用，20 步协议层 2 ms |
| UI 自动化 | `ui_tree` `ui_find` `ui_click` `ui_invoke` `ui_set_text` | 原生控件的确定性操作 |
| 宏 | `macro_list` `macro_save` `macro_run` | 相对坐标、`expect` 校验、自动 restore、越界拒点、`retry`/`repeat`/`ensure_chat` |
| OCR | `ocr_read` `find_text` `click_text` | Windows 内置 OCR，支持 `upscale` + `boost` 认小字/灰字 |
| **验证** | `verify_flow` | 分级验证：text / template / baseline / stable / file 五种断言，遇错即停、每级留证据 |
| **视觉状态** | `capture_template` `match_template` `wait_template` `click_template` `set_baseline` `diff_baseline` `wait_baseline_change` `sample_stable` `hover_probe` `vision_list` | **本项目新增**：模板自学、基线差异、稳定采样、悬停探针、运行统计 |
| 应用生命周期 | （`appkit` 模块） | `launch`（走 Explorer shell）/ `wait_window` / `exit_app` / `activate`（AttachThreadInput 强攻前台） |
| 原有 | 30 个鼠标/键盘/窗口/虚拟桌面工具 | computer-mcp 原生 |

### v0.2 的两条新增安全/治理线

```
① 权限硬闸门（Host 侧）：19 个输入类工具在 call_tool 路由之前统一过闸门
   未授权 → 结构化拒绝，不产生任何鼠标/键盘动作；读不到状态 → fail closed
② 分级验证 verify_flow：验证从"散落在脚本里"变成"分级 + 留证 + 遇错即停"
```

### v0.3：授权状态不再靠看屏幕

```
老办法：Host 用 OCR 看界面上那个胶囊是不是绿的
        → 窗口一挪、一滚、被遮挡、换分辨率就判不出来
        → 更糟的是会读到聊天正文里的「鼠标·已授权」而被骗（假阳性）

新办法：GUI 插件每 5 秒把真实状态 POST 给本地桥（127.0.0.1:18765）
        Host 读状态文件即可 —— 0.1 ms，全程不看像素
        OCR 退为后备，有效期 15 秒；桥没起来会自动拉起
```

客户端用 `GET /beacon`（图片信标）+ `fetch POST` 双通道上报：
信标不受 fetch 的 CSP/CORS 限制，桥端校验**来源（Origin/Referer）+ 本机 token**。

实测：桥命中 **0.1 ms** vs OCR **118.6 ms**（约 948 倍），
且信号来自用户界面本身，不再受窗口位置影响。

**外加一个 GUI 插件**：`@local/dsh-mouse-permission` —— 输入框工具栏里那个灰色/绿色胶囊，
是**唯一**的鼠标接管授权入口（agent 只读，不许自己点亮）。

---

## 一路是怎么长出来的（发展历程）

> 全部发生在 2026-10-25 同一天。以下按真实顺序，包含失败。

### 阶段 0 · 起点：用户说"这个 MCP 效率很慢"

第一反应去猜"是不是 MCP 协议慢"，实测单次调用 1.8 ms —— **不是协议**。
真因是每次动作都附一张全分辨率 PNG。于是重写采集层：0.5 倍缩放 + JPEG q75，
并新增 `screen_state`（只回报变没变 / 差异百分比 / hash，43 ms）、
`wait_for_change`（事件驱动等待）、`capture_config`。

**收获**：优化前先量。`screen_state` > `screenshot` > 什么都不做。

### 阶段 1 · 还是慢：慢在模型往返，不在协议

一个 20 步的操作要 20 次调用，每次等模型。于是加 `batch`（20 步 → 1 次调用，协议层 2 ms）
和 UI Automation 五件套（`ui_tree`/`ui_find`/`ui_click`/`ui_invoke`/`ui_set_text`）。

**踩坑**：某即时通讯软件 4.x（***） 的 `ui_tree` 只回 2 个节点 —— 自绘渲染面，UIA 完全瞎。
Electron / CEF / 游戏同理。**UIA 不是万能钥匙。**

### 阶段 2 · 宏与 OCR：给"看不见控件"的界面补眼睛

- 宏 `macro_run`：相对窗口坐标、`expect` 校验"画面真的变了"、目标最小化自动 restore、
  越界拒绝执行 —— 一次调用回放整段（4 步 651 ms）。
- OCR 三件套：Windows 内置 OCR，带 hwnd 时走 PrintWindow（**被遮挡也能读**），
  中文按"去空格 + 最长公共子串"匹配（`即时通讯软件的自建会话（***）` 能命中 `文亻牛传输助手`）。

**踩坑清单（全都会导致"静默点空"）**：
前台抢不到 → `SetForegroundWindow` 被拒；`key:"enter"` 让 pynput 崩；
同一个函数被定义两次（补丁覆盖）；点列表行是"切换"语义……

### 阶段 3 · 三层策略：把风险关进盒子

用户定规矩：**逆向必须藏在第一、二层之后**，是隐藏层，因为风险太高。
于是写下进入第三层的五个前置条件（举证 / 说明 / 备份 / 逐次授权 / 只读优先）和五条红线。

### 阶段 4 · 真刀真枪的四个任务（每个都留了伤）

| 任务 | 结果 | 教训 |
|---|---|---|
| ChatClient发一首长诗（405 字 / 14 行）给指定联系人 | 成功 | 长文本用剪贴板 + Ctrl+V；回车发送比点"发送"按钮可靠 |
| VideoClient启动 | 卡了 6 次 | **Electron 应用必须走 `explorer.exe` shell 启动**，直接 Popen 会静默秒退（退出码 0、无窗口） |
| MusicClient下载无损 | 先成功、后失败、再成功 | **点列表行前必须 OCR 核对行内容** —— 我没核对，把第一首歌下成了另一首（列表顺序变了），白下 28.5 MB |
| SandboxFps（SandboxFps）装模组 | 成功（3 个） | **评价数 ≠ 能用**：632 评价的 PAIO+ 描述里写着 "THIS MUTATOR DOES NOTHING!!!"；`.rgc` 是配置不是内容 |

### 阶段 5 · P2：应用生命周期三件套 + 区域记忆

`appkit.launch / wait_window / exit_app`（关窗 ≠ 退出，托盘进程要显式结束）、
`anchor_mem.learn_region / learn_item`（区域与列表项记忆，自动外推行高）、
OCR 的 `upscale` + `boost`（ChatClient"发送"按钮基线 found=0 → upscale=3 后 found=1）。

### 阶段 6 · 急停：用户要"连按两下 ESC 你就松手"

`panic.PanicSwitch`（全局键盘监听，1.5 s 内两次 ESC 触发，**粘住不复位**）+
`panic_watch.py`（进程外看守，触发就杀掉所有自动化进程）。
在打 HorrorGame 的那一局里**真机触发过一次**，脚本当场硬停。

### 阶段 7 · 视觉状态判据（本项目最通用的一组能力）

打 HorrorGame 暴露的通用需求：看不见控件时怎么可靠判断"东西在不在、变没变"。
四个判据固化进工具集：

- **模板自学**：`capture_template` → `match_template`（灰度，返回屏幕绝对坐标）
- **基线差异**：`set_baseline` → `diff_baseline`（0~255 的平均绝对差）
- **稳定采样**：`sample_stable`（连采两次一致才算数，防动画中途误判）
- **悬停探针**：`hover_probe`（悬停 → 等 → 比较 → 移开，专治悬停菜单）

**四条铁律**（都被打过）：
1. 模板必须**自标定**，不要搬别人的图（别人机器上的阈值 0.62 在我这里 0 命中，白守一夜）；
2. 判据要选**与视角/滚动无关**的特征（曾用"右按钮亮度"判断是否在监控页，视角一转就误判）；
3. 状态**每轮从画面读**，变量只当缓存（靠"我记得灯开着"必然失步）；
4. 动画期间**不要判状态**。

### 阶段 8 · HorrorGame（HorrorGame）该游戏的自定义难度模式：一次通关、两次翻车

- **发现 1**：监控不是"点"出来的，是**鼠标移到底部 box 悬停**触发（点击只开不关）；
- **发现 2**：视角能**左右平移**（贴边），左右门/灯按钮只在对应侧可见；
- **成绩**：AI 全 0 通关；AI 全 5 撑到 252/545 秒被杀 —— 因为搬了别人的模板，
  `Bonnie/Chica` 检测**一次都没命中**。
- **复盘结论**：全 0 通关证明"流程和眼睛"对了；全 5 失败证明"判断"没建立起来。
  下一次从**采集局 + 分级验证**开始，而不是先写一个漂亮的循环。

### 阶段 9 · 游戏平台的创意工坊（***）：把"订阅按钮在哪"彻底搞清楚

结论固化进 `app_facts.md`：
- item 详情页**永远没有**订阅按钮（新旧布局都没有，别在那找）；
- 订阅 + 在**列表页卡片的右下角**，位置规律 `(标题x + 255, 创作者y + 4)`；
- 卡片太靠页面底部时 + 会被窗口边缘切掉，先向下滚 2 格；
- 验证只认 `创意工坊日志（***）` 的 `Subscribed to item` + `content/<appid>/<id>/` 目录。

最终装上 3 个自包含模组（喷气背包 / 能量护盾 / 科幻机体），另 3 个被砍（2 个空壳 + 1 个配置壳）。

### 阶段 10 · GUI 授权闸门（v0.1 的收尾功能）

用户要求：把"能不能动我的鼠标"做成界面上的开关 —— **无色 = 没权限，绿色 = 可以**。
于是有了：
- 插件 `@local/dsh-mouse-permission`，挂在 `conversation.input.right`（"完全权限"右边）；
- 只读检查器 `mouse_permission.py`：退出码 0 已授权 / 2 未授权 / 3 读不到；
- 规则写进 AGENTS.md：**agent 不得写 DOM / 改 localStorage / 用鼠标点它来自我授权**。

### 阶段 11 · 全局测试 → 修 bug → v0.1

全局测试发现 `_patched/appkit.py` 与 venv 安装副本**漂移**（旧版 14,653 B vs 新版 18,455 B）：
`find_shortcut` 的评分匹配、启动前目标校验、`activate()` 的 AttachThreadInput 都不在备份里。
备份旧版 → 同步 → 复测：漂移清零，64 项测试双解释器全绿。**这就是 v0.1 的发布状态。**

---

## 快速开始

```powershell
# 0) 前置：Python 3.11+，并把 computer-mcp 装进 venv
#    本项目以"补丁层"方式工作，不 fork 上游

# 1) 打补丁（把 computer_mcp 扩到 58 个工具）
venv\Scripts\python.exe _patched\reapply.py

# 2) 环境体检（6 组检查，5~10 秒）
venv\Scripts\python.exe doctor.py

# 3) 不变量测试
venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

# 4) 真操作冒烟（会动鼠标，需要 GUI 上授权变绿）
set Shell_E2E=1 && venv\Scripts\python.exe -m unittest tests.test_e2e_smoke -v

# 5) 鼠标接管前先查权限闸门
venv\Scripts\python.exe mouse_permission.py     # 0=已授权 2=未授权
```

一条命令装 GUI 插件（需要 Shell）：

```powershell
# 在 Shell 里对 agent 说：安装 bundle C:\path\to\plugin\  （走 plugin_manager install_bundle）
```

---

## 五条铁律（写进 AGENTS.md，优先级高于任何任务）

```
① 看 → 想 → 动：先截图/OCR 把事实摆上桌，再决定点哪，动完立刻验证。
② 验证只认应用自己的状态：剪贴板回读、文件是否生成、输入框是否清空、OCR 到的气泡。
   不认"我看到点了"、不认自建探针窗口的计数。
③ 宣布"没反应"之前先排三个假阴性：有模态对话框吗？目标真在前台吗？落点在窗口内吗？
④ 找元凶一次只改一个变量：先排假阴性，再逐个停驱动，别一上来就卸载安全软件。
⑤ 改动必须有基线：优化前量、改完再量；一次只改一处，改完立刻跑测试。
```

---

## 仓库结构

```
icon-control/
├─ README.md                # 你正在读的这份（含完整发展历程）
├─ CHANGELOG.md
├─ VERSION                  # 0.1.0
├─ LICENSE                  # MIT
├─ docs/
│   ├─ 发展历程.md            # 时间线长文（含每一次翻车）
│   └─ 踩坑清单.md            # 24 条"会导致静默失败"的具体坑
├─ tools/                   # 工具层入口脚本
│   ├─ desk.py              # CLI 入口（58 个工具）
│   ├─ mouse_permission.py  # 鼠标接管权限闸门（只读）
│   ├─ panic_watch.py       # 急停看守进程
│   ├─ doctor.py            # 环境体检
│   ├─ diag_input.py        # 输入链路可信判据
│   └─ clean.py             # 垃圾文件清理
├─ _patched/                # computer_mcp 的补丁层（reapply.py 可重放）
│   ├─ reapply.py
│   ├─ mcp.py               # +26 个工具注册与分发
│   ├─ macro_ext.py         # 宏引擎（含 vision 动作）
│   ├─ vision_state.py      # 模板 / 基线 / 稳定采样 / 悬停探针 / 统计
│   ├─ appkit.py            # 应用生命周期三件套
│   ├─ anchor_mem.py        # 界面记忆库（含区域/列表项）
│   ├─ ocr_ext.py           # OCR + upscale/boost
│   ├─ ui_ext.py            # batch + UIA
│   └─ panic.py             # 急停
├─ tests/                   # 64 项不变量测试
├─ macros/                  # 已验证的宏（ChatClient发送等）
├─ recipes/                 # 每个已验证应用一份"配方"（含坑）
└─ plugin/                  # GUI 授权开关（@local/dsh-mouse-permission）
```

---

## 边界与免责

- **只在 Windows 上验证过**（Win32 API、DPI 感知、PrintWindow、Windows OCR）。
- **安全线是给"善意的自动化"设计的**，不是沙箱：它防误操作与失控，不防恶意代码。
- 第三层（逆向）默认关闭，且代码里没有任何绕过授权/DRM/凭据的路径。
- 上线的只是**我写的补丁层与插件**；`computer-mcp` 本体仍归其原作者（MIT）。

## 致谢

- [computer-mcp](https://github.com/)：提供了干净的 31 工具底座。
- StrategyWiki / GamePlatform 社区 / 一个开源机器人实现（仓库名略）：HorrorGame 机制与"模板匹配打法"的思路来源
  （只学思路，资产一律自标定 —— 这条是被打出来的）。
- 用户：这一整天里提出的每一条批评，最后都变成了仓库里的一条规则。

---

**v0.1 的含义**：能力面已经打通（能看、能点、能验、能停、能授权），
但覆盖面还窄（3 个游戏/客户端实战 + 4 个通用判据）。下一版重点是把"分级验证流程"固化进 `verify` 工具。

---

## v0.4：从「一次一张图」到「持续感知 + 端上闭环」

v0.3 之前，每次"看一眼"都是：`mss 抓全屏 → 转 numpy → 传图/OCR`，一次 60~180 ms，
而且模型每做一个动作都要重来一遍。

v0.4 换了架构：**采集常驻、感知在端上算、动作在端上闭环**，模型只发意图、只看语义。

### 三层 + 一个控制面

```
MCP 工具（模型只在这里说话：少量、粗粒度）
   ↓
微脚本解释器 micro.py      run_script / act_until —— 整段循环在本地跑完
   ↓
感知原语 perceive.py       prompt / bar / openness / color / locate_rows / digits  （0.1~3 ms）
   ↓
采集守护 capture_daemon.py 常驻线程 + 环形缓冲 + 脏区检测 + 事件等待
```

### 实测（同一台机器，2560×1440）

| 操作 | 延迟 |
|---|---|
| `sense()`（读内存里的帧 + 脏区） | **0.010 ms** |
| `probe(prompt)` 有没有亮字提示 | **0.155 ms** |
| `probe(openness)` 视野通不通 | **0.301 ms** |
| `read_digits` 读像素字体数字 | **1.3 ~ 2.6 ms**（Windows OCR 是 120~180 ms 且读错） |
| 41 步闭环（`run_script`） | **0.41 s** |
| 同样 41 步走模型往返 | 约 **123 s** |

### 新工具（14 个，工具总数 58 → 72）

| 工具 | 作用 |
|---|---|
| `capture_daemon` | 开关采集守护，改缩放/帧率 |
| `sense` | 一次返回「变了什么 + 我要的指标」 |
| `watch` | 阻塞等条件成立（替代 sleep + 再截图） |
| `probe` | 单个像素原语（prompt / bar / openness / color / digits） |
| `hud` | **按颜色自动定位 HUD 行**（窗口大小变了也不怕） |
| `snapshot` | 按需抓图，返回文件路径（不往对话塞 base64） |
| `run_script` | 端上执行微脚本：key/press/turn/click/sleep/loop/if/until/log |
| `act_until` | 重复一个动作直到条件成立 |
| `frame_mark` / `frame_diff` | 帧打点与按帧比差异（判断动作是否生效） |
| `trace` | 上一次脚本的完整时间线 |
| `glyph` / `read_digits` | 数字模板学习与识别（像素字体专用） |
| `record` | 把环形缓冲的帧 + manifest 落盘（JPEG q80） |

### 为什么要"自动定位 HUD"

实测中游戏窗口从 806×640 变成了 537×427 —— 硬编码坐标当场失效。
`hud` 用颜色扫描找出 HUD 的每一行（cyan / yellow / …），返回**屏幕坐标的 box**，
再喂给 `read_digits` / `probe`。窗口怎么挪、怎么缩放都不影响。

### 微脚本示例（40 步导航 = 1 次调用）

```json
[
  {"op": "until", "timeout_ms": 30000,
   "cond": {"kind": "prompt", "box": [230, 455, 350, 60]},
   "do": [{"op": "key", "key": "w", "hold_ms": 400},
          {"op": "if",
           "cond": {"kind": "diff", "box": [140, 140, 540, 400], "op": "lt", "value": 1.0},
           "then": [{"op": "turn", "px": 430}]}]}
]
```

读法：一直走，直到屏幕底部出现提示；每走一步如果画面没变（撞墙），就右转 90°。
条件和动作都在本地求值 —— 模型只发这一段，收一份 trace。

---

## v0.5：保留策略（跑起来不产生垃圾）

```
capture_daemon start / snapshot 写完 / record 存完  →  自动 sweep（静默）
housekeeping(action=status)  看用量（只读）
housekeeping(action=sweep)   立刻清（可 dry_run）
```

| 区域 | 上限 | 超了删什么 |
|---|---|---|
| `_draw/` | 80 个文件 / 80 MB / 3 天 | 最老的先删 |
| `recordings/` | 10 个目录 / 300 MB / 7 天 | 最老的目录整个删 |
| `vision/baselines/` | 40 个文件 / 30 天 | 最老的先删 |
| `%TEMP%` 自己的 | `vh-*` / `canity_*` / `t_*.py`，超 6 小时 | 直接删 |

**资产永不删**：`macros/`、`recipes/`、`templates/`、`vision/glyphs.json`、`_patched/`。
**宿主的临时目录不碰**：`dsh-*` 明确排除（删了会影响运行中的会话）。

---

## v0.6：快慢双层导航（模型只做外环）

```
模型（0.2–0.5 Hz）    定目标、定策略、处理异常
   ↓ 计划（不是动作）
WorldState（15–20 Hz） 画面 → 结构化状态：小地图网格 / 玩家格 / 目标格 / 提示 / 电量
   ↓ 目标格
Servo（20–30 Hz）      每步重算方位误差并修正（face / approach / advance）
   ↓
Supervisor（事件驱动）  达成 / 卡住 / 不确定 / 新事件 才回到模型
```

**为什么这样就够**：模型慢在 token 生成（2–5 s/次），而"转向、前进、修正"不需要
语言推理，交给 20 Hz 的本地伺服即可。模型只在一局里的十几个关键点出现。

**朝向怎么来**：不读罗盘 —— 走一小步，看玩家标记在地图上的位移方向
（`servo(op=calibrate)`）。这样不需要游戏配合。

**容差与振荡**：对角相邻（距离 1.41 格）算到达；连续 6 步没更近就退出并交回上层，
绝不死循环。

---

## v0.7：布局标定与记忆（通用流程，不绑应用）

**不猜布局。** 看一眼 → 记住 → 复用：

```
layout_mem(action="save", hwnd=…, regions={
  "map":    [0.66, 0.55, 0.34, 0.42],
  "prompt": [0.31, 0.73, 0.36, 0.09],
  "bar":    [0.16, 0.82, 0.24, 0.04],
  "hud":    [0.01, 0.06, 0.31, 0.19]})
```

- 坐标是**归一化**的（相对画布 0~1），窗口怎么缩放都不失效
- `world_state(hwnd=…)` 会自动套用匹配的档案 → 调用时不用再传坐标
- 档案键 = 应用名（标题去版本号）+ 画布尺寸；`Canity v1.6.5` 与 `v1.6.6` 命中同一个
- 两种模式：`fixed`（固定画布贴左上角，游戏）/ `fit`（随窗口拉伸，编辑器）

**为什么不做自动识别**：实测四个探测器在真实画面上全错（详见 CHANGELOG）。
把"看一眼"交给模型（一次性），把"每次都准"交给代码 —— 这才是能推广的通用能力。

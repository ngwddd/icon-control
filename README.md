# 图标控制 · Icon Control

> **Icon Control v1.3 稳定性重构计划 · 1.3.0 正式版**
>
> 当前保留 89 个工具，优先修复权限执行、控制权、假成功与安装问题。
> 本轮修复 RC2 安全审计及独立复审问题，授权迁移至按 Agent、能力和应用隔离的原生控制中心。
> 完整真机验收和最终独立复审尚未签收，不能作为正式稳定版发布。修复与证据状态见 [安全整改](docs/v1.3/SECURITY-REMEDIATION.md)。
> 安装与回滚见 [INSTALL](docs/v1.3/INSTALL.md)，迁移见 [MIGRATION](docs/v1.3/MIGRATION.md)，
> 阶段要求见 [PLAN](docs/v1.3/PLAN.md)，验收见 [DESKTOP-BENCHMARKS](docs/v1.3/DESKTOP-BENCHMARKS.md)。
> 下文历史性能数据来自 v1.2，尚未在 v1.3 真机环境复测。

> **把「让 AI 真正接管你的鼠标和屏幕」做成可落地的工程，而不是又一个截图+坐标点击的 demo。**
>
> 它有性能基准、有验证纪律、有急停开关、有界面上的授权闸门，
> 并且**每一条规则都是被真实任务打出来的** —— 打输过的也算。

| 事实 | 当前值 |
|---|---|
| 版本 | **v1.3.0**；回滚基线 v1.2.0 / `98b38b4` |
| 工具数 | **89**（底座 31 + 本项目补丁 58，全部按 7 个分区归位） |
| 测试 | 以 docs/v1.3/VALIDATION.md 和完整回归报告为准；跳过项不算通过 |
| 平台 | Windows 11 · 2560×1440 @150% |
| 底座 | computer-mcp 0.0.7 的 MIT 源码随标准安装包提供；见 THIRD_PARTY_NOTICES.md |
| 许可证 | MIT |

---

## 它解决什么问题

通用 agent 想操作桌面，通常卡在三件事：

1. **慢** —— 每个动作都附一张全分辨率截图，一次 128 ms / 962 KB，还要模型往返好几秒；
2. **瞎** —— UI Automation 对微信 4.x、Electron、CEF、自绘 UI、游戏几乎完全无效；
3. **不敢** —— 没有急停、没有授权闸门、没有"点错了怎么办"的纪律，一旦失控就在用户机器上乱点。

**图标控制**针对这三点逐层加码，并把"怎么验证"写进规则，而不是靠模型自觉。

---

## v1.2 历史实测数字（候选版尚未复测）

| 指标 | 改造前 | 现在 |
|---|---|---|
| 单次截图 | 128 ms / 962 KB | **61 ms / 121 KB**（0.5× JPEG） |
| 只问"变没变" | 要一张图 | **43 ms**，不带图 |
| 抓帧（窗口区域 + 4× 块平均） | 34.6 ms（全屏） | **13.7 ms** → 29.8 fps |
| 授权状态读取 | OCR 118.6 ms | **桥接 0.1 ms**（约 948×） |
| 20 步动作的模型往返 | 20 次 | **1 次**（`batch`，协议层 2 ms） |
| 工具数 / 测试数 | 31 / 0 | **89 / 298** |

---

## 架构（三层策略 + 两条安全线）

```
┌────────────────────── 第一层：确定性最高 ──────────────────────┐
│ ui_invoke > ui_click > ui_set_text      按控件名操作原生控件     │
│ batch                                   多步合成一次调用        │
│ macro_run                               整段回放（相对坐标+expect）│
│ program.run                             指令流（facts + jsonl）  │
└────────────────────────────────────────────────────────────────┘
                     ↓ 控件不存在 / 自绘 UI
┌────────────────────── 第二层：像素与文字 ──────────────────────┐
│ ocr_read / find_text / click_text        区域 OCR（被遮挡也能读）│
│ screen_state / wait_for_change           只问"变没变"，43 ms     │
│ capture_template / match_template        灰度模板自学+匹配       │
│ set_baseline / diff_baseline             区域偏离基线程度        │
│ sample_stable / hover_probe              防动画误判 / 悬停菜单   │
│ selector.resolve                         软选择器三级降级        │
└────────────────────────────────────────────────────────────────┘
                     ↓ 前两层彻底用尽
┌────────────────── 第三层：逆向（隐藏层，默认关闭）──────────────┐
│ 读应用数据库 / 私有协议 / CLI / 内存 ……                         │
│ ★ 进入条件：先举证 + 说明影响面 + 先备份 + 用户逐次授权 + 只读优先│
│ ★ 红线：不碰凭据、不篡改安全软件、不改系统服务/驱动、不绕 DRM    │
└────────────────────────────────────────────────────────────────┘

安全线 A：连按两下 ESC = 立刻松手（脚本内 panic + 进程外 panic_watch 看守）
安全线 B：原生控制中心按会话、能力和应用授权；DSH 胶囊仅显示后端确认状态
```

---

## 功能清单（89 个工具，按 7 个分区）

| 组 | 工具 | 说明 |
|---|---|---|
| 采集 | `screenshot` `screen_state` `wait_for_change` `capture_config` | 默认 0.5× JPEG，带 changed/diff |
| 批量 | `batch` | 一串动作一次调用 |
| UI 自动化 | `ui_tree` `ui_find` `ui_click` `ui_invoke` `ui_set_text` | 原生控件的确定性操作 |
| 宏 | `macro_list` `macro_save` `macro_run` | 相对坐标、`expect` 校验、越界拒点、`retry`/`repeat` |
| OCR | `ocr_read` `find_text` `click_text` | Windows 内置 OCR，支持 `upscale` / `boost` |
| 验证 | `verify_flow` | text / template / baseline / stable / file 五种断言，遇错即停 |
| 视觉状态 | `capture_template` `match_template` `wait_template` `click_template` `set_baseline` `diff_baseline` `wait_baseline_change` `sample_stable` `hover_probe` `vision_list` | 模板自学、基线差异、稳定采样、悬停探针、运行统计 |
| 列车 | `track` | 三步帧环 + 看门狗（`budget_ms` 超 3× 出拼图，连续 2 次停） |
| 应用生命周期 | （`appkit`） | `launch`（ShellExecuteEx 验证具体进程）/ `wait_window` / `exit_app` / `activate` |
| 原有 | 30 个鼠标/键盘/窗口/虚拟桌面工具 | computer-mcp 原生 |

---

## 七个核心机制

### ① 软选择器 `selector.resolve` —— 按语义找控件，找不到才退回坐标

```
text（OCR 找那一行） → template（cv2 匹配图标） → rel（比例坐标兜底）
返回 method，用来统计"这套在这个应用上到底有没有用"
```

实测（微信 1566×1057）：

| 目标 | 参数 | 结果 |
|---|---|---|
| 会话行「文件传...」 | `within` + **`upscale: 2`** | ✅ text，score 0.85 |
| 聊天标题 | `within` 顶部区 | ✅ text（OCR 读成「文亻牛传输助手」，LCS 救回） |
| 输入框 | `text:"发送"` | ❌ 退回 rel（无稳定文字，合理保留） |

**三个硬要求**：小字必须 `upscale: 2`；中文**不要** `boost`（`件`→`亻牛`）；截断按**长公共前缀 ≥3** 判。

### ② 指令流 `program` —— 写一次剧本，程序照着演

```jsonl
{"op":"click","at":"@wx.rail.discover"}
{"op":"click","find":{"text":"朋友圈"},"expect":{"kind":"changed","min_frac":0.003}}
{"op":"scroll","dy":-360,"at":[0.62,0.55]}
{"op":"send","text":"$msg","title_text":"文件传输助手","conv_min_lcs":0.5}
{"op":"assert","expect":{"kind":"text","query":"$msg","region":"@regions.conv"}}
```

`facts.json` 存不变量（坐标、区域、窗口签名、`measured_at`），`program.jsonl` 一行一条。
`@name` 取结构值、`$name` 插值；引用了不存在的名字 → **KeyError 停下**，绝不拿 None 点鼠标。

### ③ 列车 `track` —— 三步帧环 + 看门狗

```
L1 采集（窗口区域 4× 块平均，环形 150 帧，0.3~1.2 MB 恒定）
L2 处理（分块差分 → 稳定/过渡 → 事件）
L3 输出（最新稳定帧 + 变化块拼图 + 事件时间线）
看门狗：单步超预算 3× → ANOMALY + 拼图；连续 2 次 → stall
```

实测：29.8 fps；3 步轨道 0.9 秒；看门狗在 3.0s / 7.5s 准确触发（预算 1.0s / 2.5s）。

### ④ 窗口健壮性 `winutil` —— 句柄会变、点击会丢、前台会跑

```
heal(hwnd, title)        句柄被应用重建后按标题重找
win_rect(hwnd)           失效返回 None，不抛 (1400, 无效句柄)
ensure_front(hwnd, probe) 置顶 + WindowFromPoint 落点校验
click(..., verify, retries) 点前后比一小块画面，没变就重试并放慢
```

### ⑤ 控制权交接 `control` —— 用户随时能抢回鼠标

授权是**一次性开关**，但真实使用中用户随时会想"别动了，我来"。

```
control_status              读当前归属（ai / user / idle）+ 还差几秒恢复
control_claim               action=claim 申请 / action=release 交还
物理鼠标持续移动满 1 秒       夺回控制；短暂挪动不中断
物理点击、滚轮或键盘输入      立即夺回
Ctrl+Alt+Shift+Backspace    强制夺回
闲置 10 秒                   自动回到 idle，agent 可再次申请
```

闸门因此变成两层：**授权 granted → 控制权 owner**。被拒时返回 `control` 字段与剩余秒数，
模型能自己判断该等还是该问人，而不是干等。

v1.3 使用 Windows 注入标志过滤自己的事件。旧 quiet() 接口保留，但不会忽略静默期间的物理输入。
监听启动失败时拒绝接管，授权撤销或控制权代际改变会取消原任务。

### ⑥ 训练数据分区 `dataset` —— 用完即入、离线回流

v1.3 数据记录默认关闭；显式启用且用户授权有效时，路由层可记成一条 episode：

```
工具 + 参数（脱敏后）+ 结果 + 耗时 + 分区
  ├─ 成功 → 校准集（坐标/时序）
  ├─ 失败 ≥3 次同类 → dataset_triage 自动生成回归用例 cases/*.json
  └─ dataset_explore 随机游走 → 弱语义轨迹（打 explore 标签）
```

**隐私按最保守来**：抓屏默认关；六类脱敏（身份证/银行卡/手机/邮箱/token/家目录）落盘前完成；
剪贴板与键盘原文永不采集；raw 保留 90 天、帧 30 天或 8 GB。
**Z6 单向**：只被 tee 写，不被运行时读——防止"改样本 → 改行为"的隐式耦合。

### ⑦ 统一寻址 `find_element` —— 自绘界面也能定位

UIA 对微信 4.x、Electron、CEF、游戏几乎无效。`find_element(query)` 依次尝试：

```
UIA 控件名  →  OCR 文字  →  模板匹配
```

命中即返回，统一成 `{x, y, w, h, cx, cy, source, score}`；单条来源出错只记进 `errors`，
不影响后面的尝试。定位与点击分离：它只负责"在哪"，点还是交给 `click` / `ui_click`。

---

## 版本时间线

| 版本 | 一句话 |
|---|---|
| v0.1 | 能力面打通：能看、能点、能验、能停、能授权 |
| v0.2 | 权限硬闸门（19 个输入工具统一过闸）+ 分级验证 `verify_flow` |
| v0.3 | 授权状态不再靠看屏幕：界面每 5 秒 POST 给本地桥，0.1 ms |
| v0.4 | 采集常驻 + 端上闭环：14 个新工具，抓帧 34.6 → 13.7 ms |
| v0.5 | 保留策略：跑起来不产生垃圾（`_draw`/录制/模板上限 + 自动清扫） |
| v0.6 | 快慢双层导航（模型只做外环） |
| v0.7 | 布局标定与记忆；**11 个 skill 分册**把弱点与踩坑全部入库 |
| v0.8 | 软选择器（text → template → rel 三级降级）+ 可复现 A/B |
| v0.9 | **根因修复**：`check_expect(None)` 返回 True 导致"无 expect 的步骤"从不执行 → 假成功 |
| v1.0 | 指令流 `program`（facts + jsonl）跑通；`send` 四段验证 |
| v1.1 | 窗口句柄自愈 + 点击丢包重试（`winutil`） |
| v1.2 | **模块化 + 训练数据分区**：1806 行路由拆成 7 个分区（190 行）+ 控制权交接 + 统一寻址 + 数据闭环（89 工具 / 298 测试） |

完整逐版本记录见 [CHANGELOG.md](CHANGELOG.md)。

---

## 快速开始

~~~powershell
# Python 3.12+；完整源码随 wheel 提供，不再覆盖宿主 site-packages
python -m pip install build
python -m build
powershell -File tools\install.ps1

# 在独立目录运行回归；不授予真实宿主鼠标权限
python tools\verify.py --pattern "test_*.py"

# MCP 客户端 stdio 入口（详细配置见 INSTALL）
& "$env:LOCALAPPDATA\IconControl\current\Scripts\python.exe" -m computer_mcp.launcher stdio
~~~

加载安装目录的客户端后，由用户在原生控制中心选择会话、能力和应用并批准。前端不保存授权密钥。
HTTP 使用官方 Streamable HTTP、独立 Bearer Token 和 loopback 绑定；旧自制 SSE 接口不再提供。

---

## 五条铁律（优先级高于任何任务）

```
① 看 → 想 → 动：先把事实摆上桌，再决定点哪，动完立刻验证。
② 验证只认应用自己的状态：剪贴板回读、文件是否生成、输入框是否清空、OCR 到的气泡。
   不认"我看到点了"，不认自建探针窗口的计数。
③ 宣布"没反应"之前先排三个假阴性：有模态对话框吗？目标真在前台吗？落点在窗口内吗？
④ 找元凶一次只改一个变量：先排假阴性，再逐个停驱动，别一上来就卸载安全软件。
⑤ 改动必须有基线：优化前量、改完再量；一次只改一处，改完立刻跑测试。
```

---

## 仓库结构

```
icon-control/
├─ README.md                 # 你正在读的这份
├─ CHANGELOG.md              # 25 个版本，逐条记录（含失败）
├─ VERSION                   # 1.3.0rc1
├─ LICENSE                   # MIT
├─ docs/                     # 发展历程长文 + 踩坑清单
├─ recipes/                  # 每个验证过的应用一份"配方"（含 measured_coords + 坑）
│   ├─ wechat.json           # 含 find_specs（可直接抄的选择器参数）
│   ├─ steam.json
│   └─ app-01..07.json
├─ macros/                   # 已验证的宏（含 wechat_send_frac.json）
├─ programs/                 # 指令流（facts + jsonl）
│   ├─ wx_facts.json
│   └─ wx_send.jsonl
├─ tools/                    # 入口脚本
│   ├─ clean.py              # 清垃圾（保留策略）
│   ├─ desk.py               # CLI
│   ├─ diag_input.py         # 输入链路三层判据
│   ├─ doctor.py             # 环境体检
│   ├─ mouse_permission.py   # 鼠标接管权限闸门（只读）
│   ├─ panic_watch.py        # 急停看守（通用规则：*_bot/_run/_fight）
│   ├─ selector_demo.py      # 软选择器 A/B（自开靶子）
│   ├─ track_nopred_demo.py  # 无 expect 步骤的回归测试
│   └─ track_oneshot.py      # 列车一次性自测（11 项检查）
├─ _patched/                 # 完整 computer_mcp 包源码，由 pyproject.toml 打包
├─ skill/desktop-operator/   # 随身 skill（SKILL.md + 10 个分册）
├─ tests/                    # 逻辑、安全、协议回归；真机任务另行验收
├─ templates/                # 模板文件
└─ plugin/                   # GUI 授权开关
```

`computer_mcp` 侧共 30+ 个模块，v1.2 起按**七分区**组织：

```
tool_registry.py    工具清单聚合（89 条，含 zone/read_only/aliases）
tool_spec.py        ToolSpec 数据结构
mcp.py 190 行       只剩闸门 + 路由 + 数据 tee（原来是 1806 行）
zones/              按决策阶段分区
  z0_governance 4   治理：授权、控制权、配置、保留
  z1_capture    7   采集：截图、录屏、守护、模板抓取
  z2_sense     25   判据：OCR、模板、数字、HUD、统一寻址、统一等待
  z3_act       31   动作：鼠标、键盘、窗口、UIA
  z4_compose    8   编排：脚本、宏、闭环、导航、验证
  z5_memory     8   资产：宏、模板、基线、字形
  z6_learning   6   训练数据：采样、查询、提升、导出、分拣、探索
  dispatch.py       分发链（原 mcp.py 里的 522 行 if/elif）
  aliases.py        旧名 → 新名（domain_noun_verb）
dataset/            训练数据分区（采样/脱敏/查询/保留/导出/分拣/探索/导入器）
conveyor.py 1018 行 列车（原 train.py，改名消除与"训练数据"的撞名）
macro_ext.py       宏引擎
live.py            实时动作
```

---

## Skill：`desktop-operator`（随本包发布，11 个文件）

```
~/.dsh/skills/desktop-operator/SKILL.md      ← 入口：开工顺序 / 失败模式速查 / 判活三连
```

| 分册 | 什么时候翻 |
|---|---|
| `failures.md` | **卡住了先看这张**（30 条症状→真因→做法） |
| `pitfalls.md` | 要写代码/接管道/改编码（含自绘 UI 丢包、句柄重建） |
| `program.md` | 想把流程固化成剧本（facts + program.jsonl） |
| `train.md` | 多步任务、连续性、看门狗、`skip_if` / `focus` |
| `selector.md` | 界面一变就点偏、想按文字找控件 |
| `wechat.md` | 微信：独立聊天窗、朋友圈、发消息 |
| `steam.md` | 创意工坊订阅/取消（**日志验证**，ACF 会滞后） |
| `uwp-cef.md` | UWP / CEF / Electron |
| `coords.md` | DPI / 四种坐标系 / 读图预算 |
| `toolbox.md` | 清垃圾、自检、三个解释器、验证助手 |

---

## 边界与免责

- **只在 Windows 上验证过**（Win32 API、DPI 感知、PrintWindow、Windows OCR）。
- **安全线是为"善意的自动化"设计的**，不是沙箱：防误操作与失控，不防恶意代码。
- 第三层（逆向）默认关闭，代码里没有任何绕过授权 / DRM / 凭据的路径。
- 本仓库发布的是**补丁层与插件**；`computer-mcp` 本体仍归原作者（MIT）。

## 致谢

- [computer-mcp](https://github.com/)：干净的 31 工具底座。
- 用户：这一路上的每一条批评，最后都变成了仓库里的一条规则或一次发版。

---

**v1.1.0 的含义**：能力面（看/点/验/停/授权）+ 流程面（配方/宏/列车/指令流）+ 健壮性面（句柄自愈、点击重试）都已就位。

**v1.2.0 的含义**：从"能干活"走到"能长期干活"——结构上把 1806 行的单文件路由拆成 7 个有边界的分区，
行为上补了两块短板（**用户随时能夺回鼠标**、**自绘界面也能定位**），
数据上开了训练分区（**每次调用自动沉淀、失败自动变回归用例**）。
工具 89 个、测试 298 项，`mcp.py` 从 1806 行降到 190 行。
下一版重点：把"证据链"做成默认行为 —— 每个动作都自带"我怎么证明它生效了"。

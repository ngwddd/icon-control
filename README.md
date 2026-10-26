# 图标控制 · Icon Control

> **把「让 AI 真正接管你的鼠标和屏幕」做成可落地的工程，而不是又一个截图+坐标点击的 demo。**
>
> 它有性能基准、有验证纪律、有急停开关、有界面上的授权闸门，
> 并且**每一条规则都是被真实任务打出来的** —— 打输过的也算。

| 事实 | 当前值 |
|---|---|
| 版本 | **v1.1.0** |
| 工具数 | **79**（底座 31 + 本项目补丁 48） |
| 测试 | **242 项**（仓库）/ 241 项（工具目录），全绿 |
| 平台 | Windows 11 · 2560×1440 @150% |
| 底座 | [computer-mcp](https://github.com/)（MIT，31 工具）+ 本项目补丁层 |
| 许可证 | MIT |

---

## 它解决什么问题

通用 agent 想操作桌面，通常卡在三件事：

1. **慢** —— 每个动作都附一张全分辨率截图，一次 128 ms / 962 KB，还要模型往返好几秒；
2. **瞎** —— UI Automation 对微信 4.x、Electron、CEF、自绘 UI、游戏几乎完全无效；
3. **不敢** —— 没有急停、没有授权闸门、没有"点错了怎么办"的纪律，一旦失控就在用户机器上乱点。

**图标控制**针对这三点逐层加码，并把"怎么验证"写进规则，而不是靠模型自觉。

---

## 实测数字（本机，不是估算）

| 指标 | 改造前 | 现在 |
|---|---|---|
| 单次截图 | 128 ms / 962 KB | **61 ms / 121 KB**（0.5× JPEG） |
| 只问"变没变" | 要一张图 | **43 ms**，不带图 |
| 抓帧（窗口区域 + 4× 块平均） | 34.6 ms（全屏） | **13.7 ms** → 29.8 fps |
| 授权状态读取 | OCR 118.6 ms | **桥接 0.1 ms**（约 948×） |
| 20 步动作的模型往返 | 20 次 | **1 次**（`batch`，协议层 2 ms） |
| 工具数 / 测试数 | 31 / 0 | **79 / 242** |

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
安全线 B：GUI 上的「鼠标·已授权 / 未授权」胶囊（灰=无权限，绿=可接管，agent 只读）
```

---

## 功能清单（79 个工具，按组）

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
| 应用生命周期 | （`appkit`） | `launch`（走 ShellExecuteW）/ `wait_window` / `exit_app` / `activate` |
| 原有 | 30 个鼠标/键盘/窗口/虚拟桌面工具 | computer-mcp 原生 |

---

## 四个核心机制

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

完整逐版本记录见 [CHANGELOG.md](CHANGELOG.md)。

---

## 快速开始

```powershell
# 0) 前置：Python 3.11+，computer-mcp 装进 venv；本项目以"补丁层"工作，不 fork 上游

# 1) 打补丁（把 computer_mcp 扩到 79 个工具）
venv\Scripts\python.exe _patched\reapply.py

# 2) 环境体检（6 组检查，5~10 秒）
venv\Scripts\python.exe doctor.py

# 3) 不变量测试（242 项）
venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

# 4) 真操作冒烟（会动鼠标，需要 GUI 上授权变绿）
$env:SHELL_E2E=1; venv\Scripts\python.exe -m unittest tests.test_e2e_smoke -v

# 5) 鼠标接管前先查权限闸门（0=已授权 2=未授权）
venv\Scripts\python.exe mouse_permission.py

# 6) 两个可复现的能力自证（不需要任何外部应用）
venv\Scripts\python.exe tools\selector_demo.py      # 硬坐标失败 vs 软选择器命中
venv\Scripts\python.exe tools\track_nopred_demo.py  # 无 expect 的步骤是否真的执行
```

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
├─ CHANGELOG.md              # 24 个版本，逐条记录（含失败）
├─ VERSION                   # 1.1.0
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
├─ _patched/                 # computer_mcp 补丁层（reapply.py 可重放，27 个文件）
├─ skill/desktop-operator/   # 随身 skill（SKILL.md + 10 个分册）
├─ tests/                    # 242 项不变量测试
├─ templates/                # 模板文件
└─ plugin/                   # GUI 授权开关
```

`computer_mcp` 侧共 30 个模块，核心几个：

```
train.py 52 KB     列车：帧环 + 看门狗 + 判据
mcp.py 86 KB       工具注册与分发（79 个）
macro_ext.py 55 KB 宏引擎
live.py 29 KB      实时动作
program.py 10 KB   指令流
selector.py 11 KB  软选择器
winutil.py 5 KB    窗口健壮性
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
下一版重点：把"证据链"做成默认行为 —— 每个动作都自带"我怎么证明它生效了"。

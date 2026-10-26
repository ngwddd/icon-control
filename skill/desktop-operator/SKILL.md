---
name: desktop-operator
description: >
  用鼠标键盘接管 Windows 桌面完成任务（微信 / Steam / 浏览器 / UWP / 自绘 UI / 游戏）。
  核心不是"调工具"，而是：**先看再动、一步一截图、坐标从图上量、每步带时间预算**。
  触发：「帮我打开X发Y」「给微信/QQ 发…」「在 Steam 订阅/下载…」「用鼠标点…」
        「操作这个窗口」「把电脑上的…弄一下」「截图看看…」「按这个流程跑一遍」
  不适用：能用命令行/文件操作完成的事（那比点鼠标可靠一个数量级）；
          需要密码/支付/授权的操作；改系统设置与服务。
---

# desktop-operator · 桌面操作手

> **一句话**：桌面任务 = 看着屏幕 + 一步一步动鼠标。
> 工具只做三件事：**看**（截图）、**动**（点/打/滚）、**记住流程**（配方 + 轨道）。
>
> **分册按"什么时候会用到"组织**：卡住 → 先查 `references/failures.md`；
> 要写代码/接管道 → 查 `references/pitfalls.md`。

## 0. 开工顺序（不许跳步）

```
① recipes/<app>.json 里有 → 照抄里面的 measured_coords / 流程 / 坑
② macros/ 有对口宏        → macro_run 一次跑完
③ 多步且有明确"该看到什么" → track（三轮回转 + 看门狗，见 references/train.md）
④ 都没有 → 自己一步步来（第 1 节）
```

配方和宏：`~/.dsh/tools/desktop-mcp/recipes/*.json`、`.../macros/*.json`

## 1. 核心循环

```
看一眼（截图）→ 决定一个动作（只做一个）→ 做 → 再看一眼（截图对比）
```

### 三条铁律

1. **一步一截图**。长脚本一口气跑到底 = 中间错了不知道，最后重来。
2. **坐标从图上量**，不要 OCR 找按钮、不要用比例推算。
   （实测：面板 442×581 用比例算出 y=882，真实按钮在 y=835 —— 偏 47 px）
3. **动手前确认窗口在前台**：`HWND_TOPMOST` + `GetForegroundWindow() == hwnd`。

## 2. 失败模式速查（卡住先看这张表）

| 症状 | 真因 | 立刻做什么 |
|---|---|---|
| 点了没反应 | 会话/内容可能在**另一个窗口**里 | `EnumWindows` 列窗口，按标题找 |
| 点击全偏移 | 没声明 DPI 感知 | `SetProcessDpiAwareness(2)` |
| 画面正常但输入全无效 | `SW_HIDE` 后重显示破坏了输入上下文 | 只能真实点击/重启进程；以后只 `SW_MINIMIZE` |
| 能改尺寸但画面不动 | 鬼影窗口 | `SetWindowPos(..., SWP_FRAMECHANGED)` |
| 命令卡 1 分钟 | 子进程继承了输出管道（`cmd /c start`） | 改 `ShellExecuteW` |
| 打字丢字 | `kb.type()` 太快 | 逐字符 15 ms，或剪贴板粘贴 |
| 打字全落空 | 模态对话框吞键 / UWP 没点进编辑区 | 先截图；点一下编辑区 |
| 判据"没变化"就失败 | 用了瞬时变化率（竞态） | 改锁存；滚动类判据用 `stable` |
| 文字断言永不成立 | OCR 读了 `TRACKOK2152` | 归一化 + LCS 0.8；不传 region 默认整窗 |
| 开应用卡一分钟 | 没有单步预算 | 每步 `budget_ms`，超 3× 截图停车 |

**完整 30 条** → `references/failures.md`

## 3. 判活三连（宣布"没反应"之前必须过）

```
① 前台是它？   GetForegroundWindow() == hwnd
② 落点是它？   WindowFromPoint(x,y) → GetAncestor(GA_ROOT) == hwnd
③ 会重绘？     改尺寸/悬停后截图差异 > 0.5
```

三条全过还点不动 → 才考虑输入链路。**缺 ③ 会在鬼影窗口上白折腾半小时。**

## 4. 输入方式（按可靠性）

```
1. 剪贴板 + Ctrl+V        长文本/中文首选（绕开输入法）
2. 逐字符 press/release 15 ms   短英文；kb.type() 会丢字
3. 回车提交               比点"发送"按钮可靠
```

**永远不要**：逐字敲长文本、点 OCR 读到的"发送"、同一个开关点两次。

## 5. 工具分层（79 个里只有这几个是入口）

| 用途 | 工具 |
|---|---|
| 看 | `screenshot` / `screen_state`（只要"变没变"时） |
| 动 | `batch` / 坐标点击 / `type` |
| 整段 | `macro_run`（含断言与重试） |
| 多步 + 连续性 | `track`（三轮回转 + 看门狗，见 train.md） |
| 认字 | `ocr_read` / `find_text`（只确认，不定位） |
| 记位置 | `layout_mem`（标定一次归一化复用） |

其余（`screen_model` 实验性、`perceive`/`navigator` 内部件、30 个低层动作）**不要当第一步**。

## 6. 收尾（每次任务结束：**关窗** + 清理 + 还原）

```
① 关窗：close_windows 关掉**我打开或使用的**窗口（只发 WM_CLOSE，不杀进程）
   要退出整个应用才用 appkit.exit_app / exit_app
   ⚠️ 不要 SW_HIDE 微信主窗口；清桌面用 SW_MINIMIZE
② 把任务开始前的窗口还原到前台
③ clean.py --apply --keep 1  清临时文件
④ 报告：关了哪些窗口、清了多大、**量到的坐标写进配方了吗**
```

**边界**：只关自己开的；有未保存改动（标题带 `*`、弹保存提示）先问用户。

## 7. 分册索引

| 什么时候看 | 文件 |
|---|---|
| **卡住了 / 报错 / 没反应** | `references/failures.md`（30 条症状 → 真因 → 做法） |
| **要写代码 / 接管道 / 处理编码** | `references/pitfalls.md`（启动、窗口、DPI、输入、Shell、性能） |
| 微信（进入面板、朋友圈、发消息、**独立聊天窗**） | `references/wechat.md` |
| Steam 创意工坊订阅 | `references/steam.md` |
| UWP / CEF / Electron | `references/uwp-cef.md` |
| 坐标 / 缩放 / 记忆 | `references/coords.md` |
| 多步任务、要连续性、看门狗 | `references/train.md` |
| 本机工具链（清垃圾、验证、解释器） | `references/toolbox.md` |

## 8. 什么时候**别**用这个 skill

```
· 能用 PowerShell / python / 文件操作做到的 —— 一律不动鼠标
· 需要密码、支付、授权确认 —— 交回用户
· 改系统服务/驱动/安全软件 —— 不做
· 用户正在打字或看视频 —— 不抢焦点
```

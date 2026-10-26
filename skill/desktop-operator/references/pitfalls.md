# 踩坑事实（本机实测，2026-10）

> 这些是**事实**，不是建议。每条后面写着「怎么错的」，因为忘掉原因就会重犯。

## 一、启动 / 进程

| 事实 | 怎么错的 |
|---|---|
| **启动 GUI 应用用 `ShellExecuteW`**，不要 `subprocess.Popen(["cmd","/c","start",...])` | `cmd /c start` 的子进程会**继承调用方的输出管道**，工具一直等管道关闭 → 卡 1 分钟。实测微信从 7 秒变成"卡死" |
| `Popen(exe)` 会让部分 Electron 应用**静默秒退**（退出码 0、无窗口） | 所以 GUI 一律走 shell（`appkit.launch` 或 ShellExecuteW） |
| 关窗 ≠ 退出：`WM_CLOSE` 后进程常驻托盘 | 真要退出用 `appkit.exit_app` / `taskkill`；Windows 商店应用还可能有后台服务 |
| 重跑 exe 想"唤醒单实例" → 会**开出第二个实例** | 微信实测多出 169 MB 进程，抢前台，原实例更收不到输入 |

## 二、窗口状态（最容易骗人的一块）

| 事实 | 判据 |
|---|---|
| 窗口能改尺寸但**画面不动** = 鬼影（`SW_HIDE` 后 `SW_SHOW` 造成） | 改尺寸后截图差异 > 0.5；救法是 `SetWindowPos(..., SWP_FRAMECHANGED)` |
| 隐藏的窗口再显示，**输入上下文会坏**：画面正常、点击/按键全无效 | `WindowFromPoint` 指它、前台也是它，但全屏差异恒 0.003 → 只能真实点击或重启进程 |
| **要清桌面就 `SW_MINIMIZE`，永远不要 `SW_HIDE`** | 微信实测：`SW_HIDE` 一次，这个会话里输入就再没恢复 |
| 最小化窗口的 rect 是 `-32000` 附近 | 宏/轨道必须先 `SW_RESTORE` 再取 rect |
| 窗口可能**跑到屏幕外**（y=840 + 高 1057 > 1440） | 操作前先 `SetWindowPos` 挪进屏幕内 |
| 目标窗口随时可能**被别的窗口盖住** | 每步动手前：`HWND_TOPMOST` + `SetForegroundWindow`，并校验 `GetForegroundWindow() == hwnd` |

## 三、坐标 / DPI

| 事实 | 数值 |
|---|---|
| 任何坐标运算前必须 `SetProcessDpiAwareness(2)` | 屏幕 2560×1440 @150%；不声明 → 点击整体偏 1.5 倍，画面差异恒 0.00（看起来像"输入被拦"） |
| `GetWindowRect` 含边框/阴影，`GetClientRect` 不含 | 用 rect 截图、又用 client 算点击 → 差一个标题栏（30–47 px） |
| **比例坐标会偏**：面板 442×581 用 `483/581` 算出 y=882，实测按钮在 y=835 | 偏 47 px。有截图就**直接量绝对坐标**，比例只用于"大致定位" |
| `SWP_NOMOVE\|SWP_NOSIZE` 用数值时容易写错 | 直接用 `win32con.SWP_NOMOVE` 常量 |
| 抓取范围要选**目标窗口**，不是全屏 | 全屏 25 ms / 窗口 11 ms（差 2.3 倍）；54 fps vs 27 fps |
| 降采样用 **numpy 块平均**，不要 `PIL.resize` | PIL 18 ms，numpy 4.5 ms |

## 四、输入

| 事实 | 怎么错的 |
|---|---|
| `kb.type("长文本")` 会**丢字**（Win11 UWP 尤其） | 实测 `TRACK-OK-2152` 只进去一部分；改逐字符 15 ms 间隔，或直接剪贴板粘贴 |
| 长文本/中文一律**剪贴板 + Ctrl+V** | 绕开输入法和逐字敲 |
| 输入法（IME）会吞键 | `ImmAssociateContext(hwnd, 0)`，或切 en-US 布局 |
| **模态对话框**会吞掉所有按键 | `notepad` 的「要创建新文件吗」「是否保留更改」、安装向导、UAC。先截图看有没有对话框，再谈别的 |
| Win11 记事本是 **UWP + 多标签** | 窗口属于 `ApplicationFrameHost.exe`（按进程名找不到）；再打开文件是**新标签**；有未保存内容会卡在保存对话框，新的根本打不开 |
| 只 `SetForegroundWindow` 进不了编辑区 | UWP 记事本必须**点一下编辑区**才有光标，否则打字全落空 |
| 点一次就够，开关类按钮点两次是**取消** | Steam 订阅「+」点两次 = 取消订阅（日志 `removing unused item`） |

## 五、Shell / 编码 / 解释器

| 事实 | 怎么办 |
|---|---|
| PowerShell 5.1 的 `Get-Content`/`Set-Content` 管道会**破坏 UTF-8 中文**（按 ANSI 读） | 改文件用编辑器类工具（edit/write），或用 Python 读写 |
| 本机 Python 默认 GBK stdout，中文管道输出变乱码 | `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`，或写文件再读 |
| 两个 Python：系统 `C:\Program Files\Python314\python.exe`（3.14）与工具 venv（3.12） | **ABI 不同**，`computer_mcp` 只能在 venv 里 import；用系统 Python 跑测试会全 skip（假绿） |
| DSH 自带 Python 里有 python-docx / python-pptx / openpyxl / Pillow / lxml / XlsxWriter | 做 Office 文件用那个解释器，不用系统 3.14 |
| `pip install` 在沙箱里会失败（写不了 temp 和 site-packages） | 别重试；真需要就申请提权一次 |
| `curl.exe`（Schannel）在某些站假失败 `SEC_E_NO_CREDENTIALS` | 用 Python `urllib`/`requests` 探；而且 TLS 失败 ≠ 站点不可达 |
| PowerShell 执行策略是 Restricted | `.ps1` 垫片不能跑（`npm`、`pnpm` 裸调失败），用 `.cmd` 形式 |
| `git` 是便携 MinGit（无 bash） | 路径 `%APPDATA%\npm\git\cmd`；多行提交信息用 `git commit -F <file>`，别走 PowerShell here-string |

## 六、性能与内存

| 事实 | 数值 |
|---|---|
| 抓屏 mss 全屏 | **34.6 ms/帧**（29 fps 上限） |
| 窗口区域抓取 | 13.7 ms |
| 块平均降采样 | 4.5 ms |
| 分块差分（380×262） | 1.1 ms |
| JPEG 编码 640×360 q70 | 0.7 ms / 2–5 KB |
| 640×360 图给我看 | ≈300 视觉 token ≈ 我读 6–10 秒 |
| 本机可用内存常态 | 1.6–2.1 GB（总 15.8 GB）→ 批量渲染必须分块（每块 ≤140 帧、独立子进程）；x264 必须 `-threads 2` |
| 环形缓冲 150 帧 | 0.3–1.2 MB，恒定；60 秒实测进程 RSS 128.5 MB 一条直线 |

## 七、QQ / QQNT（2026-10-27 实测）

```
· exe 在 D:\Program Files\Tencent\QQNT\QQ.exe（不在 C 盘默认路径）
· 启动后可能只出现"登录"小窗或根本没有可见窗口
· **它的按键/焦点会落到别的应用上**：实测我的回车落在了 QQ音乐 窗口里（屏幕被 QQ音乐 占住）
```
所以：点 QQ 之前先 `EnumWindows` 确认有**可见的、标题非空**的 QQ 窗口；
没有就别硬按键（会打到别的应用）。QQ 未登录时不要尝试自动化，直接跳过。

## 八、`winfo_id()` 是**子窗口**，抬不动真窗口（2026-10-27 实测）

自动化 Tk / Qt 应用时，`root.winfo_id()` 返回的是**客户区子窗口**。
对它 `SetWindowPos(HWND_TOPMOST)` 抬不动真正的 toplevel，点击会落到别的应用上
（实测：轨道报 `click (431,403)`、按钮一次没被点到，clicks 恒为 0）。

```python
frame = int(root.wm_frame(), 16)      # ← 用这个：toplevel 帧句柄
win32gui.GetWindowRect(frame)         # 外框（含标题栏），比例坐标要按它算
```

**通用规律**：任何"窗口句柄"先问一句——它是客户区还是顶层窗口？
比例坐标必须和 `GetWindowRect` 用的是**同一个**句柄。

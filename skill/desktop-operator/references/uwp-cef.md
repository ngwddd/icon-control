# UWP / CEF / Electron — 通用套路

> 判据很简单：**`ui_tree` 能不能看到真控件**。

## 一、先分流

```
ui_tree 能列出按钮/输入框（名字有意义）
   → 原生 Win32 / WPF / 部分 UWP：走 ui_invoke / ui_click / ui_set_text（最稳，不动鼠标）

ui_tree 只有 1~2 个空壳节点
   → CEF / Electron / 自绘 UI（微信、Steam、QQNT、Discord…）：**只能截图 + 坐标**
```

## 二、UWP 应用（Win11 记事本、设置、商店）

**Windows 11 的记事本是 UWP + 多标签**，有三个坑：

1. **窗口属于 `ApplicationFrameHost.exe`**，不是 `notepad.exe`
   → 按进程名找会找不到。按**标题**（`*.txt - Notepad` / `* - 记事本`）找。
2. **多标签**：再打开一个文件会**新开一个标签页**，而不是新窗口。
   → 如果已有未保存内容，会卡在「是否保存」对话框上，**新的东西打不开**。
3. **只 `SetForegroundWindow` 不进编辑区** → 没有光标，打字全部落空。
   → 必须先**点一下编辑区中心**，再打字。

诊断脚本的正确姿势（`diag_input.py` 的教训）：
```
先建好文件 → notepad.exe <已存在文件> → 点编辑区 → 逐字符打 → Ctrl+A/Ctrl+C → 读剪贴板
少任何一步都会得到"输入被拦"的**假阴性**。
```

## 三、CEF / Electron 通用

```
· 窗口常被隐藏（vis=0）→ 用任务栏按钮或 appkit.activate，别 ShowWindow 硬顶（会得到鬼影）
· 长文本一律剪贴板粘贴
· 页面内的"开关类"按钮点一次就够，再点就是反向操作
· 弹窗（对话框）出现时，整个页面对悬停无响应 —— 先处理弹窗
· 滚动用 mouse_event(WHEEL) 比拖滚动条可靠
```

## 四、判断"这个应用到底能不能用 UIA"

跑一次就够，别重复试：

```
ui_tree(hwnd=目标)  → 节点数 ≥ 10 且名字像人话 → 能用
                    → 节点数 ≤ 2                    → 死心，走坐标
```

已知结论（别再验）：
```
微信 4.x (Weixin.exe)     UIA 不可见
Steam (steamwebhelper)   只回 DocumentControl
QQNT                      部分可见（聊天列表可点）
Win11 记事本 (UWP)        可见，但有标签/对话框陷阱
```

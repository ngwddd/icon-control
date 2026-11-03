# v1.3.2 单窗口授权 · 实现与验证记录

基线：`v1.3.1`（预发布）。本轮不新增工具，只重做授权入口与授权有效期。

## 一、需求（用户拍板）

| 决策 | 落地 |
|---|---|
| 窗口用原生（B 方案） | `comctl32!TaskDialogIndirect`，纯 ctypes，无 Tk、无 C# |
| 默认时长 60 分钟 | 租约 `lease_expires_at = now + 60*60`，到期自动失效 |
| 热键挑偏僻的 | `Ctrl+Alt+Shift+F9`，被占用时回退 F7 / F12 / G |
| DSH 胶囊彻底删除 | 插件不再渲染按钮，`quick_grant.py` 与三条 IPC 删除 |
| 接受身份继承 | `agent_id = sha256(安装目录 + 工作区)[:32]`，60 分钟内新进程自动继承 |
| 不保留「高级」窗 | 授权窗口只有三档预设，没有逐项勾选入口 |

## 二、实现

- `_patched/native_dialog.py`：TaskDialog 封装（`ask_grant` / `ask_status`）。
- `_patched/native_tray.py`：`Shell_NotifyIcon` 封装（add / update / balloon / remove）。
- `_patched/native_consent.py`：常驻宿主。隐藏窗口 + 消息循环 + 托盘 + 热键 + 心跳；`WM_SHOW` 唤醒、`WM_HOTKEY` 打开、`WM_TIMER` 续租。
- `_patched/consent.py`：默认委托给原生宿主；`--tk` 仅留给内部调试。
- `agent_session.identity()`、`capabilities.check_scope`、`permission.status`、`consent_ipc.dispatch`：身份租约贯通。
- `control.blocking_reason`：授权时间晚于最后一次物理输入时直接交接控制权。

## 三、踩到的四个坑（都写进代码注释了）

1. **`TASKDIALOG_BUTTON` 是 pack(1)**：x64 下 12 字节，用默认对齐会 access violation。`TASKDIALOGCONFIG` 同理（160 字节）。
2. **`WM_HOTKEY` 常量漏定义**：`_on_message` 里抛 `NameError`，被 ctypes 回调静默吞掉，表现是"热键注册成功但没反应"。已补常量，并加回归用例直接调用 `_on_message`。
3. **`TrackPopupMenu` 需要前台权限**：后台进程隐藏窗口上调用，菜单弹不出来（空白小框）。改成**托盘点击直接打开同一个授权窗口**，撤销/续期/退出都在窗口里，少一个脆弱 API。
4. **后台进程的对话框可能在后面**：加了 `_force_foreground()` 轮询抢前台；没有真实输入时 Windows 仍可能拒绝，这是系统规则。

## 四、验证（本机，1.3.2）

| 项 | 结果 |
|---|---|
| 授权窗口渲染 | ✅ 三档预设、60 分钟复选框默认勾选、两个按钮 |
| 回车即授权 | ✅ `granted=true`，`lease_expires_at` 剩 3592 秒 |
| 新进程继承 | ✅ 不同会话、同工作区 → `granted=true` |
| 跨工作区不继承 | ✅ 从 `%TEMP%` 启动 → `granted=false` |
| 紧急撤销 | ✅ 立即 `false`，宿主心跳自动退出 |
| 托盘注册 | ✅ `state/consent-host.json` → `"tray": true` |
| 托盘点击 | ✅ 打开授权窗口（`WM_TRAY` 注入验证） |
| 热键注册与回退 | ✅ 本机 F9/F7 被占，实际绑定 `Ctrl+Alt+Shift+F12` |
| 回归 | ✅ 542 项 / 0 失败 / 0 错误 / 3 跳过 |

## 五、已知限制

1. **合成按键不触发全局热键**（SendInput 不进入 RegisterHotKey 派发），所以热键只能由真人按键确认；消息处理路径已用 `WM_HOTKEY` 注入验证。
2. **托盘图标默认在 Win11 的隐藏区**，需要在任务栏设置里固定。
3. **本机 F9 被占用**，实际是 F12；换机器可能又不同，以 `state/consent-host.json` 为准。
4. **32 项真机验收仍是 13/32**，`acceptance.json` 保持 blocked，因此继续以预发布版提供。

## 六、交付

- 标签：`v1.3.2`（预发布）
- 回归证据：`.runtime/test-results.json`（CI artifact）
- 宿主自检：`%LOCALAPPDATA%\IconControl\state\consent-host.json`

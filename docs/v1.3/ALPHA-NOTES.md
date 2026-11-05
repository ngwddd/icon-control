# ICON Control 1.3.9-alpha — 范围与验证说明

> 版本：`1.3.9a1`（预发布）
> 基线：`1.3.8` / `e3a8142`
> 分支：`v1.3.9-alpha`
> 日期：2026-11-06

## 这一版解决什么

1. **不再自动弹窗**：授权宿主默认后台意图（`--intent=background`），安装、重启、MCP 重连、页面刷新都不会升起授权窗口。
2. **授权桥不可用时不弹模态框**：改为托盘“状态未知” + `consent-host.json(last_sync_ok=false)` + 工具返回 `authority_unavailable`。
3. **错误说得清**：工具拒绝结果带 `code`；参数错误是 `invalid_argument`，不再是“未授权”。
4. **组合键可用**：`key_press('ctrl+f')`；`batch` 里的 `key_down/key_up` 明确拒绝并提示改用顶层工具。

## 不包含（留给后续版本）

- 长期信任（30 天、跨会话继承）——仍按会话授权
- 撤销代际（`revocation_generation`）
- `frame_id` 坐标契约与 Precision Engine（点偏问题仍是已知限制）
- 应用白名单改为纯审计日志

## 验证方法

### 单元/回归

```powershell
# 需要能 import computer_mcp 的解释器（本机为 IconControl 的 3.12 venv）
python tools\verify.py --pattern "test_*.py"
```

本版实测：`run=660, failures=0, errors=0, skipped=3`。

新增用例：

```
tests/test_v139_consent_intent.py   18 项：意图解析、命令行白名单、静默启动、状态文件
tests/test_v139_error_codes.py       8 项：code 映射、authority 健康块、/status health
tests/test_v139_gate_codes.py        7 项：异常分类、参数值不外泄
tests/test_v139_key_chords.py       15 项：组合键顺序、key_down/key_up 拒绝、batch 提示
```

### 真机（桌面）

```powershell
$env:IC139_PYTHON = "<装有 alpha 的 python.exe>"
powershell -ExecutionPolicy Bypass -File tests\manual\verify_v139_silent_start.ps1
```

脚本会：停掉当前宿主 → 用隔离 `ICON_CONTROL_HOME` 以 `background` 启动 → 断言

- IconControl 窗口存在但 `visible=False`
- 前台窗口 hwnd 前后不变
- `consent-host.json` 记录 `intent=background`、`last_sync_ok=false`、`granted=null`
- 第二次后台启动不改变窗口集合与前台窗口

本版实测记录（2026-11-06，本机）：`docs/v1.3/evidence/` 目录被 `.gitignore` 排除，故把关键输出固化在这里。

```
=== A. baseline ===
  [before] IconControl windows: none
  [before] foreground hwnd: 6294642
=== C. background intent start (isolated home, no bridge) ===
  py: {'opened': True, 'woken': False}
=== D. observe ===
  host pid=3244 parent=3848 / host pid=14920 parent=3244
  [after] IconControl windows: 93916780|14920|False|IconControlConsentHost
  [after] foreground hwnd: 6294642
  consent-host.json: {"pid": 14920, ..., "tray": false, "intent": "background",
                      "last_sync_ok": false, "granted": null, ...}
=== E. a second start must not wake the window ===
  foreground before=6294642 after=6294642  unchanged=True
  [second] IconControl windows: 93916780|14920|False|IconControlConsentHost
```

结论：后台启动只建窗不显示、不抢焦点、不弹模态；桥不可用时通过状态文件与托盘表达；二次启动无副作用。

## 已知限制

| 限制 | 说明 |
|---|---|
| 托盘注册可能失败 | 非交互会话下 `Shell_NotifyIcon` 可能返回 false（本机测试环境即如此）；此时热键仍可用，`consent-host.json.tray=false` 可供诊断 |
| 宿主重启后仍需重新授权 | 授权仍绑定会话，本版未引入长期信任 |
| `batch` 不支持按住键 | `key_down`/`key_up` 跨步骤持有会在失败时留下按住的修饰键；请用顶层工具 |
| 点偏风险仍在 | 坐标契约（`frame_id`）未实现，模型仍需自行换算物理像素 |
| `key_press` 组合键只覆盖普通键 | 窗口定向版本（`key_press_to_window`）暂不支持组合键 |

## 升级建议

- 这是预发布：建议先在测试机验证“启动不弹窗”和“组合键可用”，再替换正式安装。
- 替换方式与 1.3.8 相同（wheel 覆盖安装）；回滚到 1.3.8 直接重装旧 wheel。

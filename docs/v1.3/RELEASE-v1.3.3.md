# Icon Control v1.3.3

授权体验的收尾修补。功能与 v1.3.2 相同，修的是"能跑起来之后才会遇到的问题"。

## 修复

- **托盘点击改为直接开窗口**：`TrackPopupMenu` 在后台隐藏窗口上弹不出来（渲染成空白小框）。现在点托盘打开同一个授权窗口，撤销/续期/退出都在窗口里。
- **租约到期由客户端自己判**：`permission.status` 现在直接检查 `authorization.lease_expires_at`，不再依赖桥进程重写状态文件。桥崩溃或卡住都不会把租约拖长。
- **宿主启动即写诊断**：`state/consent-host.json` 一开始就记录 pid、实际绑定的热键、托盘是否注册，不用等第一次授权。
- **窗口抢前台**：授权窗口出现后会主动请求前台（Windows 只在真实输入后才给权限，所以在后台被拉起时仍可能停在后面）。

## 新增文档

- `docs/v1.3/CONSENT-USAGE.md`：热键 / 托盘 / 三档预设 / 60 分钟租约 / 续期撤销 / 常见故障对照表。
- `docs/v1.3/AUDIT-1.3.2.md`：单窗口授权的实现与验证记录（含本轮踩的 4 个 ABI/API 坑）。

## 验证

- 回归：**544 项运行 / 0 失败 / 0 错误 / 3 跳过**（新增租约到期用例 2 项）。
- 本机安装：`version 1.3.3`、89 工具、`consent-host.json` 显示 `hotkey: Ctrl+Alt+Shift+F9`、`tray: true`。

## 仍然待办

- 32 项真机验收仍未跑完（13/32 + 本轮待跑的 B11/B12/B20/B21/B26/B28），`acceptance.json` 保持 `blocked`，因此继续以**预发布版**提供。
- `Ctrl+Alt+Shift+F9` 在部分机器上可能被占用，实际绑定见 `state/consent-host.json`。

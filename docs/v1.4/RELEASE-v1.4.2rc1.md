# Icon Control v1.4.2-rc1

通用能力补齐版。**没有新增工具**（仍是 96 个），修的是"能按住键、能对得上坐标、能看见焦点"。

## 修了什么

| 缺口 | 修法 |
|---|---|
| 只能点按，不能按住键 | `key_press(hold_ms=...)`；`batch` 支持 `key_down`/`key_up`，失败时自动释放 |
| 截图不返回 `frame_id`，坐标只能手工换算 | `screenshot` / `screenshot_window` 返回 `frame_id`，`click` 直接吃图片坐标 |
| 不知道键盘焦点在谁身上 | `control_status` 新增 `foreground_hwnd` / `focus_hwnd` / `focus_class` / `focus_process` / `focus_source` |
| 弹窗 `bounds` 为 0×0 | `GetWindowRect` → DWM 扩展边框 → 客户区，附 `bounds_source` |
| 窗口信息缺客户区/DPI | `list_windows` / `get_window_info` 增加 `client` 与 `dpi` |

## 为什么是这四个

一份实测报告（一下午、21 张截图、2 局游戏）指出：三分之一的时间花在 `keybd_event` /
`GetGUIThreadInfo` / `CopyFromScreen` 这些原生调用上——说明缺的是**通用原语**，不是功能。
这四条都不为某个应用定制：长按、图片坐标点击、焦点诊断、坐标换算对任何桌面任务都成立。

## 验证

- 回归 **870 项 / 0 失败 / 0 错误 / 3 跳过**
- 真机：截图 → frame_id → 图片坐标点击；按住 W 300ms；`control_status` 焦点归属

## 备注

`batch` 以前会明确拒绝 `key_down`（报错让你用顶层工具）。现在允许，但要记住：
**序列里按下的键会在结束时释放**，不需要也不应该再手动收尾。

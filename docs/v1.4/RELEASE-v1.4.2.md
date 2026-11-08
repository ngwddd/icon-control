# Icon Control v1.4.2

正式版。工具数不变（96），补的是**桌面操作的原语**与**安全绑定**：
按住键、截图坐标直连、焦点诊断、窗口边界；以及"这个点击到底发给了谁"。

## 新增原语

| 能力 | 用法 |
|---|---|
| 长按 | `key_press(key="w", hold_ms=300)`；上限 10 秒，可被急停/接管中断，支持 `ctrl+w` 组合 |
| 批量按键 | `batch` 的 `key_down` / `key_up`，结束自动释放并列出 `released_keys` |
| 图片坐标点击 | 截图返回 `frame_id`，`click(frame_id=..., x=..., y=...)` 直接换算 |
| 焦点诊断 | `control_status` 报 `foreground_hwnd` / `focus_hwnd` / `focus_class` / `focus_process` |
| 窗口信息 | `list_windows` / `get_window_info` 带 `client` 与 `dpi`，0×0 弹窗自动回退 |

## 安全绑定

- 窗口截图带目标身份（hwnd + pid + 进程创建时间）；被遮挡、移动、句柄回收时**拒绝注入**。
- 拖拽检查起点与终点，异常路径释放鼠标键。
- 按键释放失败会如实返回 `released=false` / `success=false` / `release_failed`，不再假报成功。
- `batch` 遇到卡住的修饰键立即中止，后续输入不执行。

## 验证

- 回归 **889 项 / 0 失败 / 0 错误 / 3 跳过**
- 真机：frame 坐标 (640,360) → 屏幕 (1280,720)；hold 250ms 实测 262ms 后释放；
  遮挡窗口点击被拒且鼠标未移动
- 真机任务：朋友圈第 4/5 条、视频号首条读取与「不感兴趣」

## 已知限制

- 自绘界面（微信 4.x 等）没有 UIA 树，只能坐标 + OCR
- 部分应用的 ValuePattern 只读（如 Win11 记事本）：返回 `no_effect`，不假报成功
- 多区域截图/OCR 仍是逐块采集（接口一次调用，底层未共享单帧）

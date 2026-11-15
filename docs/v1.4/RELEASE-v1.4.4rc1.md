# Icon Control v1.4.4-rc1

预发布。工具数 96 → **97**（新增 `focus_window`）。

这一版不来自 roadmap，来自一次**真实操作记录**：用助手在 Edge 里走 GitHub 设备授权，
中途因为"坐标系、前台、OCR 选错目标"返工约 8 次。下面每条都对应那次的具体现象。

## 改了什么

| 现象（原文） | 现在 |
|---|---|
| `click(x=1316, y=1504)` → 空 `ValueError` | 报 `outside the screen (0..2559, 0..1439)`，并提示可改用 `frame_id` |
| `find_text` 给的 `cy=1504` 是窗口坐标，屏幕只有 1440 | 每条命中带 `onscreen`，返回体带 `screen`（虚拟桌面矩形） |
| 窗口截图里按钮很清楚，屏幕上点不到 | `screenshot_window` 返回 `clipped_by_screen` / `visible_rect` / `offscreen_px` |
| `click_text("Authorize github")` 点到了标题 | 排序加入 `slack`：同样命中时，比 query 多字最少的优先 |
| 不知道它在多个候选里选了哪个 | 返回 `candidates` + `chosen_index` + `ratio` |
| 目标在屏幕外仍然点了 | 返回 `code=offscreen_target`，不注入 |
| `SetForegroundWindow` 失败后要自己写 Win32 | 新增 `focus_window`：多重兜底 + **回读确认** |
| 控制权被释放时只看到一句 `ValueError` | 返回 `code=permission_denied` + 原因 + 提示先 `control_claim` |

## 新增工具

```json
{"name": "focus_window", "hwnd": 1234, "restore": true}
→ {"focused": true, "foreground_before": {...}, "foreground_after": {...},
   "attempts": ["restore", "bring_to_top", "set_foreground"]}
```

`focused=false` 说明 Windows 拒绝了跨进程抢前台，返回体会给 `next_action`：
先把挡住的窗口最小化再重试，或在目标窗口里点一下。

## 验证

- 回归 **946 项 / 0 失败 / 0 错误 / 3 跳过**
- 新增 12 项：越界与虚拟桌面坐标、`slack` 排序、候选返回、屏幕外拒绝、
  `focus_window` 成功/被拒/窗口消失、裁剪标注

## 已知限制

- `focus_window` 依赖 Windows 的前台规则：某些全屏独占程序仍可能拒绝
- `slack` 是启发式（"更贴近 query 的那行更像按钮"），不保证对所有页面成立；
  返回 `candidates` 就是为了让调用方能够自己复核
- 模板"屏幕抓图 vs 窗口位图"两个采集通道仍未统一

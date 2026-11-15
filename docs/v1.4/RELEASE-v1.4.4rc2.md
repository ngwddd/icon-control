# Icon Control v1.4.4-rc2

RC1 的审计修复版。工具数不变（97）。

## 修了什么

| 审计项 | 问题 | 修法 |
|---|---|---|
| ① | 越界提示被 MCP 层吞成 `Tool execution failed` | 参数错误走 `ArgumentError`，`code`/`hint`/数据原样返回；其它异常仍脱敏 |
| ② | `click_text(hwnd=…)` 不核验窗口归属 | 按下前 `WindowFromPoint` 比对顶层窗口，不符 `target_occluded` |
| ③ | `focus_window` 用了 `win32gui.GetWindowThreadProcessId`（不存在） | 改用 `win32process`，兜底路径真实可达 |
| ④ | 焦点没拿到也报 `success=true` | `success = focused`；未拿到为 `focus_denied` + `next_action` |
| ⑤ | 两个相同候选按 Y 坐标猜 | 判 `ambiguous_target`，要求显式 `index` |
| ⑥ | `index=-1` 会选中最后一个 | `invalid_index`；屏幕外候选不参与自动选择 |
| ⑦ | `wait_for(template)` 读错字段，必然超时 | 兼容 `matched` / `found` |

## 行为变化（会影响调用方的地方）

- `click_text` 的 `index` 默认从 `0` 改为 `None`（自动选择）；显式越界/负数会被拒绝。
- `focus_window` 在没抢到前台时返回 `success=false`（此前是 `true`）。
- 相同候选不再自动点击，需要 `index` 指定。

## 验证

- 回归 **960 项 / 0 失败 / 0 错误 / 3 跳过**
- 真机：MCP 层错误透传、歧义拒绝、窗口归属拒绝、焦点回读、模板等待

## 已知限制

- `ambiguous_target` 只在"文本完全相同"时触发；文本相近但语义不同（"保存"/"另存为"）仍按 slack 排序。
- 多显示器用虚拟桌面外接矩形，显示器之间的空白区域无法区分。
- 模板"屏幕抓图 vs 窗口位图"两个采集通道仍未统一。

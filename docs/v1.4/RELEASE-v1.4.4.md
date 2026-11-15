# Icon Control v1.4.4

正式版。97 个工具（新增 `focus_window`）。

这一版来自两次真实审计，主题只有一个：**识别结果能不能安全地变成一次鼠标按下**。

## 修掉的阻断问题

| 编号 | 问题 | 修法 |
|---|---|---|
| P0 | `click_text` 经 MCP 调用时 `index` 恒为 0，歧义拒绝永远不触发 | 分发层传 `None`，让函数自己判断 |
| P0 | `click_template(hwnd=…)` 不绑定窗口，遮挡窗口会收到点击 | 按下携带 `expected_point` + `expected_hwnd` |
| P0 | `expected_point` 被包在进程身份检查里，漂移不拦 | 独立校验，注入前执行 |
| P1 | `ui_click` 检查后到注入之间存在竞态 | 按下绑定 `expected_hwnd` |
| P1 | 右键/中键实际都点左键 | 显式三键映射 |
| P1 | 模板"歧义"被当成"已消失" | `verdict`: present / absent / inconclusive |
| P1 | OCR 归属校验异常时降级为无绑定点击 | 返回 `target_unverified`，零注入 |
| P1 | 大小写不同绕过歧义判断 | 按 `case_sensitive` 归一化 |
| P1 | 无区域时只搜主屏 | 抓虚拟桌面（含副屏） |
| P2 | 区域缺参静默扩大搜索 | 缺一即 `invalid_argument` |
| P2 | `ui_click` 的 ref/element_id 不在 Schema | 已暴露，name 可选 |

## 验证

- 回归 **974 项 / 0 失败 / 0 错误 / 3 跳过**
- 新增 14 项打在 MCP 边界：参数透传、模板点击绑定、右键/中键、指针漂移、
  模板歧义 verdict、区域不完整、归属失败零注入、虚拟桌面抓图

## 已知限制

- 遮挡检测依赖 `WindowFromPoint` 的顶层窗口；被同一窗口内的子窗口/重叠控件挡住时无法区分。
- 模板"屏幕抓图 vs 窗口位图"两个采集通道仍未统一（跨通道匹配可能失败）。
- 多显示器用虚拟桌面外接矩形，显示器之间的空白区域无法区分。
- 微信/游戏类自绘界面的长跑基准仍未建立。

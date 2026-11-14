# Icon Control v1.4.3

正式版。工具数不变（96）。这一版解决的是"观察是否省、判定是否准"，不是加功能。

## 新增能力

| 能力 | 用法 | 实测 |
|---|---|---|
| 精准查询 | `ui_find(control_type=…, automation_id=…, enabled=…)`，边走边匹配 | 找地址栏 135.0 → 124.5 ms |
| 跳过身份读取 | `ui_tree(with_ids=false)` | 138.8 → 126.0 ms |
| 局部模板重定位 | `match_template(previous=[x,y], radius=160)` → `moved_by` | 53.3 ms vs 整窗 112.5 ms |
| 三态验证 | `execute_verified(expect={"kind":"absent"})` 只在**跑完且无读取错误**时判定不存在 | 截断扫描 → `executed_unverified` |

## 修掉的缺陷（都是"会点错/会误判"这一类）

1. `match_template(hwnd=…)` 返回窗口相对坐标，文档却承诺屏幕坐标。
2. OCR 候选缺 `ratio` 时按满分计，能压过 UIA 精确命中。
3. `ui_find` 未命中时 `max_nodes` 失效，会走完整棵树。
4. `index ≥ 10` 返回 `target=None`。
5. `search_region` 越界 → 坐标偏移，完全越界时甚至虚假命中。
6. `found=false` 的返回里仍带 `x/center`，看起来可以直接点。
7. **双击与拖拽的最终窗口校验没生效**（`expected_hwnd` 被包在进程身份检查里，从未触发）。
8. **深度未展开的扫描被当成"已证明不存在"**。
9. Wheel 的 `source_dirty=true` 与 CI 记录不一致（provenance 复用了旧文件）。

## 有意不做

按项目要求，**不加身份验证类的限制**：`with_ids=false` 只是省一次属性读取，
不会因此把引用降级、也不会额外抓图。需要长期引用时用带 `automation_id` 的查询重新取目标。

## 验证

- 回归 **934 项 / 0 失败 / 0 错误 / 3 跳过**
- 基准工具 `tools/bench/`：观测微基准（遍历 vs 属性）、固定任务集（独立判据）、A/B 交替测量
- 真机（Windows 11）：查询/预算/越界拒绝、自绘窗口 OCR、模板跟踪位移、三态判定

## 已知限制

- 资源管理器**文件列表项不在 UIA 树里**，按文件名定位仍不可行。
- 模板"屏幕抓图"与"窗口位图"两个采集通道未统一，跨通道可能匹配失败（下一版优先）。
- 视觉跟踪是局部重搜，不是长期身份跟踪：缩放、旋转、大面积重绘会拒绝（`below_threshold` / `ambiguous`）。
- `scan_complete` 的含义是"配置的深度与预算内读完"，不代表 UIA 未暴露或虚拟化的控件不存在。

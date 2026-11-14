# Icon Control v1.4.3-rc1

预发布。工具数不变（96）。这一轮的目标不是"加能力"，而是**先测量再优化**——
每条性能结论都有前后对比，没有数据支撑的优化没有写进来。

## 改了什么

| 方向 | 变化 | 实测 |
|---|---|---|
| 查询 | `ui_find` 边遍历边匹配 + `truncated`；`control_type`/`automation_id`/`enabled` 条件 | 找地址栏 135.0 → 124.5 ms（−7.8%） |
| 读取 | `ui_tree(with_ids=false)` 跳过 AutomationId | 138.8 → 126.0 ms（−9.2%） |
| 视觉 | `match_template(previous=…, radius=…)` 跟踪 + `moved_by` | 53.3 ms vs 整窗 112.5 ms（−53%） |
| 安全 | 分数不足 / 双峰歧义 / 跟踪框越界 → 拒绝给坐标 | 新增 9 项测试 |

## 修掉的缺陷

1. **`match_template(hwnd=…)` 返回窗口相对坐标**（文档承诺屏幕坐标）——跟踪功能把它暴露了出来。
2. **OCR 候选缺 `ratio` 按满分 1.0 计**——改为 0.5 + `ratio_missing`。

## 没做的（以及为什么）

| 项 | 原因 |
|---|---|
| 原生 `ElementFindFirst` | `uiautomation` 的封装会 10 s 超时（未命中和命中都实测过）；要做得绕开库直接 comtypes |
| 增量 `ui_tree(mode=delta)` | 只省传输不省遍历；身份配对是独立课题 |
| `ui_read_table` / TextPattern / CDP | 与当前主要场景（微信、游戏）无关，等真实需求 |

## 验证

- 回归 **906 项 / 0 失败 / 0 错误 / 3 跳过**
- 真机：资源管理器跟踪（窗口移动 +80/+60，跟踪结果一致）、记事本/资源管理器查询任务
- 前后对比用 `tools/bench/ab_runner.py` 交替测量，避免环境漂移

## 已知限制

- 资源管理器的**文件列表项不在 UIA 树里**，按文件名定位仍不可行
- 跟踪是整块平移假设：目标缩放、旋转或大面积重绘时会失效（此时返回 `below_threshold` 或 `ambiguous`）
- `ui_find` 的 `truncated=true` 表示 `found` 是下界，需要总数时把 `max_hits` 调大

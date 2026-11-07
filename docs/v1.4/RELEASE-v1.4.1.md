# Icon Control v1.4.1

正式版。**授权模型与 v1.4.0 完全一致**（连接即授权 + 急停 + 接管 + 目标校验），
这一版补的是"定位准不准、输入真的进没进去、一次调用能干多少事"。

## 六个新工具（90 → 96）

- `find_elements_ranked`：多来源融合定位，带置信度与歧义标记
- `element_state`：读控件真实状态（启用/可见/值/勾选）
- `element_action`：按控件能力执行，可回读校验
- `type_verified`：输入后回读，丢字会被发现
- `execute_verified`：定位 → 执行 → 等后置条件，返回 `verified_success` / `no_effect` / `target_changed` / `executed_unverified` / `verified_absent`
- `scroll_into_view`：长列表滚动到目标

## 关键改进

- **元素引用跨窗口移动可用**：按子控件索引路径重新解析，返回当前坐标，绝不回退旧坐标
- **定位不再"先命中先返回"**：UIA 优先，缺失/歧义才用 OCR/模板；两个候选分不清就 `ambiguous`
- **动作不再假装成功**：Pattern 抛异常会如实上报；`set_value` 走 `SetValue` 并读回
- **输入前先确认焦点**：焦点拿不到就 `focus_failed`，键盘调用 0 次
- **引用失效 ≠ 元素消失**：`absent` 会按名字复查，确认查不到才算消失

## 验证

- 回归 **857 项 / 0 失败 / 0 错误 / 3 跳过**
- 真机：记事本文档状态读取、焦点校验后输入 `verified_success`、窗口移动后引用可用、
  `set_value` 如实报 `no_effect`、`absent` → `verified_absent`
- 真机任务：朋友圈第二条与视频号首条读取后汇报到文件传输助手

## 已知限制

- 自绘界面（微信 4.x 等）没有 UIA 树，只能用坐标 + OCR
- 某些应用的 ValuePattern 只读或无效（如 Win11 记事本）：工具返回 `no_effect`，不假报成功
- 多区域截图/OCR 仍是逐块采集（接口已支持一次调用，底层未共享单帧）

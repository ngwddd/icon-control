# Icon Control v1.4.1-rc1

功能增强候选版。**授权模型与 v1.4.0 完全一致**（连接即授权 + 急停 + 接管 + 目标校验），
这一版只改"能不能一次做对"。

## 新增 6 个工具（90 → 96）

- `find_elements_ranked`：多来源融合定位，带置信度与歧义标记
- `element_state`：读控件真实状态（启用/可见/值/勾选）
- `element_action`：按控件能力执行，可回读校验
- `type_verified`：输入后回读，丢字会被发现
- `execute_verified`：定位 → 执行 → 等后置条件，返回四种结局
- `scroll_into_view`：长列表滚动到目标

## 关键修复

- **元素引用不再随截图失效**：改为按子控件路径重新解析，窗口移动也能用；
  失效时明确报 `stale_element`，绝不回退旧坐标
- **定位不再"先命中先返回"**：UIA 优先，缺失/歧义才用 OCR/模板；分不清就 `ambiguous: true`
- **输入不再"发出去就算成功"**：`type_verified` / `execute_verified` 会回读
- `screenshot(regions=[...])`、`ocr_read(regions=[...])`、`wait_for(any=[...])` 减少往返

## 验证

- 回归 **822 项 / 0 失败 / 0 错误 / 3 跳过**

真机（Windows 11 + 记事本 11 + 微信 4.x，安装的是本版 wheel）：

| 检查 | 结果 |
|---|---|
| `element_state` 读记事本文档 | ✅ `DocumentControl`，enabled/focused/`value`（31453 字符）都读到了 |
| `type_verified` 输入中文 | ✅ `verified_success`（reason `inserted`，字段长度 +14） |
| 引用跨"标题变化"存活 | ✅ 编辑后标题多了 `*`，引用仍然可用（标题不再参与身份判定） |
| `element_action set_value` | ⚠️ `no_effect` —— Win11 记事本的 DocumentControl **不接受** ValuePattern 写入；工具如实报告，没有假装成功 |
| `execute_verified` 同上 | ⚠️ `no_effect`，与上一条一致 |
| `find_element` 融合 | ✅ `source=ocr`，两个"搜索"候选 → `ambiguous: true` |
| 微信（自绘界面） | UIA 树为空；`element_state` 会明确返回 `no_path`，不猜坐标 |

第三条（标题变化）是这轮真机才发现的 bug：以前窗口标题进身份校验，记事本一打字标题就变，
后面的引用全部 `stale_element`。已修。

## 已知限制

- **自绘界面（微信 4.x 等）没有 UIA 树**：`element_state` / `element_action` 会明确返回 `no_path`，
  这类窗口只能用坐标 + OCR
- OCR/模板命中的候选没有结构路径，同理
- 某些应用的 ValuePattern 是只读或无效（如 Win11 记事本）：工具会返回 `no_effect`，不会假报成功
- `read_table` / `drag_to_target` 未实现（计划在 R3，未纳入本版）
- 仍为预发布

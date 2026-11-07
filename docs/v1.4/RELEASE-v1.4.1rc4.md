# Icon Control v1.4.1-rc4

RC3 的语义修复版 + **第一次真机复核**。仍然 96 个工具，没有新增。

## 修了什么（D01–D06）

| 编号 | 问题 | 修法 |
|---|---|---|
| D01 | UIA 查询报错被当成"元素已消失" | `absent` 复检要求 `ui_find` 返回 `ok=true` 且 `found==0`；查询失败 → `executed_unverified` |
| D02 | 只给 query 的 `absent` 永远失败 | 没有 `ref` 时按名字直接查询，作为正式支持的验证路径 |
| D03 | 目标存在但 `SetFocus` 失败仍然打字 | 输入前必须确认焦点；失败且控件当前无焦点 → `focus_failed`，键盘调用 0 次 |
| D04 | 跳过动作却报动作成功 | 返回 `verified_absent` + `action_executed=false` + `observation_only=true` |
| D05 | 滚动计数与实际不符 | 分开返回 `wheel_scrolls` / `uia_scrolls`；UIA 滚动后加短暂等待 |
| D06 | 长文本只截断了部分工具 | `element_action.after`、`execute_verified.before` 也走 `_trim_state()` |

## 真机复核（Windows 11 · 本版 wheel · 已安装运行）

| 场景 | 结果 |
|---|---|
| 读记事本文档状态 | ✅ `DocumentControl`，focused=true，value 按长度摘要（31,467 字符不回灌全文） |
| 焦点校验后输入中文 | ✅ `verified_success`（`inserted`，长度 +14），`action_executed=true` |
| 窗口移动后引用是否还可用 | ✅ 窗口从 (300,38) 移到 (429,210)，同一 ref 仍解析成功，返回新 bounds |
| `set_value` 的真实结果 | ⚠️ `no_effect` —— Win11 记事本不接受 ValuePattern 写入，工具如实报告，`action_executed=true` |
| 不存在的目标上做 `absent` 断言 | ✅ `verified_absent`，`action_executed=false`（D02 + D04 同时验证） |
| 微信（无 UIA 树）上的融合定位 | ⚠️ 本轮未命中（OCR 在该窗口表面没找到查询词），未产生错误结果；融合路径本身在屏幕 OCR 场景已验证 |

结论：**"找到目标 → 准确执行 → 正确确认"这条链路在真机上跑通了**；
两处 ⚠️ 都是应用侧限制，工具没有谎报。

## 验证

- 回归 **857 项 / 0 失败 / 0 错误 / 3 跳过**（新增 9 项覆盖 D01–D06）
- 发布门禁：版本一致、回归绑定提交、stdio + HTTP 均 96 工具、无凭证 401

## 仍未做

- 多区域截图仍是逐块采集（接口保留，底层未共享单帧）
- 微信这类自绘窗口没有 UIA 树，只能用坐标 + OCR

## 仍是预发布

正式版建议在 RC4 真机复核结论被接受后发布。

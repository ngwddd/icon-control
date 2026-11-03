# Icon Control v1.3.5

授权窗口从"猜该点哪一档"变成"告诉你缺什么"。

## 新增

- **窗口会说出缺什么**：被拦下的调用把缺失作用域带到窗口，抬头下直接写「本次调用需要：file_write」。
- **自动预选最小可用预设**：只读 / 常用 / 全部里挑**能覆盖该请求的最小一档**并预选。只读屏幕 → 只读；普通点击打字 → 常用；要文件或剪贴板 → 全部。
- `tools/acceptance_report.py`：`acceptance.json` 的唯一生成入口，按 SHA 绑定 + 哈希校验组装证据，跨提交的旧证据自动标 `stale`。
- S5 用例 **B22（遮挡）** 与 `tests/manual/cover_window.ps1`。

## 验证

- 回归：**550 项 / 0 失败 / 0 错误 / 3 跳过**（新增 4 项预设选择用例）。
- 真机：用 `capture_template`（需要 `file_write`）触发拦截 → 窗口显示「本次调用需要：file_write」且预选「全部」。

## 升级提醒

改的是桥进程里的 IPC 逻辑，**升级后必须重启授权桥和宿主**（`permission_bridge` / `computer_mcp.consent`），否则新字段不会被识别。

## 仍未签收

32 项真机验收在当前提交上尚未重跑（旧证据已标 stale），`acceptance.json` 保持 `blocked`，本版继续以预发布版提供。

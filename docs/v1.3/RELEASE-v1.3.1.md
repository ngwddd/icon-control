# Icon Control v1.3.1

安全修补版，对应独立审计对 v1.3.0 提出的 P0 与 P1 项。**不重构授权模型，不增加工具。**

## 修复

- **快捷授权身份漂移（P1-01）**：保存的 Agent 退出后，即使它是唯一在线会话，也不再沿用旧目标；
  必须重新绑定，界面提示"已保存的目标已失效"。
- **剪贴板读取权限分离（P1-02）**：新增 `clipboard_read`。宏的 `clipboard_get` / `assert_clipboard`
  不再能凭 `text_entry` 读取系统剪贴板；执行日志与错误只记录长度与是否匹配，不再回显内容。
- **剪贴板写入权限与恢复（P1-03）**：新增 `clipboard_write`。`clipboard_set` 与带文本的 `paste`
  需要显式授权；内部临时粘贴在剪贴板未被其他程序改写时恢复原内容。
- **范围说明（P1-04）**：一键授权界面明确"读取整个桌面（含未授权窗口）"，并补上剪贴板读写说明。
- **副作用精简（P2-01）**：`capture_daemon` 不再声明未使用的 `file_write`。
- **发布闸门（P0）**：正式版必须通过 `tools/release_gate.py` 的 SHA 绑定证据校验；
  未通过时只能发布预发布版。

## 验证

- 回归：536 项运行、0 失败、0 错误、3 跳过
- 89 个 MCP 工具、stdio/HTTP 协议自检、wheel/sdist 构建与包完整性检查通过
- 新增 18 个针对性用例（`tests/test_v131_security.py`）

## 尚未签收

`docs/v1.3/DESKTOP-BENCHMARKS.md` 的 32 项真机验收、100%/200% DPI、干净 Windows 账号安装、
撤销/急停物理动作仍未完成，`docs/v1.3/acceptance.json` 保持 `blocked`。
因此本版本按 Release Gate 规则**以预发布版提供**，不得据此宣称已通过全部稳定版验收。

详见 `docs/v1.3/AUDIT-1.3.1.md`。

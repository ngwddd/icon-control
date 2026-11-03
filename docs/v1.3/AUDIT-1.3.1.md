# v1.3.1 独立审计整改记录

基线：`34bc17025224a85134ad043657ba7f611733195a`（v1.3.0 正式版）

本轮只做小范围缺陷修复，不重构授权模型、不增加工具数量。每项都先补失败测试，再提交修复。

## 一、已修复

| 编号 | 审计结论 | 修复 | 回归测试 |
|---|---|---|---|
| P1-01 | `QuickGrantPolicy.resolve()` 在保存的 Agent 退出、另一个 Agent 唯一在线时会转用它 | `resolve()` 只接受与保存身份完全一致的 Agent；其余情况返回 `ambiguous / saved_agent_inactive`，界面提示重新绑定 | `test_v131_security.QuickGrantIdentityTests` |
| P1-02 | 宏 `clipboard_get` 只要求 `text_entry`，可读剪贴板并把前 120 字符写进日志 | 新增 `clipboard_read` 作用域；`clipboard_get` / `assert_clipboard` 改查该作用域；日志只记长度与是否匹配，错误信息不再回显内容 | `ClipboardScopeTests`、`ClipboardRedactionTests` |
| P1-03 | 宏 `clipboard_set` / `paste` 直接覆盖系统剪贴板且不恢复 | 新增 `clipboard_write` 作用域；`clipboard_set` 与带文本的 `paste` 显式要求该作用域；内部临时粘贴在剪贴板序列号未被他人改写时恢复原内容 | `ClipboardRestoreTests` |
| P1-04 | 应用白名单只限制输入类动作，屏幕读取可看整个桌面，界面说明不清 | `screen_read` 标签改为「读取整个桌面（含未授权窗口）」；一键授权胶囊文案同步；文档明确两组能力边界 | `ConsentLabelTests` |
| P2-01 | `capture_daemon` 仍声明已不再使用的 `file_write` | 副作用改为 `screen_read` | `DeclaredEffectTests` |
| P0 | 发布流程绕过 `release_gate.py` | 新增 `.github/workflows/release.yml`：tag 触发时先跑测试、协议自检与 Release Gate；Gate 未通过只能发布预发布版 | 见工作流 |

## 二、权限模型变化

新增两个作用域，`SCOPES` 变为 12 项：

```
screen_read  input  input_observe  text_entry  window_close
clipboard_read  clipboard_write  file_read  file_write  file_delete
config_write  process
```

- 一键授权（`quick_grant.COMMON`）仍是 `screen_read / input / text_entry`，**不包含**剪贴板读写。
- 宏动作映射：`clipboard_get`、`assert_clipboard` → `clipboard_read`；`clipboard_set` → `clipboard_write`；`paste` 带 `text` 时额外要求 `clipboard_write`。
- 因此旧的 `text_entry` 授权不再能读剪贴板；需要读剪贴板的用户要在控制中心单独勾选。

## 三、回归结果

```
{"run": 536, "failures": 0, "errors": 0, "skipped": 3}
```

- 覆盖：535 个自动化用例 + 3 个显式跳过（真机/命名管道等需人工环境）
- 新增 18 个用例，全部针对本轮四项修复
- 89 个 MCP 工具、stdio/HTTP 协议自检、wheel/sdist 构建保持通过

## 四、仍然存在的风险

1. **真机验收未完成**：`DESKTOP-BENCHMARKS.md` 的 32 项、100%/200% DPI、干净 Windows 账号安装、撤销/急停物理动作仍未签收，`acceptance.json` 保持 `blocked`。
2. **剪贴板写入仍是全局副作用**：恢复逻辑只在"没有其他程序改写"时生效；若用户在粘贴期间复制了新内容，产品不会覆盖它，但也不会替用户找回旧内容。
3. **屏幕读取的纵深防御**：本轮只把语义写清，没有实现"仅批准窗口画面"的强制模式；该能力计划放到 v1.4 的租约改造里。
4. **快捷授权仍绑定进程级会话**：Agent 重启后需要重新绑定（这是 P1-01 严格化的直接代价），身份级租约（安装 ID + 工作区）尚未实现。

## 五、发布结论

- 代码级整改完成，回归与协议自检通过。
- 按 Release Gate 规则，v1.3.1 在真机验收签收前**只能作为预发布版**提供；不得据此宣称稳定版已通过全部验收。

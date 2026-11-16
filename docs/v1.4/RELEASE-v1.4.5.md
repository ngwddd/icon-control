# Icon Control v1.4.5

Windows 桌面 MCP 的可靠性与发布一致性加强版本，保留 97 个公开工具。

## 交互可靠性

- UIA、OCR 与模板点击共用受约束执行路径，异常不会降级为无约束重发。
- 识别前固定目标窗口、进程身份和几何信息；执行前重新核验落点。
- 鼠标按钮严格接受 left、right、middle，未知值返回 invalid_argument，
  不会静默变成左键，也不会先移动指针后才拒绝非法按钮。
- 模板区域参数必须全部提供或全部省略，禁止扩大半指定搜索区域。
- OCR 自动候选选择与显式 index=0 保持不同语义。
- 模板消失等待超时返回 timeout/inconclusive，不误报 absent。

## 结果与测量

保留旧 success/ok/status 字段，并提供明确的 outcome。副作用执行成功
但没有效果证据时使用 executed_unverified；观察完成使用 observed。
性能报告分别统计成功任务与失败任务耗时，并区分执行器、验证器与总耗时。
本版本不宣称未经同机测量的竞品性能或 Token 成本优势。

## 安装与发布

- 源码、运行包版本、Git Tag 和构建提交必须一致。
- 正式标签禁止携带 rc/dev 等预发布包，门禁失败不发布任何正式 Release。
- 安装器支持 SHA256 校验、独立环境切换及回滚，保留已触发的急停状态。
- icon-control config 输出当前解释器对应的客户端配置。
- Windows 自动化检查覆盖构建、来源、回归、97 工具协议一致性、
  原生窗口探针与 v1.4.4 → 当前版本 → v1.4.4 的安装迁移。

下载本 Release 中的 icon_control-1.4.5-py3-none-any.whl，并对照新生成的
SHA256SUMS.txt 校验。安装方法见 README。升级后重启 MCP 工作进程并
刷新客户端 tools/list，确认 control_status.runtime_contract.server_version
显示 1.4.5。

已知覆盖边界：完整 DPI／多显示器组合、长期 UIA 阻塞与不同应用工作流
仍需按具体环境评估；这些场景不因版本号升级而被视为已全面验证。

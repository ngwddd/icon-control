# v1.3 候选版迁移

工具名称与入参继续保留 89 个接口及旧别名；安全语义作以下收紧：

- ALLOW / DENY 同时用于可见性和实际执行，旧名与别名共享策略。复合工具也须允许其子动作。
- ToolSpec.effects 为能力来源，read_only 仅作兼容提示；文件、配置、窗口操作都可能要求授权。
- 删除无 Token 兼容、OCR 授权和 DSH_MOUSE_GATE=off 放行。缺失或损坏状态一律拒绝。
- 安装时生成本机 Token，渲染客户端模板；源码中的 __BRIDGE_TOKEN__ 不能运行。不要提交生成的客户端或 Token。
- 重启桥后需用户重新点击授权。心跳只保活，不能授权；撤销后旧任务不自动恢复。
- 控制权监听失败、用户接管、急停都停止任务；claim 不能覆盖用户接管。
- 2026-11-03 用户修订：真人鼠标持续移动满 1 秒才接管；停顿超过 350ms 重新计时，
  多次短暂挪动不累加。键盘、点击、滚轮、撤销授权和双 ESC 仍立即生效；助手注入的移动不计入。
- program 结果包含 state、verified、steps、artifacts。普通动作无后置验证返回 executed_unverified，ok=false；
  提供 expect 或最终 assert 才能得到已验证完成。branch 实际执行选中分支；photo 生成可读取证据文件。
- 批处理等待超时不再报成功；安全中断不受 stop_on_error=false / on_fail=continue 覆盖。
- run_script 没有应用后置验证时返回 executed=true、success=false、status=executed_unverified；
  track 的运行中、引擎已结束和经过判据验证的成功分别报告，不把启动或未验证完成当作任务成功。

不为兼容旧脚本重新开放安全绕过。请先在独立环境迁移和验收，正式发布门槛见 PLAN.md。

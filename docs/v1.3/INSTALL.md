# 候选版安装与回滚

需要 Windows 10/11 x64、Python 3.12+。源码包和 wheel 包均由 pyproject.toml 构建，不再覆盖第三方 site-packages。
当前验证环境为 CPython 3.12.14；安装器默认使用 constraints-windows-py312.txt 锁定验证过的依赖。
其他 Python／Windows 组合须重新验收，不能直接沿用本机通过结论。

```powershell
python -m pip install build
python -m build
powershell -File tools/install.ps1 -Wheel dist/icon_control-1.3.0rc1-py3-none-any.whl
```

安装目录默认为 `%LOCALAPPDATA%\IconControl`。每版用独立 venv，验证后切换 current 目录联接；
失败保留现有环境，旧版本以 backup-* 联接保留。回滚：

```powershell
powershell -File tools/install.ps1 -Rollback
```

在 MCP 客户端配置中，将 command 指向 `current\Scripts\python.exe`，
args 设为 `-m computer_mcp.launcher stdio`。自定义 InstallRoot 时，客户端也需设置同值的 ICON_CONTROL_HOME。
协议自检：`python tools/protocol_smoke.py --home <安装目录>`（仅连接与列工具，不输入）。

`init` 只生成凭据、复制默认资产和渲染授权客户端，不授予控制权。
按宿主的插件加载机制装入 `<安装目录>\plugin\client.js`，由用户手动点击授权。
不要提交 state/、生成的客户端或凭据。用户已有宏／模板可备份后复制进新目录；不会自动覆盖旧宿主或真实授权。

HTTP 模式使用官方 SDK Streamable HTTP 的 `/mcp`，仅监听 loopback，要求
`Authorization: Bearer <state/mcp-token.txt>`。原简化 `/sse` 端点停用；旧客户端请改用 stdio 或支持 Streamable HTTP 的客户端。

数据、模板和记录位于统一数据目录。训练采集默认关闭；显式开启且用户授权有效时才记录。
v1.2 的 `_patched/reapply.py` 原地覆盖流程已废弃；完整新接口差异见 MIGRATION.md。
正式 v1.3.0 发布前必须完成 DESKTOP-BENCHMARKS.md 的真机验收与 release_gate.py 校验。

# 候选版安装与回滚

使用 Windows 10/11 x64、标准 CPython 3.12（含 Tk 和 pythonw.exe）。constraints-windows-py312.txt 锁定已验证依赖。其他 Python 或 Windows 组合需要单独验收。

```powershell
python -m pip install build
python -m build
powershell -File tools/install.ps1 -Wheel dist/icon_control-1.3.0rc2-py3-none-any.whl -BridgePort 18766 -RegisterUi
```

默认安装到 %LOCALAPPDATA%\IconControl。每版使用独立 venv；验证导入、89 个工具和原生界面依赖后，切换 current 目录联接。切换及回滚前先撤销旧许可。已有环境、宏和模板保留，安装器不移动已创建的 venv。

```powershell
powershell -File tools/install.ps1 -Rollback
```

回滚后重启助手工作进程及授权桥，再由人重新批准所需会话。回滚只恢复软件环境，不恢复旧授权。

MCP 客户端的 command 使用 current\Scripts\python.exe，args 为 -m computer_mcp.launcher stdio。自定义 InstallRoot 时同时设置 ICON_CONTROL_HOME。升级后需要重启已运行的 MCP 工作进程，目录联接切换不会替换已加载的 Python 模块。

-RegisterUi 注册当前用户的 icon-control://permissions 协议。DSH 按其插件机制加载安装目录 plugin/client.js；胶囊只显示已确认状态，点击打开原生控制中心。界面内由人选择具体 Agent、能力及应用，点击授权后才会生效。关闭控制中心会撤销，断线显示状态未知。

浏览器来源必须精确配置在 state/bridge-config.json 的 origins。DSH 打包宿主使用 dsh-app://app；自定义浏览器宿主应登记其准确来源。不要将 file://、任意 localhost 端口或整个自定义协议当作白名单。

init 只生成本机凭据、默认资产与无凭据的前端，不会授予权限。不要将 state/ 或生成的本机配置加入仓库。首次迁移会废弃旧前端中曾保存的密钥。

HTTP 使用官方 Streamable HTTP /mcp、loopback 监听和 Bearer 认证。每个 MCP 客户端应有独立凭据，可运行：
```text
python -m computer_mcp.launcher client-add --client-name my-agent
```
命令只返回本机凭据文件路径，不输出密钥；它不授予任何桌面权限。不要让不同 Agent 共用同一凭据。旧 /sse 接口不再提供。

协议自检使用安装环境的 Python 运行 tools/protocol_smoke.py --home <安装目录>，只连接 SDK 并列出工具。实际输入验证使用专用夹具、由人授权；完整步骤见 DESKTOP-BENCHMARKS.md。正式发布仍受 release_gate.py 控制。

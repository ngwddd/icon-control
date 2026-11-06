# Icon Control

Windows 桌面控制 MCP：让 AI 通过截图、OCR、UI Automation、鼠标键盘和宏操作桌面，并在执行时检查授权、目标应用与用户接管状态。

**v1.4.0（headless）：连上即用，不再需要人工授权** · **90 个 MCP 工具** · **MIT**

> v1.4.0 起默认走本地执行策略，授权窗口/托盘/热键不再启动；需要旧的人工授权流程时设 `ICON_CONTROL_POLICY=human`。设计与安全边界见 [docs/v1.4/HEADLESS.md](docs/v1.4/HEADLESS.md)。

[下载正式版](https://github.com/ngwddd/icon-control/releases/tag/v1.3.8) · [更新日志](CHANGELOG.md) · [授权说明](docs/v1.3/CONSENT-USAGE.md) · [v1.3.8 发布说明](docs/v1.3/RELEASE-v1.3.8.md)

## v1.3.8 更新

- **运行版本诊断**：查看实际 MCP 进程的版本、工具定义指纹、`click` 参数和构建来源，帮助排查客户端使用旧工具缓存的问题。
- **明确授权对象**：请求绑定实际 Agent 会话与应用进程。没有可信目标时由用户明确选择，不默认选中第一个窗口。
- **独立滚动工具**：新增 `scroll`，支持指定坐标、限制滚轮幅度，并在注入前复核目标。原有 89 个工具继续保留。
- **页面条件点击**：宏支持 `guarded_click`，检查页面条件后只点击一次，再检查结果；绑定顶层 HWND，拒绝同进程其他窗口遮挡后的错误落点。
- **文本完整性信息**：输入结果提供字符数、直引号计数和哈希，并提示核对草稿；保留 `executed_unverified`，不把事件提交当成应用内容正确。
- **统一工具清单**：安装与 stdio/HTTP 协议检查共用包内清单，不再依赖散落的固定工具数。
- **保留用户窗口**：操作规范明确保留用户原本打开、或要求保持打开的应用。

## 主要能力

| 类别 | 入口示例 | 用途 |
|---|---|---|
| 屏幕观察 | `screenshot`、`screen_state`、`wait_for_change` | 截图、判断画面变化 |
| 鼠标键盘 | `click`、`mouse_move`、`scroll`、`type`、`key_press` | 定点操作、滚动、文字与快捷键 |
| 原生控件 | `ui_tree`、`ui_find`、`ui_click`、`ui_invoke`、`ui_set_text` | 读取和操作 UIA 可访问控件 |
| OCR 与视觉 | `ocr_read`、`find_text`、`click_text`、`match_template` | 自绘界面文字和模板定位 |
| 组合执行 | `batch`、`run_script`、`macro_run`、`track` | 批处理、脚本和可复用流程 |
| 验证 | `verify_flow`、`sample_stable`、`diff_baseline` | 文字、模板、文件及画面状态判断 |
| 授权与控制 | `control_status`、`control_claim` | 查看实际调用者、控制权和拒绝原因 |
| 记忆与数据 | `layout_mem`、`anchor_mem`、`dataset_status` | 保存定位资产和管理采集数据 |

完整工具名称见 [工具清单](_patched/tool_manifest.json)，参数以当前连接的 MCP `tools/list` 为准。`guarded_click` 是宏步骤，不是额外的 MCP 工具。

## 安装

面向 Windows 10/11 x64，推荐使用标准 CPython 3.12，包含 Tk 与 `pythonw.exe`。项目声明 Python 3.12+；其他解释器和系统组合需自行确认兼容性。

### 安装正式发布包

先取得与发布版本对应的安装脚本及依赖约束，再下载 wheel：

```powershell
git clone --branch v1.3.8 --depth 1 https://github.com/ngwddd/icon-control.git
cd icon-control

New-Item -ItemType Directory -Path dist -Force | Out-Null
Invoke-WebRequest -Uri "https://github.com/ngwddd/icon-control/releases/download/v1.3.8/icon_control-1.3.8-py3-none-any.whl" -OutFile ".\dist\icon_control-1.3.8-py3-none-any.whl"

# 需要已安装 Python 3.12 及 Windows Python Launcher。
$python312 = py -3.12 -c "import sys; print(sys.executable)"
powershell -File tools\install.ps1 -Python $python312 -Wheel .\dist\icon_control-1.3.8-py3-none-any.whl -RegisterUi
```

默认安装目录为 `%LOCALAPPDATA%\IconControl`。安装器使用独立环境，通过 `current` 目录联接切换版本；软件升级不会沿用旧授权。

### 从源码打包

在需要构建的源码版本中执行：

```powershell
py -3.12 -m pip install build
py -3.12 -m build
```

然后将生成的 wheel 传给 `tools\install.ps1 -Wheel`。构建包包含源码来源信息；未知来源会显示为不可用，不会假定它就是 GitHub 最新提交。

### 回滚

```powershell
powershell -File tools\install.ps1 -Rollback
```

回滚后重启 MCP、授权桥和原生授权宿主，再由用户重新批准会话。回滚恢复软件环境，不恢复旧授权。

## 连接 MCP 客户端

### stdio

在客户端的 MCP 配置中使用安装环境的 Python。下面的用户名占位符需要替换为真实路径；不要假定客户端会展开 `%LOCALAPPDATA%`：

```json
{
  "mcpServers": {
    "icon-control": {
      "command": "C:\\Users\\<Windows用户名>\\AppData\\Local\\IconControl\\current\\Scripts\\python.exe",
      "args": ["-m", "computer_mcp.launcher", "stdio"]
    }
  }
}
```

自定义安装目录时，修改 `command` 并设置 `ICON_CONTROL_HOME` 指向实际数据目录。

### HTTP

也支持带 Bearer 认证的官方 Streamable HTTP，默认仅监听本机，端点为 `/mcp`：

```powershell
& "$env:LOCALAPPDATA\IconControl\current\Scripts\python.exe" -m computer_mcp.launcher http --host 127.0.0.1 --port 8000
```

不同客户端应使用独立凭据，通过 `client-add --client-name <名称>` 创建。该命令返回本机凭据文件路径，不授予桌面权限。旧 `/sse` 接口不再提供。

## 授权与用户接管

热键 **Ctrl+Alt+Shift+F9** 或托盘图标打开原生授权窗口。DSH 胶囊保留为原生授权入口，不能替代用户在原生界面的批准。

- 常用范围为 `screen_read`、`input`、`text_entry`；剪贴板、文件操作、窗口关闭与进程启动等需要相应的独立能力。
- 许可绑定实际 Agent 会话和批准的应用进程身份；同一工作区的新会话也不会自动继承。
- `screen_read` 涉及屏幕读取；输入操作还会核对目标应用。窗口或进程身份变化时需要重新确认。
- **物理鼠标持续移动满 1 秒**触发接管；物理点击、滚轮或键盘输入立即触发接管。
- **双 ESC** 急停；撤销、接管和急停会阻断剩余动作，并清理本进程持有的输入。
- 通信失败显示状态未知，不能把本地按钮变绿当作后端已授权。

具体行为见 [授权使用说明](docs/v1.3/CONSENT-USAGE.md)。

## 常见调用

以下 JSON 是 MCP 工具的参数，需分别交给对应工具。

### 定点点击：`click`

```json
{"x": 320, "y": 450, "button": "left"}
```

`x`、`y` 必须同时提供，表示物理屏幕坐标。不提供时点击当前光标位置。定点点击会复核落点进程；页面是否切换仍需后置观察。

### 指定区域滚动：`scroll`

```json
{"x": 900, "y": 600, "dy": -3, "dx": 0}
```

`dy > 0` 向上，`dy < 0` 向下；`dx > 0` 向右。每轴为 `[-100, 100]` 内的整数滚轮步数，不能同时为零。省略成对的 `x/y` 时在当前指针处滚动。

### 文字输入：`type`

```json
{"text": "中文与直引号 \"example\"，以及表情 😀"}
```

结果中的 `injected_characters`、`text_integrity` 说明提交的事件及工具收到的文本；它们不能证明目标应用已逐字接收。`executed_unverified` 表示操作已执行但应用结果未核实，发送前应核对未发送草稿及标点。

### 页面条件宏：`macro_run`

```json
{
  "name": "wechat_moments_guarded",
  "params": {
    "target_hwnd": 123456,
    "main_query": "当前主界面可确认的文字",
    "moments_content_query": "当前朋友圈内容区可确认的文字"
  }
}
```

示例中的 HWND 和页面文字必须替换为当前观察到的值。宏要求前后均有正向文字或模板特征；历史坐标仅作候选。缺参、空值、遮挡或页面条件失败时停止，不自动重复点击。详见 [微信操作参考](skill/desktop-operator/references/wechat.md)。

## 升级后仍看到旧工具？

重启实际 MCP 工作进程并刷新客户端 `tools/list`。目录联接切换不会替换进程已经加载的 Python 模块。

读取 **当前 MCP 连接**返回的 `control_status.runtime_contract`：

| 字段 | 含义 |
|---|---|
| `server_version` | 实际服务端版本 |
| `tools_sha256` | 当前可见工具定义的指纹 |
| `tool_count` | 当前可见工具数，可能受允许/禁止名单影响 |
| `click_input_schema` | 当前服务端的坐标点击参数 |
| `source_commit` / `source_dirty` | 包内构建来源；没有元数据时为 `null` |

另一个终端运行的 `icon-control check` 只说明那个解释器的安装情况，不能证明 DSH 使用的是同一进程。服务端可以提供诊断，但不能强制所有客户端丢弃旧缓存。

## 开发与验证资料

- [更新日志](CHANGELOG.md)：版本修改记录。
- [桌面操作技能](skill/desktop-operator/SKILL.md)：观察、执行、页面确认与收尾约定。
- [32 项桌面验收任务](docs/v1.3/DESKTOP-BENCHMARKS.md)：真实 Windows 场景的验收清单。
- [桌面反馈交接](docs/v1.3/DESKTOP-FEEDBACK-HANDOFF.md)：v1.3.8 修改范围及验证归属。
- [第三方声明](THIRD_PARTY_NOTICES.md) 与 [许可证](LICENSE)。

自动化回归、输入事件提交和真实桌面任务验收是不同层次。具体结论应对应源码提交及其证据，不以历史性能数字或工具返回的 `success` 替代应用状态核对。

## 仓库结构

```text
_patched/                 computer_mcp 包源码、执行权限和工具实现
  zones/                  七个工具分区及分发
  tool_manifest.json      安装与协议代码共用的工具名称清单
  runtime_contract.py     运行版本与工具定义诊断
plugin/                   DSH 授权入口
macros/                   可复用宏与页面条件点击示例
recipes/                  应用经验、历史坐标与页面约定
skill/desktop-operator/   桌面操作技能与应用参考
programs/                 指令流示例
tools/                    安装、回滚、构建及验证辅助脚本
tests/                    回归用例
docs/                     发布说明、设计和验收资料
```

Icon Control 使用 `computer-mcp` 的 MIT 源码，并以完整 Python 包交付；不再通过覆盖宿主 `site-packages` 安装。依赖及归属见第三方声明。

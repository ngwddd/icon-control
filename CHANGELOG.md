# Changelog

所有改动记录在此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.3.0] - 2026-10-26

把「有没有授权」从**看屏幕像素**改成**走程序层通道**。

### Added — 授权状态通道（本地桥）
- `computer_mcp/permission_bridge.py`：只听 `127.0.0.1:18765` 的小服务
  - GUI 插件每 5 秒把真实授权状态 POST 过来，Host 直接读状态文件
  - **无 token**：改校验 `Origin`（只接受 `dsh-app://` / `file://` / `127.0.0.1` / `localhost`）
    —— token 写死在源码里，发布即公开；Origin 由浏览器设置，普通网页改不了
  - 只写一个 JSON 状态文件，源码里没有任何执行命令的调用
- 客户端插件：挂载即上报 + 5 秒心跳 + 点击立即上报（`no-cors` 简单请求，无预检）
- 闸门（`permission.py`）**桥优先**：新鲜桥状态 0.1 ms 直接用；桥没起来会**自愈拉起**；
  OCR 仅作后备，且有效期从 45 s 缩到 **15 s**（桥挂了不会一直"以为已授权"）

### Fixed — 一个方向最危险的假阳性
- 旧实现里扫描区域第三条是 `(0,1000,2560,440)`（整个窗口下 1/3），
  OCR 会读到**聊天正文里**的「鼠标·已授权」字样，再撞上一处绿色像素 → 判成已授权
- 修法：扫描区收窄到输入框工具栏（高度 ≤ 200）；正面判定必须
  「检测到绿色胶囊」**且**「文字含 鼠标 + 已授权」同时成立；否则 unknown → 按未授权处理
- `tools/mouse_permission.py` 不再自己 OCR，改为调 `permission.status()`，与闸门同源

### Changed
- 测试 **75 → 86** 项（新增 11 项守桥：模块常量、写入/读取、无秘密、Origin 校验、
  TTL 短于 OCR、新鲜状态不触发 OCR、过期状态不信任、插件三处上报、CLI 同源、扫描区高度）
- 工具数仍 **58**（桥是支撑进程，不是 MCP 工具）

## [0.2.0] - 2026-10-25

把 v0.1 的"能力面"补成"可治理面"：**授权下沉到执行点**、**验证变成分级留证**。

### Added — 权限硬闸门（Host 侧）
- `computer_mcp/permission.py`：输入类工具的**统一闸门**
  - 未授权时在 `call_tool` 路由之前直接返回结构化拒绝，**不产生任何鼠标/键盘动作**
  - **fail closed**：读不到授权状态时按未授权处理
  - 45 s 缓存（命中约 0 ms，不给每次点击加 IO）
  - `DSH_MOUSE_GATE=off` 仅供自动化测试关闭；`DSH_MOUSE_STATE` 可指向别的状态文件
  - 状态来源：GUI 上那个「鼠标·已授权 / 未授权」胶囊（OCR 读取），只读不写
- 覆盖 19 个输入类工具（`click` / `type` / `key_press` / `batch` / `macro_run` / `ui_click` /
  `click_template` / `hover_probe` …）；只读工具（截图、OCR、模板匹配、状态查询）不受影响

### Added — 分级验证 `verify_flow`
- 新工具 `verify_flow`：**按级验证、遇错即停、每级留证据**
- 五种断言：`text`（区域 OCR + 容错）/ `template`（模板命中）/ `baseline`（基线偏离）/
  `stable`（连采稳定）/ `file`（存在 + 内容包含）
- 报告含每级耗时、每条断言的具体证据（OCR 片段 / 置信度 / diff / 文件大小）
- `stop_on_fail=False` 时跑完全部，`failed_stage` 记**第一处**失败，`failed_stages` 记全部
- 可写 JSON 报告留档（`report_path`）
- 只做验证、不做动作 —— "动作做了没生效"与"根本没做"能在报告里分开

### Changed
- 工具总数 **57 → 58**
- 测试 **64 → 75** 项（新增 11 项守闸门与分级验证）
- `verify_flow` 的失败语义修正：多级失败时 `failed_stage` 不再被最后一级覆盖

### Fixed
- 清掉 6 处未使用的 import（两个演示脚本 / 三个测试文件）
- 探测性 import 显式标注用途，避免静态检查误报

### Docs
- 文档与示例统一脱敏：应用名以「软件性质（***）」表示，不含个人信息

## [0.1.0] - 2026-10-25

首个公开版本。能力面打通：**能看、能点、能验、能停、能授权**。

### Added — 采集与感知
- 采集层重写：默认 0.5 倍缩放 + JPEG q75，单次截图 **128 ms → 61 ms**、**962 KB → 121 KB**
- `screen_state`（不带图，43 ms，回报 changed / diff / hash）
- `wait_for_change`（事件驱动等待，替代模型轮询）
- `capture_config`（运行时改 scale / quality / format / diff_threshold / mask_bottom）

### Added — 执行层
- `batch`：一串动作合成一次调用（20 步协议层 2 ms，往返 20 → 1）
- UI Automation 五件套：`ui_tree` / `ui_find` / `ui_click` / `ui_invoke` / `ui_set_text`
- 宏引擎 `macro_run`：相对坐标、`anchor:"br"`、`expect` 校验、自动 restore、越界拒点、
  `retry` / `repeat` / `ensure_chat` / `assert_text` / `assert_file` / `clipboard_*` / `paste`
- OCR 三件套：`ocr_read` / `find_text` / `click_text`，支持 `upscale` + `boost` 认小字与灰字

### Added — 视觉状态判据（本版核心）
- `capture_template` / `match_template` / `wait_template` / `click_template`：灰度模板自学 + 匹配
- `set_baseline` / `diff_baseline` / `wait_baseline_change`：区域偏离基线的程度
- `sample_stable`：连采多次一致才算数，防动画中途误判
- `hover_probe`：悬停 → 等待 → 比较 → 移开，识别"悬停才出现"的控件
- `vision_list`：模板/基线清单 + 运行统计（calls / failures / retries / failure_rate）
- 工具总数 **31 → 57**

### Added — 应用生命周期
- `appkit.launch`（走 Explorer shell，规避 Electron 静默秒退）
- `appkit.wait_window` / `appkit.exit_app`（关窗 ≠ 退出，托盘进程显式结束）
- `appkit.activate`（AttachThreadInput 强攻前台，SetForegroundWindow 常被拒）

### Added — 安全
- 急停：`panic.PanicSwitch`（1.5 s 内连按两次 ESC 立即硬停，粘住不复位）
- `panic_watch.py`：进程外看守，触发即杀掉所有自动化进程
- 鼠标接管授权闸门：GUI 插件 `@local/dsh-mouse-permission`（灰色 = 无权限 / 绿色 = 可接管）
  + 只读检查器 `mouse_permission.py`（退出码 0 / 2 / 3）

### Added — 工程保障
- 64 项不变量测试，系统 Python 与 venv Python 双跑全绿
- `doctor.py` 六组体检（身份 / 显示 / 输入 / 驱动 / 补丁 / 记忆库）
- `diag_input.py`：用"系统文本编辑器打字 + 剪贴板回读"当唯一可信判据
- `clean.py`：白名单清理临时文件，不碰宏、补丁、用户目录
- `recipes/`：每个已验证应用一份配方（即时通讯软件（***） / 某即时通讯客户端（***） / 游戏平台（***） / 安全软件（***） / 系统文本编辑器 / 视频客户端（***） / 音乐客户端（***））
- `_patched/reapply.py`：重装依赖后一键重放所有补丁

### Fixed
- `_patched/appkit.py` 与安装副本漂移（旧版 14,653 B 缺评分匹配、启动前校验、`activate`）→ 已同步并留备份
- 补丁脚本全部改为"先 assert 旧片段存在再替换"，避免静默失效
- 截图变化检测默认遮掉底部 60 px，否则任务栏时钟会让静止画面被判成一直在变

### Known limitations
- 仅在 Windows 11 验证；DPI 150% 下必须 `SetProcessDpiAwareness(2)`
- 授权闸门的状态存在浏览器本地（客户端无法直连 Host），agent 通过读界面文字判定
- 第三层（逆向）默认关闭，需要逐次授权

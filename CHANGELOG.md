# Changelog

所有改动记录在此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

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

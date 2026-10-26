# 本机工具链（别重写，直接用）

## 一、清理垃圾（每次任务收尾）

```powershell
$PY = %USERPROFILE%\.dsh\tools\desktop-mcp\venv\Scripts\python.exe
& $PY %USERPROFILE%\.dsh\tools\desktop-mcp\clean.py                 # 预览
& $PY %USERPROFILE%\.dsh\tools\desktop-mcp\clean.py --apply --keep 1 # 真删
& $PY ...\clean.py --scope temp --apply                             # 只清 %TEMP%
```

清：`%TEMP%\t_*.py / patch_*.py / run*.json`、`_draw\*.png`、工具目录 `_bench*.py/_verify*.py/*.bak`（24 小时内）。
**不动**：`macros/`、`recipes/`、`templates/`、`vision/`、`_patched/`、`venv/`、用户目录。

保留策略（`retention.py`，自动触发）：
```
_draw          80 文件 / 80 MB / 3 天
recordings     10 目录 / 300 MB / 7 天
vision         40 文件 / 30 天
%TEMP% 自己的  vh-* / canity_* / t_*.py  超 6 小时
```

## 二、自检脚本（怀疑环境时跑，别自己写）

```powershell
& $PY ...\doctor.py            # 6 组体检：令牌 / DPI / 输入链路 / 可疑驱动 / 补丁 / 记忆库
& $PY ...\diag_input.py        # 输入链路三层（光标 / 键盘 / 回读）
  退出码 0=通   2=拦   3=不可信
& $PY ...\mouse_permission.py  # 鼠标授权闸门  0=已授权 2=未授权 3=读不到
& $PY ...\tools\track_oneshot.py   # 列车三轮回转 + 看门狗（11 项）
```

⚠️ `diag_input.py` 的已知假阴性：记事本没点进编辑区 / 有模态框时，会误报"输入被拦"。
它现在会判 **UNKNOWN** 而不是说谎 —— 但看到 UNKNOWN 时按 `references/failures.md` 的 C 组排。

## 三、Python 解释器（别混）

| 解释器 | 版本 | 用途 |
|---|---|---|
| `%USERPROFILE%\.dsh\tools\desktop-mcp\venv\Scripts\python.exe` | **3.12** | 唯一能 import `computer_mcp` 的 |
| `C:\Program Files\Python314\python.exe` | 3.14 | 系统；跑 `pdf-read.py` / `stt.py` |
| `.dsh\dsh-runtimes\...\python.exe` | DSH 自带 | 有 python-docx/pptx/openpyxl/Pillow/lxml/XlsxWriter，做 Office 用它 |

**ABI 不同**：用系统 Python 跑 desktop-mcp 的测试会全 skip（假绿），必须用 venv。

## 四、验证（交付前）

```
mcp__project-verify__verify_start(path=...)   → 三态结论 PASS/FAIL/UNKNOWN
```
- 全跳过的测试 → **UNKNOWN**，不是 PASS
- 测试解释器可选：`DSH_TEST_PYTHON` → 项目 `.verify-python` → 项目 venv → `sys.executable`
- 证据写进 `.verify-artifacts/<时间戳>/`

## 五、媒体 / 文档工具（本机已装）

```
ffmpeg / ffprobe   %APPDATA%\npm\ffmpeg\...\bin\           9.0.2
LibreOffice        C:\Program Files\LibreOffice\program\soffice.exe   26.8（转 PDF / 渲染）
Marp               marp.cmd（能自己渲染 PNG）
没有               PowerPoint / Word / Excel / WPS / pandoc / xelatex / ImageMagick
```

## 六、DSH 侧约定

```
插件改动：host 半用 plugin_manager set_bundle 关再开；client 半必须刷新页面
插件目录：~/.dsh/profiles/desktop/node_modules/ 与 ~/.dsh/profiles/web/...
热补丁：  ~/.dsh/tools/desktop-mcp/_patched/ ←→ venv 里的 computer_mcp（必须字节一致）
记忆库：  ~/.dsh/storages/mcp-memory.jsonl（2026-10-27 用户要求清空，备份同级 .backup-*）
```

## 七、改文件的两条硬规则

```
① UTF-8 中文文件：不要用 PowerShell Get-Content/Set-Content 管道（PS 5.1 按 ANSI 读会写坏）
   → 用 edit/write 工具，或 Python 显式 encoding="utf-8"
② 字符串替换打补丁：必须 assert old in s；语法校验用 compile(src, path, "exec")
   （ast.parse 不检查 from __future__ 的位置）
```

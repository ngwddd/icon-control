# v1.3.0rc1 验证与剩余风险

2026-11-02；基线 v1.2.0 / 98b38b49335587595ed998ed003a79e9f8fd9d4b。
本报告是候选版工程验证，不是正式版验收。共享聊天页无法读取，实施依据为用户粘贴的六阶段任务书。

## 已取得的证据

| 范围 | 实际结果 | 可复核材料 |
|---|---|---|
| 完整自动化回归 | 375 项运行，367 通过、8 跳过、0 失败、0 错误 | test-results.json；tools/verify.py |
| 新稳定性回归 | 77 项安全／任务／快照／传输／原生调用与发布闸门用例，全部通过 | tests/test_stability*.py |
| 标准构建 | wheel 与 sdist 成功；完整包不依赖宿主补丁目录 | pyproject.toml；dist/ 构建产物 |
| 独立安装 | Windows x64 / CPython 3.12.14 新建 venv，pip 自动安装声明依赖；pip check 通过 | tools/install.ps1；constraints-windows-py312.txt |
| 官方 MCP SDK 互通 | stdio、Streamable HTTP 均初始化成功、列出 89 工具；无凭据 HTTP 返回 401 | protocol-smoke.json；tools/protocol_smoke.py |
| 版本回滚 | 升级确实切换目录联接；回滚恢复完全相同的原目标；恢复后导入 89 工具成功 | rollback-evidence.json |
| 正式发布闸门 | 缺 P0 复审与 32 项真机证据时返回退出码 2 | tools/release_gate.py；acceptance.json |

测试只在独立工作目录、临时签名授权夹具和假执行器中授予测试权限；没有授予真实宿主鼠标权限，
没有修改原已安装宿主或原开发目录。窗口截图与部分屏幕采集测试可读取本机桌面，
SDK 互通只列工具，不注入鼠标或键盘。

77 项新回归包括：首请求 Token 缺失、错误 Token、伪域 Origin、伪造／过期状态、心跳不授予权限、
撤销与跨窗口乱序／同毫秒冲突、名单实际执行、监听失败、claim 接管竞争、逐事件取消与持键释放、
急停持久化、branch/photo 真实结果、失败计数、后置条件、快照 TTL／窗口／进程／DPI／内容失效、
HTTP 认证与官方传输、中文及 UTF-16 输入、只读截图和 OCR 不切前台、微脚本未知指令和超时。

## 跳过项没有计为通过

- 3 项旧 E2E：未启用 DSH_E2E，涉及真实窗口和输入。
- 1 项专项 bot 扫描：本仓库没有对应专项自动运行脚本。
- 1 项旧宏文件检查：旧测试寻找 wechat_send，仓库现有文件名不同。
- 1 项旧 venv 副本同步检查：本轮使用独立完整包，仓库没有旧 venv 安装布局。
- 1 项旧根目录 CLI 检查：入口已位于 tools/，旧测试路径不存在。
- 1 项应用案例回归：未启用 DSH_RUN_CASES，不能视为真实应用通过。

完整 ID 和原始跳过理由保留于 test-results.json。没有删除这些测试或把 skip 改计为 pass。

## 尚未满足的发布条件

- DESKTOP-BENCHMARKS.md 的 B01–B32 均未执行；没有真实误点率、成功率、P50/P95 或急停时延数据。
- 新建 venv 不等于干净 Windows 账号；B31 仍待完成。
- 双 ESC 与物理鼠标／键盘接管需测试员实际操作；自动调用监听回调的单测不能替代。
- 独立 P0 安全复审尚未完成；本轮第二遍代码检查不冒充独立复审。
- 全仓“没有已知假成功路径”的发布审计尚未签收，acceptance.json 保持未完成。

## 剩余风险与边界

- Token／签名的信任边界是当前 Windows 账户，不能防御同账户进程读 Token、改源码或注入本进程。
- 物理事件判别依赖 Windows injected 标志与 pynput；远程桌面、辅助输入设备、游戏全屏及不同权限级别需真机验证。
- 完整窗口像素摘要会使动画或时钟导致引用失效；当前偏向拒绝旧引用，可能需要频繁重新观察。
- 旧坐标／名称接口为兼容仍保留；只有显式使用 ref 的点击拥有快照失效检查，仍须验证应用实际结果。
- OCR、PrintWindow 和模板对 GPU／自绘窗口的支持因应用而异；候选命中不等于动作已验证。
- 改写现有工具与直接 Python 入口，并未提供操作系统沙箱；任意第三方 Python 代码不属于受控执行接口。
- HTTP 仅为本机使用设计；不支持公网监听或旧自制 SSE。当前不部署到用户生产宿主。

## 复现与回滚

用 Python 3.12 安装候选 wheel 后运行：

```powershell
python tools/verify.py --pattern "test_*.py"
python tools/protocol_smoke.py --home <独立安装目录>
python tools/release_gate.py docs/v1.3/acceptance.json
```

最后一条当前应失败。按阶段 git revert 可撤回源码；已安装候选版按 INSTALL.md 回滚。
基线仅保留作对照，不能因回滚而重新开放无 Token、OCR 或环境变量绕过。

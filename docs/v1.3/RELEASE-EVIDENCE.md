# ICON Control 1.3.9 预发布证据汇总

> 分支：`v1.3.9-alpha`（`main` 未动，仍为 `e3a8142`；无 `1.3.9` tag）
> 最新提交：`dbeb1a5`
> 版本演进：`1.3.9a1 → b1 → b2 → b3 → b4 → b5 → b6 → b7 → b8 → b9 → b10`
> 记录时间：2026-11-06

## 一、交付内容

| 阶段 | 版本 | 解决什么 |
|---|---|---|
| alpha | `1.3.9a1` | 静默启动（不再自动弹授权窗）、桥不可用不弹模态、托盘错误态、错误码分类、`ctrl+f` 组合键 |
| beta | `1.3.9b1` | 30 天信任记录（签名 + 主体绑定）、通配目标、`trust` CLI 与原生一键授权 |
| beta.2 | `1.3.9b2` | 撤销代际（持久化、单调）、执行戳取消、撤销时释放按住输入、撤销同时清信任、窗口内「信任 30 天」按钮 |
| beta.3 | `1.3.9b3` | `frame_id` 坐标契约（截图带帧身份、`click` 吃图像坐标、服务端换算、陈旧帧拒绝） |
| beta.4 | `1.3.9b4` | 窗口移动/DPI 变化/关闭即令帧失效；`double_click`/`drag` 支持 `frame_id`；`screen_state` 返回帧号；坐标契约文档 |
| beta.5 | `1.3.9b5` | 真机验收①：先撤销后授权信任不生效（`status()` 提前返回 `permission_revoked`） |
| beta.6 | `1.3.9b6` | 真机验收②：授权宿主退出会清掉 30 天信任 |
| beta.7 | `1.3.9b7` | 真机验收③：信任主体含 cwd，服务进程与 CLI 算不出同一主体 |
| beta.8 | `1.3.9b8` | 真机验收④：宿主退出推进撤销代际，等价于撤销信任 |
| beta.9 | `1.3.9b9` | 真机验收⑤：桥启动/退出推进撤销代际 |
| beta.10 | `1.3.9b10` | 撤销语义定稿：startup/shutdown 属租约结束，不否定信任 |

## 二、提交与 CI

| 提交 | 内容 | CI |
|---|---|---|
| `c7136a7` | 版本号 1.3.9a1 | run 42084878603 ✅ |
| `b696cd7` | 30 天信任 | run 42086069116 ✅ |
| `dfcefd1` | 撤销代际 | run 42086821315 ❌（held-input 监控器仍用旧戳） |
| `9acb028` | 撤销释放输入 + 信任按钮 | run 42086994130 ❌（无条件 release 启动监控器） |
| `7099872` | 只在按住时释放 | run 42087504888 ❌（监控器戳形状未同步） |
| `7137325` | 监控器改用三元组 | run 42088069551 ✅ |
| `3b3f62b` | frame_id 契约 | run 42089142547 ✅ |
| `c985a99` | 窗口失效 + 拖拽/双击 | run 42090035121 ✅ |
| `15cb4bb` | 坐标契约文档 + 真机脚本 | run 42090760409 ✅ |
| `8f1029c` | 证据汇总初版 | run 42091225659 ✅ |
| `ea4966d` | b5 撤销后信任不生效 | 待 CI |
| `b797221` | b6 退出清信任 | 待 CI |
| `01be2cd` | b7 信任主体 cwd | 待 CI |
| `143c0c4` | b8 退出推进代际 | 待 CI |
| `c49165e` | b9 桥启停推进代际 | 待 CI |
| `dbeb1a5` | b10 租约结束不否定信任 | 待 CI |

三次红灯都是本分支自己引入的回归，均在当轮修复并复跑通过；没有遗留失败。

## 三、测试

| 节点 | 全量用例 | 结果 |
|---|---|---|
| alpha | 660 | 0 失败 / 0 错误 / 3 跳过 |
| beta | 680 | 同上 |
| beta.2 | 691 → 713（新增帧测试） | 同上 |
| beta.4 | 713 | 0 失败 / 0 错误 / 3 跳过 |
| beta.10（当前，已装到本机） | **718** | **0 失败 / 0 错误 / 3 跳过** |

新增测试文件：

```
tests/test_v139_consent_intent.py   18 项  启动意图 / 静默 / 白名单 / 状态文件
tests/test_v139_error_codes.py       8 项  code 映射 / 健康块
tests/test_v139_gate_codes.py        7 项  异常分类 / 参数不外泄
tests/test_v139_key_chords.py       15 项  组合键 / batch 拒绝
tests/test_v139_trust.py            20 项  信任签名/过期/撤销/主体变化/CLI
tests/test_v139_revocation.py       12 项  代际持久化/戳取消/释放/信任压制
tests/test_v139_frames.py           22 项  换算/负坐标/未知陈旧/窗口失效/拖拽双击
```

## 四、真机验收（有输出记录）

### 1. 静默启动（`tests/manual/verify_v139_silent_start.ps1`）

```
后台启动 → IconControl 窗口存在但 visible=False
         前台 hwnd 前后一致；consent-host.json: intent=background,
         last_sync_ok=false, granted=null；无任何对话框
二次启动 → 前台与窗口集合均不变
```

### 2. 坐标契约（`tests/manual/verify_v139_frames.py`）

```
PASS map_window_centre
  source_rect=[0,0,2560,1440]  image_size=[1280,720]
  image_point=[195.5,154.0] → mapped=[391,308]  expected=[391,308]
  delta_px=[0,0]  inside_window=true
PASS moved_window_rejects_frame
  moved_by=[80,60]  rejected=true
  message="stale frame_id; the target window moved or resized"
```

### 3. 本机安装 + 30 天信任 + 微信发消息（2026-11-06 03:2x）

```
安装       1.3.8 → 1.3.9b10（pip --force-reinstall 到 %LOCALAPPDATA%\IconControl\current）
运行版本   control_status.runtime_contract.server_version = 1.3.9b10，工具 90 个
信任       原生窗点「信任 30 天」→ desktop-trust.json subject=57475a13… days=30
重启验证   杀链重启后 origin=startup、代际不变，list_windows 直接成功（不再按热键）
微信       启动 → 进入微信 → 文件传输助手独立窗 → 点输入框 → type 666 → Enter
结果       绿色气泡「666」03:27 发出（截图确认）
```

验收过程中暴露并修复了 6 个真 bug（b5–b10，见交付表与提交表）。

## 五、明确未验证的项

| 项 | 状态 |
|---|---|
| 撤销即时停 / 撤销后不能自恢复的**真人点击**验收 | 只做了程序化验证（代际、戳、`permission_revoked` 返回码）；没有在真机上按住输入时点撤销 |
| 多显示器负坐标 | 仅单元测试（`-1920` 起点），未在真实双屏上跑 |
| 30 天信任的原生弹窗（`ask_trust`） | **已真机点过**（4 次；b10 后重启不再需要重新点） |
| 迁移后的微信实测点击 | 未做（alpha 之前那台机器上的微信会话未复跑） |
| 1.3.8 → 1.3.9b10 覆盖安装 | **已做**，本机现在运行 1.3.9b10；回滚需重装 1.3.8 |

## 六、安装与回滚

```powershell
# 安装预发布（覆盖当前安装）
python -m pip install --force-reinstall icon_control-1.3.9b10-py3-none-any.whl

# 回滚
python -m pip install --force-reinstall icon_control-1.3.8-py3-none-any.whl
```

升级会改变工具指纹 → 已授予的 30 天信任自动失效并要求重新授权（这是设计，不是 bug）。

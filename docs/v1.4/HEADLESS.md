# Icon Control v1.4.0 · Headless Local MCP

> 从「需要人工授权的桌面控制插件」变成「连上即用的本地 MCP 服务」。
> 人工授权流程保留为可选模式（`ICON_CONTROL_POLICY=human`），默认不再启用。

---

## 一、为什么要改

v1.3.x 的架构是：**每次工具调用都要证明"刚刚有人点过授权"**。

```
MCP 调用 → check_tool() → permission.status()
                              ├─ 桥进程签名状态（15 秒新鲜期）
                              ├─ 会话必须完全相等
                              ├─ live_valid() 再向桥问一次
                              └─ 失败 → 弹授权窗口 → 人点 → 再重试
```

这条链路带来三个结构性问题：

1. **一次授权只对一个会话有效** —— DSH 同时开着多个 MCP 通道，授权经常绑到"不是干活的"那个；
2. **桥/托盘/热键成了单点** —— 桥挂掉、宿主没起来、心跳过期，都会表现为"明明授权了却说没授权"；
3. **升级即失效** —— 30 天信任记录含工具指纹，每次升级都要重新授权。

v1.4.0 把这套"人工许可"换成**本地执行策略**：能不能动，不再取决于"刚刚有没有人点过"，而取决于**调用是否来自本机已连接的 MCP 会话** + **执行保护是否允许**。

---

## 二、架构对比

**v1.3.9**

```
DSH ──stdio──▶ MCP Server ──check_tool──▶ permission.status()
                                             │
                                    ┌────────┴────────┐
                                    ▼                 ▼
                              permission_bridge   30 天 trust
                              （签名状态+租约）    （含工具指纹）
                                    │
                                    ▼
                              consent 宿主（托盘/热键/窗口）
```

**v1.4.0**

```
DSH ──stdio/HTTP──▶ MCP Server ──check_tool──▶ policy.state()
                                                  │
                                    ┌─────────────┴──────────────┐
                                    ▼                            ▼
                          LocalExecutionPolicy            执行保护（全部保留）
                          · 连接即授权                    · 人机接管（10s）
                          · 12 scope 全开                 · 急停（ESC/看门狗）
                          · 应用/启动/读取通配            · 目标窗口身份校验
                                                          · 参数校验 / 撤销代际
```

---

## 三、代码改动

| 文件 | 改动 |
|---|---|
| `_patched/policy.py` | **新增**。`mode()` / `authorization()` / `state()` / `runtime_state()` / `resume()`；`state/local-policy.json` 记录授权时刻 |
| `_patched/permission.py` | `status()` 在本地模式下直接返回 `policy.state()`；`_request_consent()` 本地模式直接返回 `None`（不弹窗） |
| `_patched/capabilities.py` | `require_launch()` 支持 `launches=['*']`（此前信任模式下**永远无法启动程序**） |
| `_patched/workspace.py` | `readable_path()` 支持 `read_files=['*']`；1 MiB 上限与路径穿越检查不变 |
| `_patched/launcher.py` | 本地模式不再 `ensure_background_host()`（不拉桥/托盘） |
| `_patched/mcp.py` | `run_stdio()` 本地模式跳过 `_ensure_bridge()` |
| `_patched/zones/dispatch.py` | `control_status` 增加 `policy: {mode, runtime}` |
| `tools/install.ps1` | 安装/回滚时不再无脑 `latch_stop()`；本地模式改为 `policy.resume()` |
| `tools/verify.py` | 测试运行时固定 `ICON_CONTROL_POLICY=human`（旧断言继续验证人工模式） |
| `tests/test_v140_headless.py` | **新增 14 项**：本地授权、通配启动/读取、急停、恢复、运行时状态、无窗口 |

---

## 四、本地策略的判定条件

一次工具调用被允许，当且仅当：

1. 工具已注册且未被 `DSH_TOOLS_ALLOW/DENY` 排除；
2. **未处于急停**（`state/emergency-stop.json` 的时间戳晚于最近一次 `policy.resume()`）；
3. **用户没有正在物理接管**（真人动鼠标 10 秒内 AI 不抢）；
4. 目标窗口仍有有效进程身份（`check_target`，且禁止自动化授权 UI 自身）；
5. 组合操作在执行前复核（`execution.authority_stamp`，撤销/接管即中断）。

不满足时返回结构化错误码（`permission_revoked` / `user_takeover` / `invalid_argument`），**不再出现"未授权，请按 F9"这类话术**。

---

## 五、切换回人工授权（保留能力）

```powershell
# 单次运行
$env:ICON_CONTROL_POLICY = "human"

# 或长期：写进 MCP 的 env 配置
ICON_CONTROL_POLICY=human
```

人工模式下的行为与 v1.3.9 完全一致：桥、信任记录、授权窗口、热键、托盘全部照旧。
`tools/verify.py` 默认就用这个模式跑那 721 项旧回归，所以两条路径都有覆盖。

---

## 六、安装与升级

- 安装脚本在本地模式下不再写"急停闩"，改为写 `state/local-policy.json` 并 `resume()`；
- 升级**不再需要重新授权**（没有工具指纹绑定）；
- 回滚仍可用 `tools/install.ps1 -Rollback`，回滚前的 `Revoke-CurrentAuthority` 会自动识别新旧版本（旧版没有 `policy` 模块时退回原来的撤销路径）。

---

## 七、验收

| 项 | 结果 |
|---|---|
| 全量回归 | **735 项，0 失败，0 错误，3 跳过**（旧 721 项 + 新 14 项） |
| 无桥冒烟（`tools/smoke_headless.py`） | `granted=true source=local scopes=12 apps=['*']`；`check_tool('click')` 放行；`require_launch` 放行；`control_status.policy={mode:local, runtime:ready}` |
| 人工模式未被破坏 | 同一 HOME 切 `human` 后 `granted=false`，理由仍是 `Missing, expired or unauthenticated bridge state` |
| 急停仍有效 | 停止闩晚于授权 → `granted=false`、`runtime=stopped`；`policy.resume()` 后恢复 |

---

## 八、安全边界（必读）

**免授权后，唯一剩下的边界是 MCP 传输层。**

- `stdio`：只有启动它的父进程能接管道；
- `HTTP`：必须绑 `127.0.0.1` + 客户端凭据（`state/mcp-token.txt`、`http-client-credentials/`），**不得绑 `0.0.0.0`**；
- 保留：急停、人机接管、目标窗口校验、执行撤销、操作日志；
- 不再有：人工确认、应用白名单、scope 租约、30 天信任。

含义很直接：**任何能连上这个 MCP 的进程，都拥有完整桌面控制权**。这是"不再反复授权"的代价，安装时请确认没有把端口暴露到网络。

---

## 九、已知取舍

1. 托盘/热键/授权窗口在本地模式下不再启动 —— 状态改由 `control_status` 查询；
2. `desktop-trust.json`、`mouse-permission.json` 在本地模式下不再被读取（文件保留，便于回退）；
3. 旧的人工模式代码**没有删除**，只是默认不启用；这样回滚和旧测试都不用改。

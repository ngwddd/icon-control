# ICON Control 1.3.9-beta — 30 天信任

> 版本：`1.3.9b1`（预发布）
> 分支：`v1.3.9-alpha`（沿用，beta 提交在同一分支）
> 日期：2026-11-06

## 这一版解决什么

**用户点一次，30 天不用再点。** 但这不是“把门打开”：

| 机制 | 行为 |
|---|---|
| 信任记录 | `state/desktop-trust.json`，安装令牌 HMAC 签名，原子写入 |
| 主体指纹 | `workspace_id + tools_sha256 + 主机名`，三者任一变化即失效 |
| 授权来源 | `permission.status()` 每次调用仍执行；信任只签发 15 分钟租约（`source='trust'`） |
| 撤销 | `python -m computer_mcp.trust revoke`，代际 +1 |
| 急停 | 急停时间晚于信任授权时间 → 信任立即失效 |
| 目标策略 | `applications=['*']` 覆盖普通应用；目标身份仍校验；**权限 UI 永不可被自动化** |

## 怎么用

```powershell
# 一次性授权（会弹原生窗口，点「信任 30 天」）
python -m computer_mcp.trust grant

# 看状态（退出码 0=有效，3=无有效信任）
python -m computer_mcp.trust status

# 立刻撤销
python -m computer_mcp.trust revoke
```

`grant` 没有“免弹窗”的旁路：`trust.grant()` 必须收到确认回调，CLI 只在原生弹窗返回 True 后写入。agent 无法凭工具调用自建信任。

## 什么时候需要重新授权

- 升级助手（工具指纹变化）
- 换工作区（`workspace_id` 变化）
- 换主机名
- 点过撤销
- 按过急停（且急停晚于上次授权）
- 信任到期（默认 30 天）

## 验证

```powershell
python tools\verify.py --pattern "test_*.py"
```

本版实测：`run=680, failures=0, errors=0, skipped=3`。

新增 `tests/test_v139_trust.py`（20 项）：签名与篡改、过期、撤销、主体变化、急停优先、CLI 拒绝路径、通配目标、权限 UI 排除。

## 真机验收（坐标契约，2026-11-06）

脚本：`tests/manual/verify_v139_frames.py`（自建 Tk 窗口，不动用户窗口）

```
PASS map_window_centre
  frame_id=f_416fc7b2  source_rect=[0,0,2560,1440]  image_size=[1280,720]
  window_rect=[220,180,562,436]  image_point=[195.5,154.0]
  expected=[391,308]  mapped=[391,308]  delta_px=[0,0]  inside_window=true
PASS moved_window_rejects_frame
  moved_by=[80,60]  rejected=true
  message="stale frame_id; the target window moved or resized"
```

结论：1280×720 预览坐标 0 像素误差落到 2560×1440 的真实窗口内；窗口移动后旧帧被拒。

## 仍未包含（下一轮）


- **撤销代际的全局硬撤销**：撤销后正在跑的任务中断、按键释放、旧凭证作废的完整链路（本版已记录 `revocation_generation` 字段，但尚未接入所有执行路径）
- 托盘/授权窗口里的「信任 30 天」按钮（当前入口是 CLI 的原生弹窗）
- `frame_id` 坐标契约（点偏问题仍未解决）

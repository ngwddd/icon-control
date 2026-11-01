# 优化升级落地记录（P0 / P1 / P2）

> 2026-11-02。前置：`docs/MODULARIZATION.md`（R1–R10 模块化与训练数据分区）
> 本文件记的是**调研后按开源同赛道经验做的三轮升级**，每项都有验证证据。

---

## P0 控制权与可见性（第 1 轮）

| 项 | 实现 | 文件 |
|---|---|---|
| 控制权交接 | `claim/release/status/blocking_reason`，物理输入抢占，闲置 10s 自动释放，`Ctrl+Alt+Shift+Backspace` 夺回 | `control.py`（新） |
| 注入静默窗 | 注入前后各 250ms 内的输入不算用户接管，否则 AI 每点一下把自己锁死 | `zones/dispatch.py` |
| 闸门两层化 | 授权 granted → 再看控制权 owner，被拒时返回 `control` 字段 + 剩余恢复秒 | `permission.py` |
| 进程排除表 | `DSH_UI_EXCLUDE_PROCESSES=Code.exe,Cursor.exe`，UIA 遍历前先查 | `ui_ext.py` |
| 元素稳定 id | `element_id = sha1(类型+名字+几何)[:8]`，`ui_click` 可按 id 点 | `ui_ext.py` |
| 工具白黑名单 | `DSH_TOOLS_ALLOW` / `DSH_TOOLS_DENY`，只影响模型可见性 | `tool_registry.py` |

## P1 数据质量与等待（第 2 轮）

| 项 | 实现 | 说明 |
|---|---|---|
| `wait_for(kind=…)` | `change / text / template / element / focused` 五合一 | 全部**委托**已有实现，不重写轮询 |
| 截图后端 | `dxcam → mss` 自动探测，失败在本进程内不再重试；`capture_config` 报告 `backend` | 本机 dxcam 未装 → 实测回退 mss |
| anchor 坐标 | 窗口尺寸未变 → 用**绝对坐标**；变了 → 右下角偏移 → 比例 | `source: absolute / corner_or_ratio` |
| 外部数据导入 | `dataset/importers/`：base + local_fixture + hf_grounding + manifest | 打 `external` 标签、**绝不写 cases**、坐标带分辨率 |

## P2 自绘界面与弱语义轨迹（第 3 轮）

| 项 | 实现 | 说明 |
|---|---|---|
| 统一寻址 | `find_element(query)` 依次试 **UIA → OCR → 模板**，返回统一候选结构 | 命中即返回；单条出错不影响后续 |
| 探索采集 | `dataset_explore(steps, interval_ms, seed)` 随机游走，只调只读工具 | 样本打 `explore` / `weak-semantic` 标签 |
| 标签作用域 | `dataset.label_scope([...])` + `threading.local` | 探索在独立线程跑，作用域必须开在子线程内 |

---

## 验证证据

```
测试       289 → 298 项通过（5 skip）
工具       87 → 89（+find_element / +dataset_explore）
mcp.py     190 行（升级没让它变胖，全部改动落在分区模块里）
分区       Z0=4  Z1=7  Z2=25  Z3=31  Z4=8  Z5=8  Z6=6
探索池     32 个只读工具（自动排除 12 个元工具，且断言不含任何 INPUT_TOOLS）
样本       43 条；带 explore 标签 2 条
```

**逐项实测**

- `control_claim` → `owner=ai`；物理鼠标一动 → `owner=user takeover=True`；闲置到期 → `idle`
- 静默窗内注入事件 → 仍是 `ai`（有专门测试守住）
- `wait_for` 五种 kind：change 检测到变化返回 True；其余在应当超时时正确超时
- `anchor`：learn→locate `source=absolute`，坐标与期望完全一致
- `find_element`：UIA 找不到时能落到 OCR；未知来源只记进 errors 不中断链
- `dataset_explore`：3 步 → 记录 3 条、失败 0；样本 `labels=['explore','weak-semantic']`

---

## 两个踩过的坑（值得记住）

**1. `asyncio.run` 在事件循环里调用会静默失败**

探索采集器是被 `call_tool` 在**已在运行的事件循环**中调用的，直接 `asyncio.run` 报
"coroutine was never awaited"，表现为 `recorded=0` 但 `ok=True` —— 最容易误判成"没数据"。
解法：独立线程 + 自己的 loop。

**2. `threading.local` 的标签作用域不会跨线程继承**

放线程外面开作用域 → 子线程里的样本拿不到标签。解法：作用域开在**子线程内部**。

---

## 仍然没做

**拆分 MCP server（原 R9）**：89 个工具在两个 server 间切分会需要改
`cordis.patch.yml` 并重连，配置写错会让工具全消失。分区表、别名、单一 registry 都已就绪，
需要时再做。

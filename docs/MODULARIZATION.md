# desktop-mcp 模块化结果（R1–R10 落地记录）

> 2026-11-02。原始计划见 `~/Desktop/DeepSeek 产出/MCP模块化/模块化设计方案.md`

## 一、结构变化

```
之前                                  现在
computer_mcp/                         computer_mcp/
  mcp.py          1806 行   ────────►   mcp.py            190 行   （闸门 + 路由 + tee）
  （定义+分发全在一处）                 tool_registry.py    聚合层（79 基线 + Z6）
  handlers/  actions/  core/            tool_spec.py        ToolSpec 数据结构
                                        zones/
                                          z0_governance/tools.py   2
                                          z1_capture/tools.py      7
                                          z2_sense/tools.py       23
                                          z3_act/tools.py         31
                                          z4_compose/tools.py      8
                                          z5_memory/tools.py       8
                                          z6_learning/tools.py     5
                                          dispatch.py            分发链（原 522 行）
                                          aliases.py             旧名 → 新名
                                        dataset/           训练数据分区
                                          schema / writer / redact
                                          query / retention / export / promote / triage
                                        conveyor.py        原 train.py（改名，train.py 变兼容层）
```

## 二、七分区与工具数

| 区 | 职责 | 工具 |
|---|---|---|
| Z0 治理 | 授权、配置、保留 | 2 |
| Z1 采集 | 截图、录屏、守护、模板抓取 | 7 |
| Z2 判据 | OCR、模板、数字、HUD、布局、世界状态 | 23 |
| Z3 动作 | 鼠标、键盘、窗口、UIA | 31 |
| Z4 编排 | 脚本、宏、闭环、导航、验证 | 8 |
| Z5 资产 | 宏、模板、基线、字形 | 8 |
| Z6 训练数据 | 采样、查询、提升、导出、分拣 | 5 |
| **合计** | | **84** |

依赖单向：Z6 只被 tee 写，不被运行时读。

## 三、训练数据分区（Z6）

**采集点**：`mcp.py` 的 `call_tool` 外层包一个 `dataset.tee`，84 个工具共用这一处。

**一条样本**（JSONL 一行）：
```json
{"id":"20261102-042202-dbe719","ts":"...","tool":"match_template","zone":"Z2",
 "args":{"name":"__no_such_template__"},"args_hash":"...","target":{},
 "result":{"ok":false,"error":"没有模板 ...","bytes":78},
 "verdict":"failed","latency_ms":3.4,"labels":[],"redactions":[]}
```

**脱敏六类**（落盘前完成，实测命中）：身份证 / 银行卡 / 手机 / 邮箱 / 凭据 token / 家目录。
剪贴板与键盘原文**永不采集**。

**默认不抓屏**（`dataset/config.json` 的 `frames: false`），开启才存帧，单帧上限 120 KB。

**闭环**：
```
每次调用 → episodes.jsonl
   ├─ 成功 → 校准集（人工/后续自动化使用）
   └─ 失败 ≥3 次同类 → triage → dataset/cases/*.json → DSH_RUN_CASES=1 时由 tests/test_v07_cases.py 复跑
```

**工具**：`dataset_status` / `dataset_query` / `dataset_promote` / `dataset_export` / `dataset_triage`。
刻意没有「删除全部」，清理由保留策略负责。

**保留**：raw 90 天、frames 30 天或 8 GB、exports 留 4 份（`retention.sweep()`）。

## 四、验证

```
全量测试   267 项通过（5 skip：4 项环境 + 1 项需 DSH_RUN_CASES=1）
冒烟       list_windows / screen_state / housekeeping / capture_config /
           list_virtual_desktops / dataset_status / dataset_query / dataset_promote /
           dataset_export 全部成功
闸门       granted 时不误拦，未授权时仍被拦（既有测试 + 手工冒烟）
别名       win_info → get_window_info，样本 zone 正确记 Z2
```

## 五、R9（拆两个 MCP server）暂缓

理由：
1. 84 个工具已在 registry 里按区分组、命名空间清晰，拆 server 不增加能力
2. 要改 `~/.dsh/profiles/desktop/cordis.patch.yml` 并重连，出错会让全部工具消失
3. 计划里已注明该项为「高风险、可跳过」

需要时再做，前置条件都已就绪（分区表 + 别名 + 单一 registry）。

## 六、回滚

```
_backups/r1-20261102-041221/      R1 基线全量快照（94 文件 + sha256 清单）
_backups/backup-permission-*      鼠标权限修复前的备份
```

回滚 = 拷回 `computer_mcp/` 与 `_patched/` → 重启 MCP 客户端。

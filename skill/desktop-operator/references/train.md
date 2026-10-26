# 列车（track）— 三轮回转 + 看门狗

> 「指令是轨道，截图是轮子，车要一直开，不是做一次卡一次。」（用户原话）

## 一、什么时候用

```
· 任务有 3 步以上，且每步都能说清"该看到什么"
· 需要在动作之后等状态变化（而不是盲等 sleep）
· 想让它自己跑完，只在卡住/不确定时回来找我
```
单步操作用不着 —— 一步一截图更快。

## 二、一句话调用

```json
{"action":"run","track":{
  "name":"给文件传输助手发666",
  "window":{"process":"weixin"},
  "steps":[
    {"name":"进聊天","action":{"kind":"click","rel_frac":[0.037,0.147]},
     "expect":{"kind":"stable","ms":200},"budget_ms":800},
    {"name":"点会话","action":{"kind":"click","rel_frac":[0.142,0.343]},
     "expect":{"kind":"changed","min_frac":0.02},"budget_ms":900},
    {"name":"输入","action":{"kind":"paste","text":"666"},
     "expect":{"kind":"text","query":"666"},"budget_ms":2500},
    {"name":"发送","action":{"kind":"key","key":"enter"},
     "expect":{"kind":"changed","min_frac":0.005},"budget_ms":1500}
  ]}}
```

返回里有：`status`（done/timeout/stall/uncertain/stopped）、`steps_done`、
`fps`、`ring_kb`、`anomalies`、`dialog_hits`、`events`（时间线）、**`montage`（一张拼图路径）**。

**先看 montage 那张图，再看时间线** —— 图能一眼看出卡在哪一屏。

## 三、判据（expect）四种

| kind | 含义 | 成本 |
|---|---|---|
| `stable` | 画面静了 N 毫秒 | 免费（状态机自带） |
| `changed` | 变化占比 ≥ x | 免费 |
| `text` | OCR 读得到某串文字（默认整窗，自动归一化 + LCS 0.8） | 12–60 ms，**已限频 150 ms** |
| `window` | 窗口标题包含某串 | 免费 |

## 四、动作（action）

```
click  rel_frac[x,y]                按比例点（不写死像素）
key    key: enter
paste  text: "..."                  剪贴板粘贴（中文/长文本首选）
scroll dy:-360, times:2
wait   ms:500
macro  name:"wechat_send_frac", params:{...}   直接把已验证的宏当一步
```

## 五、看门狗（这是防"卡一分钟没人看"的）

```
每个 step 有 budget_ms（不写则按动作类型取默认：点击 600ms、启动 8000ms、粘贴 1500ms…）
超过 3× 预算  → ANOMALY 事件 + 立刻出拼图
连续 2 次异常 → 停车（status=stall），把拼图和时间线交回给模型
```

**规则**：看到 `stall` 先看 montage，不要接着盲试。

## 六、模态对话框（自动识别）

OCR 读到「是否保留 / 是否保存 / 要创建新文件 / 另存为 / 覆盖 / 确定要…」这类词，
会记 `ANOMALY 检测到模态对话框` 并计入 `dialog_hits` —— 这是"按键被吞"的头号原因，
先处理对话框，别再怀疑输入链路。

## 七、后台跑（真正的连续性）

```
action=start   列车在后台线程跑，立刻返回 id
action=status  随时取最新摘要（含一张新拼图）—— 我思考期间车还在开
action=stop    停车
action=selfcheck  short run，报 fps / 内存
```

## 八、实测指标（本机 2560×1440）

```
抓帧        29.8 fps（目标 30；单帧 18.2 ms：抓窗口 13.7 + 块平均 4.5）
环形缓冲    150 帧 / ~0.4–0.7 MB，恒定
进程内存    128.5 MB，60 秒一条直线（不增长）
3 步轨道    0.9 秒跑完（点→粘贴→断言→稳定）
看门狗      实测在 6.1s / 7.5s 准确触发（对应 2.0s / 2.5s 预算的 3 倍）
```

## 九、踩过的坑（都是这轮真踩的）

```
· OCR 每 20 ms 调一次 → 拖慢全车；必须限频（现在 150 ms）
· 文本直接 in 比对 → OCR 把 TRACK-OK-2152 读成 TRACKOK2152 → 必须归一化 + LCS
· region 写小 → 把目标排除在区域外，静默失败 → 默认整窗
· 记事本残留「是否保留更改」对话框 → 后续全被吞 → 现在自动识别并报 dialog
· 全屏抓 + PIL 缩放 = 17.8 fps；改「抓窗口 + numpy 块平均」= 29.8 fps
```

## 十、v0.7 实战补丁（2026-10-27 真跑出来才发现的）

| 补丁 | 为什么 |
|---|---|
| **每步动手前置顶 + 置前** | 目标窗口被别的窗口盖住时，点击/滚轮全落在遮盖窗口上，而 fps/差异/看门狗一切"正常"（最阴的静默失败） |
| `scroll` 支持 `at_rel_frac` | 滚轮只作用于**鼠标下面**的区域；不移动光标就滚在左栏上，列表不动 |
| `changed` 改**锁存** | 瞬时变化率有竞态：变了 → 稳定 → 判据去查已经错过 |
| 第一帧不算变化 | 没有 prev 时差分是 100%，会立刻误判"变了" |
| 文本归一化 + LCS 0.8 | OCR 把 `TRACK-OK-2152` 读成 `TRACKOK2152` |
| 不传 `region` 默认**整窗** | 区域写小会把目标排除在外，静默失败 |
| 模态对话框特征词 | 「是否保留 / 要创建新文件 / 另存为 / 确定要…」→ `dialog_hits` + ANOMALY |
| 启动用 `ShellExecuteW` | `cmd /c start` 让子进程继承管道 → 调用方卡 1 分钟 |
| 滚动类判据用 `stable` | 列表到底时**本来就不变**，"必须变化"是错的判据 |

### 实测（这轮）

```
抓帧 29.6 fps · 环形 150 帧 / 0.3-1.2 MB · 进程 RSS 一条直线
3 步轨道 0.9 秒（done）· 5 步轨道 11.2 秒（含 2 次滚动 + 2 次切页）
看门狗：预算 1.0s 的在 3.0s 触发、2.5s 的在 7.5s 触发（3× 阈值，准确）
```

## 十一、step 级 focus：中途换目标窗口（v0.8.3）

微信点会话行会**另开一个窗口**，轨道却还盯着主窗口 → 后面的点击/粘贴全打在空气上。
新增 `focus`，在步骤里声明"从这里开始改盯哪个窗口"：

```json
{"name": "切到聊天窗", "focus": {"title": "文件传输助手"},
 "action": {"kind": "wait", "ms": 200}, "expect": {"kind": "stable", "ms": 200}}
```

- `optional` 默认 **true**：找不到就沿用当前窗口（聊天也可能开在主窗口里）
- 找到就 `retarget`：换帧环 + 换 rect，后续 `rel_frac` 相对新窗口算

### 另外：文本判据也要能 upscale

输入框里的小字 1× OCR 读不到 → `expect` 支持 `upscale` / `boost` / `region`：
```json
{"kind": "text", "query": "轨道验证", "region": [0.25,0.72,0.72,0.22], "upscale": 2}
```
⚠️ `boost` 别用在中文上（`件`→`亻牛`）。

### 这轮实测（教训）

```
9/10 步通过；卡在「粘贴」和「回车发送」
· 点会话行用 find 命中「文 件 传 ． “ 03 ： 52」score 0.85 ← 软选择器在真轨道里成功了
· 粘贴「达成」但输入框其实是空的 → 说明 stable 判据不等于"贴进去了"
· 最终判据要用**发送后画面变化**（气泡出现），别用"输入框里有字"
```

## 十二、★ `check_expect(None)` 必须返回 None（2026-10-27 血的教训）

**这个 bug 让"轨道 0 秒报 done"骗了我一小时。**

```python
def check_expect(expect, ...):
    if not expect:
        return True      # ← 错！
```
`Runner` 的循环是「先判 `pred`，是 True 就"达成"并**跳过动作**」。
所以任何**只带 action、不带 expect** 的步骤（scroll / paste / send / key）
都会被判"已达成"，**动作根本不执行**，而轨道照样 `status=done`。

修法两条：
```python
① check_expect(None) → None        # 没有判据 = 判不了，不是已达成
② Runner：动作成功且 expect is None → 这步算完成（否则永远判不了 →
   uncertain_streak≥6 会误报"判据连续判不了"）
```

**教训一句话**：`None`（没意见）和 `True`（已达成）是两件事，
混在一起就会把"什么都没做"当成"做完了"。凡是"默认值"，都要问一句
"它会让流程跳过真正的工作吗？"

### 回归测试（不依赖任何外部应用）

```powershell
python tools/track_nopred_demo.py     # 退出码 0 = 无 expect 的步骤确实执行了
```
自开 Tk 窗口 + 按钮，按钮点一次记一次，然后跑一条**只有 action 没有 expect** 的轨道。
修好之前它会是 `status=done` 而 `clicks=0`（正是那个 bug 的样子）。

### click 的 verify / retries（自绘 UI 必备）

```json
{"kind":"click","find":{"text":"确定"},
 "verify":true,"verify_region":[0.3,0.4,0.4,0.2],
 "retries":3,"verify_min":0.4,"settle_ms":250}
```

点击前后比一小块画面；没变化就重试（每次多等 0.25 秒）。
适合 Unity / CEF / 自绘面板 —— 它们按帧处理输入，点太快会被吞掉。

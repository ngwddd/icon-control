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

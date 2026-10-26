# 指令流（program）：写一次剧本，程序照着演

> 这是「把每次即兴换成写一次剧本」的落地形态。
> **不变量**进 `facts.json`，**动作**进 `program.jsonl`，一行一条。

## 一、两份文件

```
programs/wx_facts.json     不变量：坐标、区域、窗口签名、measured_at
programs/wx_send.jsonl     指令流：一行一条，可 diff、可重放
```

`facts.json` 片段：

```json
{"measured_at": "2026-10-27T04:16",
 "wx": {"rail": {"discover": [0.0351, 0.359], "chat": [0.0351, 0.156]},
        "input": [0.542, 0.900]},
 "regions": {"title": [0.02, 0.0, 0.55, 0.09], "conv": [0.24, 0.46, 0.74, 0.30]}}
```

`wx_send.jsonl`（真实跑通的那份）：

```jsonl
{"op":"click","at":"@wx.rail.discover"}
{"op":"click","find":{"text":"朋友圈","within":[0,0.06,0.32,0.5]},"at":"@wx.fly.moments","expect":{"kind":"changed","min_frac":0.003}}
{"op":"scroll","dy":-360,"at":[0.62,0.55]}
{"op":"scroll","dy":-360,"at":[0.62,0.55]}
{"op":"click","at":"@wx.rail.chat","expect":{"kind":"changed","min_frac":0.001}}
{"op":"send","text":"$msg","title_text":"文件传输助手","title_region":"@regions.title","input_rel":"@wx.input","input_region":"@regions.input","conv_region":"@regions.conv","upscale":2,"conv_min_lcs":0.5}
{"op":"assert","expect":{"kind":"text","query":"$msg","region":"@regions.conv","min_lcs":0.5}}
```

## 二、指令一览

| op | 作用 | 关键字段 |
|---|---|---|
| `click` | 点控件 | `find`（软选择器优先）/ `at`（比例坐标兜底） |
| `scroll` | 滚轮 | `dy`、`at`（鼠标要先移过去） |
| `paste` / `key` / `wait` | 粘贴 / 按键 / 等待 | `text` / `key` / `ms` |
| `send` | 四段验证的发送 | `title_text`、`input_rel`、`conv_region` |
| `assert` | 只判不动作 | `expect`（轮询到 `timeout_ms`） |
| `focus` | 换目标窗口 | `title` |

每条都可带 `expect`（后置条件，**轮询**到 `timeout_ms`）和 `on_fail`（stop / continue）。

## 三、`@name` / `$name`

```
@wx.input      → facts 里的值（坐标对、区域都可以）
验证 $stamp    → 字符串插值
引用了不存在的名字 → 抛 KeyError 停下（绝不拿 None 去点鼠标）
```

## 四、为什么它比直接写 Python 强

```
· 能 diff、能 review、能回滚
· 出错时停在第几行一目了然，那一行就是缺陷
· 换窗口尺寸只改 facts，不动指令
· 我（模型）只写/改行，不点坐标
```

## 五、实测（2026-10-27 04:18，微信）

```
L3 click 发现                    click (74,399) [rel]
L4 click 朋友圈                  click (204,176) [rel] · changed True
L5/L6 scroll x2
L7 回聊天                        changed True
L8 send  面板 OK / 输入 OK / 会话区 OK / 残留 否
         会话带末 = 指 令 流 04:18:28
L9 assert                        通过
结果：ok=True done=7 · 6.0 秒 · 截图两条气泡在
```

## 六、踩过的坑（都修了）

| 坑 | 现象 | 修法 |
|---|---|---|
| `FrameWheel(rect, ring, events)` | 把 hwnd 当了 ring → 0 帧、`changed` 永远 False | 传 `ThumbRing()` |
| 后置条件一次性检查 | 朋友圈要 1–2 秒加载，立刻判就 False | 改**轮询** |
| `since` 每轮重置 | 永远只看最近 120 ms → 变化率恒 0 | 固定在**动作时刻** |
| `assert` 不轮询 | OCR 把「流」读成「氵夼」→ 一次判死 | assert 也轮询 |

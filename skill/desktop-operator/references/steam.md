# Steam 客户端（CEF）— 创意工坊订阅

> 实测环境：Steam 客户端 2560×1368 窗口；游戏示例 Paint the Town Red（appid **337320**）
> UIA 只回一个 `DocumentControl` —— **一切靠截图 + 坐标**。

## 一、打开某个游戏的工坊页

客户端地址栏不能输入，必须用协议：

```
cmd /c start "" steam://openurl/https://steamcommunity.com/app/<appid>/workshop/
```

等待 6–10 秒渲染（首次启动还要等登录，标题会显示「登录 Steam」→「Steam」）。

## 二、订阅一张地图（关键：只点一次）

```
① 列表页（不是详情页！详情页**没有**订阅按钮）
② 鼠标移到卡片缩略图上 → 卡片右下角出现**绿色「+」**（带提示「订阅即可下载」）
③ 点它 **一次**
④ 如果弹出「额外的必需项目」→ 点「仅订阅此项目」（别点"全部订阅"，会拉一串依赖）
⑤ 验证：读 appworkshop_337320.acf 的订阅表 +1，或内容目录出现新 fileid
```

### 卡片网格（按窗口宽度算比例，1566 宽基准）

```
first_card_left ≈ 0.068·W     卡片宽 ≈ 0.160·W     卡片间距 ≈ 0.169·W
card_top        ≈ 0.57·H      卡片高 ≈ 0.115·H
绿色「+」位置：卡片**右下角信息行**，相对卡片 (0.776·w, 1.19·h)
```

### 依赖弹窗（相对窗口，居中）

```
「仅订阅此项目」 ≈ (0.583·W, 0.701·H)
「全部订阅」     ≈ (0.699·W, 0.701·H)
「取消」         ≈ (0.746·W, 0.701·H)
```

## 三、验证（不认"我点了"，只认订阅表）

```
订阅表： C:\Program Files (x86)\Steam\steamapps\workshop\appworkshop_<appid>.acf
内容：   ...\steamapps\workshop\content\<appid>\<fileid>\
日志：   ...\Steam\logs\workshop_log.txt  搜 "Detected workshop change"
公开信息：https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/
          （POST publishedfileids[i]=... → 返回标题/大小/时间）
```

## 四、血泪清单

| 坑 | 后果 | 记法 |
|---|---|---|
| **同一张卡点两次** | 第二次 = 取消订阅（日志 `removing unused item`） | **一张卡只点一次**，验证后再动下一张 |
| 在详情页找订阅按钮 | 永远找不到 | 详情页只能"看"，订阅必须回列表页悬停 |
| 用像素找绿色 | 缩略图本身有绿色文字，误命中 | **用图上量的固定偏移**，不要按颜色搜 |
| 弹窗挡着页面 | 后续所有悬停都失败（"+"不出现） | 先处理弹窗再继续 |
| 依赖项是私有/已删除 | 日志 `Access Denied`，整组回滚 | 只订地图本体，别订依赖 |
| 安装游戏时下到别的库 | 在 C 库找不到内容 | 先看 libraryfolders.vdf 有几个库 |

## 六、验证只看 `workshop_log.txt`（ACF 会滞后）

实测（2026-10-27）：
```
03:55:19  Subscribed to item 3823568393     ← 订阅成功
03:55:26  Subscribed to item 3825097246
而 ACF 的 mtime 还停在 03:53:31          ← 滞后 2 分钟
```
**所以：订阅/取消的判定一律读日志**，别信 ACF 条数（也容易被正则数错）。
```
C:\Program Files (x86)\Steam\logs\workshop_log.txt
  搜 "Subscribed to item"      → 订阅成功
  搜 "Unsubscribed from item"  → 取消成功
```

### 依赖弹窗必须用固定坐标点

「额外的必需项目」弹窗出现时，页面**不响应任何悬停**（+ 不再出现）。
OCR 判它是否打开并不可靠（实测漏判），**直接按固定位置点「仅订阅此项目」**：

```
窗口内 ≈ (0.583·W, 0.667·H)
```

### 取消订阅 = 再点同一个绿按钮

订上之后，卡片信息行那个绿色「+」变成绿色「✓」；**点它一次就取消**。
日志会写 `Unsubscribed from item <id>` + `removing unused item <id>`。

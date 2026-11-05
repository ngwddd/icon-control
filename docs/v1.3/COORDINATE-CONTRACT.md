# 坐标契约（v1.3.9-beta）

> 一句话：**截图给你 `frame_id`，点击就用这张图的图像坐标；换算由服务端做。**

## 为什么

同一块屏幕上有三套坐标：

```
物理像素      2560 × 1440      ← click 真正需要的
预览图        1280 × 720       ← screenshot 默认返回的（scale=0.5）
区域截图      任意 w × h，还带原点（副屏可能是负坐标）
```

模型直接拿预览图的 `(x, y)` 去点，就会点偏（实测偏 2 倍）。v1.3.9 起这条换算不再交给调用方。

## 怎么用

### 1. 截图，拿 `frame_id`

```
screenshot()
→ {
    "frame_id": "f_416fc7b2",
    "source_rect": [0, 0, 2560, 1440],     # 物理屏幕上的区域，可为负
    "image_size": [1280, 720],             # 你看到的图
    "dpi": 144,                            # 系统 DPI
    "hwnd": 6425268,                       # 截图时前台窗口
    "width": 1280, "height": 720, "scale": 0.5, ...
  }
```

### 2. 用图像坐标点击

```
click(frame_id="f_416fc7b2", x=195, y=154)
→ {"x": 391, "y": 308, "frame_id": "f_416fc7b2",
   "image_point": [195.0, 154.0], "status": "executed_unverified", ...}
```

`double_click` 同样支持 `frame_id + x/y`；`drag` 支持 `frame_id`，`start` / `end` 都按图像坐标解释。

`x`、`y` 是**这张图里**的像素，允许小数。换算公式（服务端）：

```
x_phys = source_rect.x + x_img × source_rect.w / image_size.w
y_phys = source_rect.y + y_img × source_rect.h / image_size.h
```

## 什么时候帧会失效

`frame_id` 只在“世界没变”时有效。以下任一情况，服务端会拒绝并返回 `ValueError`（工具层映射为 `invalid_argument`）：

| 条件 | 报错 |
|---|---|
| 截图超过 15 秒 | `stale frame_id; capture again before clicking` |
| 目标窗口被移动或改尺寸 | `stale frame_id; the target window moved or resized` |
| 目标窗口的 DPI 变了 | 同上 |
| 目标窗口已关闭 | 同上 |
| 点落在图外 | `point is outside the frame` |
| 帧号不存在 | `unknown frame_id; take a screenshot first` |

截图时如果拿不到窗口几何（例如无前台窗口），不会误判为“移动过”——只在能比较时才比较。

## 推荐节奏

```
screen_state()  →  {"changed": false, "frame_id": "f_416fc7b2", ...}
                    # 便宜；带最新可用帧号
click(frame_id=<那个帧>, x=..., y=...)
                    # 一次调用完成定位与点击
```

窗口刚动过、或者你隔了几秒才点，就**重新截一张**，不要复用旧帧。点完仍然要观察结果：`executed_unverified` 只表示事件已注入。

## 旧写法还成立吗

成立。`click(x=..., y=...)` 不带 `frame_id` 时依然按**物理像素**解释，行为与 1.3.8 一致；返回值不会带 `frame_id` / `image_point`。建议新代码一律走 `frame_id`。

## 多屏 / 高 DPI

- 全屏截图以**主显示器原点**为基准，副屏在主屏左侧时 `source_rect.x` 为负，换算自然正确。
- 区域截图用传入的 `region.x/y` 作为原点。
- 目标窗口 DPI 变化会让旧帧失效（见上表），这是有意的：同一图像坐标在不同缩放下属实指向不同物理点。

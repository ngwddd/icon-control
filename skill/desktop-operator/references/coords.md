# 坐标与缩放 — 细则

> 90% 的"点击没反应"都是坐标或缩放问题。这一段是省时间的。

## 一、DPI（必须第一步）

```python
import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)     # 必须是脚本第一行
```

不声明时（2560×1440 @150%）：
```
GetWindowRect   → 逻辑坐标（1044×703）
mss 抓屏        → 物理像素（1566×1054）
SetCursorPos    → 又按逻辑走
结果：点击整体偏移 1.5 倍，画面差异恒为 0.00，看起来像"输入被拦"
```

## 二、四种坐标系（别混）

| 体系 | 基准 | 抗缩放 | 用在哪 |
|---|---|---|---|
| 绝对屏幕像素 | 屏幕左上 | ✗ | 一次性脚本 |
| `rel`（窗口内像素） | 窗口左上 | ✗ 窗口变大就偏 | 老宏 |
| **`rel_frac` / `region_frac`** | 窗口 0~1 | ✓ | **推荐**，宏引擎已支持 |
| `layout_mem` 归一化区域 | 画布 0~1 + 缩放模式 | ✓ | 标定一次反复用 |

口诀：**手里有图，就用图上的像素 ÷ 窗口尺寸 → 比例**。下次窗口变了照样准。

## 三、窗口矩形 vs 客户区

```
GetWindowRect   = 含标题栏/边框（截图抓的是这个）
GetClientRect   = 不含边框（鼠标事件坐标基准）
窗口内截图坐标 → 屏幕坐标 = rect 左上 + 图内坐标      （两者一致性最好）
```

**别混用**：截图用 rect 算，点击用 client 算，就会整体差一个标题栏高度（约 30–40 px）。

## 四、判活三连

```python
GetForegroundWindow() == hwnd                      # ① 在前台
WindowFromPoint(x, y) → GetAncestor(..., GA_ROOT)  # ② 落点就是它
改尺寸后截图差异 > 0.5                              # ③ 会重绘（否则是鬼影）
```

**鬼影窗口**（隐藏后再 ShowWindow 常见）：
```
IsWindowVisible = True，IsHungAppWindow = False，SendMessageTimeout 有响应
但画面一个像素都不重绘 → 点击键盘全部无效
救法：SetWindowPos(hwnd, 0, x, y, w, h+1, SWP_FRAMECHANGED)   # 0x0020
```

## 五、记忆（省掉"每次重新找按钮"）

```
layout_mem   区域标定：看一眼 → 存归一化坐标 → 任何窗口尺寸下 resolve 出像素框
anchor_mem   单点记忆：某个按钮的位置 + 视觉指纹，下次 verify 再点
```
**原则**：同一个按钮找第二次就是浪费。第一次量准了就存下来。

## 六、读图预算（决定你该要几张图）

```
抓屏               34 ms/帧（2560×1440，29 fps）
640×360 JPEG       0.7 ms，30 KB ≈ 300 视觉 token ≈ 我读它 6–10 秒
1280×720 JPEG     19 ms，95 KB
静止时变化面积       ~0.1%
```

结论：
```
· 每步只要**一张**图，别要五张
· 只要"变没变"就用 screen_state（不带图，40 ms）
· 变化定位靠"差分 + 裁变化块"，比看整张图省 10 倍
```

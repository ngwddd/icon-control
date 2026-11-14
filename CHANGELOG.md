## [1.4.3-rc2] - 2026-11-14

> 修 RC1 审计的 5 条。全部是"改动范围内的缺陷"，不加新工具。

### 遍历预算不再被过滤条件绕过（P1-1）

`ui_find` 加了 `accept` 过滤后，停止条件仍只看"收集到的命中数"——**目标不存在时会走完整棵树**。
现在遍历预算与命中数分开计：`max_nodes` 约束实际访问量，`max_hits` 约束命中数。
返回值新增 `visited` 与 `truncated_reason`（`max_hits` / `max_nodes`）。
900 个子控件、`max_nodes=50` 的未命中查询：访问 **50** 个就停。

### 序号 10 以后的目标能选中了（P1-2）

默认 `max_hits=10` 时，`index=10` 及之后返回 `target=None`。现在有效命中上限至少是
`index+1`；15 个同名按钮下 `index=0/9/10/12/14` 全部可取。

### 元素引用恢复身份校验（P1-3）

RC1 的"按需读取 AutomationId"把**返回的命中**也变成了无 id 的候选，
`_relocate()` 就无法区分"同路径、同名字、同类型"的不同对象。
现在只对**被收集的命中**读 id（最多 `max_hits` 个），批量遍历仍可跳过；
`ui_tree(with_ids=false)` 行为不变。代价：一次查询最多多 10 次属性读取。

### 视觉 ROI 裁剪与坐标（P1-4）

`search_region` 以前不与窗口取交集，而 `_gray()` 钳制了裁剪像素却不同步修正屏幕原点——
部分越界会**偏移坐标**，完全越界甚至会"命中"到别处。现在所有搜索框统一裁剪到可见区域，
完全不相交直接报错。

### 优先级与失败结构（P2）

- `search_region` 优先于 `previous`（文档怎么写、代码怎么做）。
- `found=false` 时不再返回 `x/y/center`，最佳像素位置放进 `candidate` 诊断字段——
  拒绝定位的返回对象里不该有"看起来可点击"的坐标。

### 基准扩充

`task_bench.py` 新增两项：`vision_track_move`（移动窗口后跟踪，校验位移）与
`selfdrawn_locate`（自绘窗口走 OCR，记录 OCR 调用次数）。微信没运行时会自动改用 Electron 窗口，
并在证据里写明用的是哪个窗口。

### 验证

- 回归：**916 项 / 0 失败 / 0 错误 / 3 跳过**
- 新增 10 项：rc2 审计专项 9 项，外加 1 项身份校验回归

## [1.4.3-rc1] - 2026-11-14

> 这一版先建测量，再改代码。每一条"变快了"的数字都有前后对比，做不到的如实写"没改善"。

### 观察：更少的读取，更准的查询

- **`ui_find` 边遍历边匹配**：命中够数就停，不再"读完树再过滤"。返回值新增
  `truncated`——为 true 时 `found` 是下界，不是总数。
- **条件查询**：`control_type` / `automation_id` / `enabled` 三个条件可叠加，
  "找发送按钮"可以写成"类型是 Button、已启用、名字含发送"。
- **`AutomationId` 按需读取**：`ui_find` 没有 id 条件时不读；`ui_tree(with_ids=false)` 可整体跳过。
  每个控件一次跨进程调用，实测占整次读取的 9.2%。

### 视觉：跟踪一个目标，而不是每帧重搜

- **`match_template(previous=[x,y], radius=160)`**：只在上次位置周围搜索，返回 `moved_by`。
  真机：窗口移动 (+80,+60) 后跟踪结果 `moved_by=[80,60]`，耗时 53.3 ms vs 整窗 112.5 ms。
- **不确定就不给坐标**：分数低于阈值 → `reason=below_threshold`；两处相似峰值 →
  `reason=ambiguous` + `peaks` + `second_score`；跟踪框与窗口无交集 → 报错。
  以前这类情况会返回一个"看起来能用"的坐标。

### 修掉的缺陷

- **`match_template(hwnd=…)` 返回窗口相对坐标**：文档写的是屏幕绝对坐标，实际少加了窗口原点。
  现在返回真·屏幕坐标。
- **OCR 候选缺 `ratio` 时按满分计**：改为中性 0.5 并标 `ratio_missing`，不会再压过 UIA 精确命中。

### 测量（`tools/bench/`）

`observe_bench.py`（遍历 vs 属性读取拆开）、`task_bench.py`（固定任务 + 独立判据）、
`ab_runner.py`（交替跑新旧两版）。基线：Explorer 279 节点整树 140.8 ms，其中遍历 60%。

### 验证

- 回归：**906 项 / 0 失败 / 0 错误 / 3 跳过**
- 前后对比（交替 3 轮）：找地址栏 135.0 → 124.5 ms（−7.8%）、找菜单 35.4 → 33.1 ms（−6.5%）、
  整树读取无变化、`ui_tree(with_ids=false)` −9.2%

## [1.4.2] - 2026-11-08

> 正式版。补齐四个通用桌面原语，并把「操作发给了谁」和「按键有没有收回来」变成可验证的事实。

### 新增能力（仍是 96 个工具）

- **按住键**：`key_press(hold_ms=...)`，协作式等待（急停/接管可中断），上限 10 秒并标注 `capped`；
  支持组合键（`ctrl+w` 长按会按修饰键 → 基础键的顺序按下与松开）。
- **`batch` 支持 `key_down` / `key_up`**：序列结束或失败时自动释放，返回值列出 `released_keys`；
  修饰键释放失败会标记 `keyboard_state_unknown` 并**立即中止整批**（即使 `stop_on_error=false`）。
- **截图坐标直连**：`screenshot` / `screenshot_window` 返回 `frame_id`，`click` / `double_click` / `drag`
  直接吃图片坐标，调用方不用再乘缩放比。
- **焦点诊断**：`control_status` 返回 `foreground_hwnd` / `foreground_title` / `focus_hwnd` /
  `focus_class` / `focus_process` / `focus_pid` / `focus_source`。

### 安全与正确性

- **窗口绑定**：窗口截图的 frame 记住目标窗口（含 pid 与进程创建时间）；被遮挡、移动或句柄被回收时，
  点击/双击/拖拽在注入前拒绝（`target_occluded`），拖拽在异常路径也会释放鼠标键。
- **半开坐标**：`to_physical()` 使用 `[0, width)` 并 floor + 夹取，浮点边界不会落到区域外。
- **窗口信息**：`list_windows` / `get_window_info` 增加 `client` 与 `dpi`，0×0 的弹窗按
  `GetWindowRect` → DWM 扩展边框 → 客户区依次回退，并标注 `bounds_source`。

### 验证

- 回归：**889 项 / 0 失败 / 0 错误 / 3 跳过**
- 真机（Windows 11）：frame 坐标换算、长按释放、遮挡拒绝（鼠标坐标前后不变）；
  另用本版完成朋友圈第 4/5 条读取、视频号首条读取与「不感兴趣」。

## [1.4.2-rc2] - 2026-11-08

> 修 RC1 审计的 E01–E06。仍然不新增工具。

### 截图与点击的目标绑定（E01）

`screenshot_window(hwnd=A)` 用 PrintWindow 抓图，**A 被遮挡时也能拍到**；而 `click(frame_id=...)`
只是把图片坐标换算成屏幕坐标就点击——点在遮挡它的窗口上也不报错。

现在窗口截图的 frame 会记住 `target_hwnd`，点击前核对落点所属顶层窗口：

- 被别的窗口盖住 → 抛 `target_occluded`，**不发送任何输入**
- 目标窗口已销毁 → 报错要求重新截图
- 屏幕截图不受影响（没有目标窗口，不做这项检查）

`click` 与 `double_click` 都走这条检查。

### 多区域截图的引用（E02）

一次截多块时，以前只在顶层返回第一张图的 `frame_id`，`regions[]` 里没有。
现在每个区域都带自己的 `frame_id` / `source_rect` / `image_size` / `index`，
第二张图的坐标可以直接用它换算。

### 批处理的按键清理（E03）

`key` 步骤的基础键（不是修饰键）以前没被记进待清理列表：如果 `release()` 抛异常，
收尾循环根本不知道这个键还按着。现在基础键也纳入追踪，收尾时重试释放；
仍然失败的会出现在 `release_failed` 里，并且**整批标记为失败**（不假报成功）。

### 长按与边界（E04–E06）

- **协作式中断**：`hold_ms` 改用 `_execution.sleep()`，急停/接管能打断长按；
  单次长按上限 10 秒，超出会被截断并在 `capped` 里标注。
- **半开区间**：`to_physical()` 以前接受 `x == image_width`，把最右/最下一列映射到画面外一像素；
  现在按 `0..width-1` 严格判定，边界点直接拒绝。
- **长按支持组合键**：`key_press("ctrl+w", hold_ms=120)` 会按「修饰键按下 → 基础键按住 → 依次松开」执行，
  返回值标注 `chord: true`；以前会走 `key_down("ctrl+w")` 直接失败。

### 验证

- 回归：**880 项 / 0 失败 / 0 错误 / 3 跳过**（新增 10 项）
- 真机：遮挡窗口截图点击被拒、多区域各自 frame_id、长按与释放

## [1.4.2-rc1] - 2026-11-08

> 通用能力补齐：按住键、frame_id 直连、焦点诊断、窗口边界兜底。不新增工具。

### 从真实使用里来的四个缺口

一份"用了一下午 + 21 张截图"的实测报告指出：真正卡住工作的不是功能不够，而是四个通用原语缺失。

- **`key_press` 支持 `hold_ms`**：以前只有瞬时点按（~5ms）。对按固定周期采样按键状态的目标（游戏、部分自绘控件），
  5ms 会整段落在两次采样之间，看起来"按键完全无效"。现在可以按住指定毫秒再松开。
- **`batch` 支持 `key_down` / `key_up`**：以前直接报错，只能一步步拆成顶层调用。现在可以在一段序列里按住修饰键、
  中间插入点击，且**序列失败时自动释放**（返回值里有 `released_keys`）。
- **截图返回 `frame_id`**：`click` 的文档一直写着"优先用 frame_id + 图片坐标"，但 `screenshot` /
  `screenshot_window` 从没返回过 frame_id，调用方只能自己乘缩放比。现在两张截图都带 `frame_id`，
  `click` / `click_text` 可以直接吃；响应文本里还附了 `source_width/height`。
- **`control_status` 报焦点**：新增 `foreground_hwnd` / `foreground_title` / `focus_hwnd` /
  `focus_class` / `focus_process` / `focus_pid` / `focus_source`。所有"点了没反应"的第一现场不用再写
  `GetGUIThreadInfo`。

### 窗口信息

- **0×0 边界兜底**：`list_windows` / `get_window_info` 以前对 SmartScreen 这类窗口返回 `width:0,height:0`。
  现在依次尝试 `GetWindowRect` → DWM 扩展边框 → 客户区矩形，并在 `bounds_source` 里注明来源。
- **新增 `client` 与 `dpi`**：窗口客户区矩形 + 每窗口 DPI 与缩放比，坐标换算不用再猜。

### 验证

- 回归：**870 项 / 0 失败 / 0 错误 / 3 跳过**（新增 13 项）
- 真机：截图 → frame_id → 按图片坐标点击；按住 W 300ms；`control_status` 焦点归属

## [1.4.1-rc4] - 2026-11-08

> 修 RC3 审计的 D01–D06，并补做真机验证。仍然不新增工具。

### 语义修复

- **UIA 报错不再等于元素消失**（D01）：`absent` 复检要求 `ui_find` 返回 `ok=True` 且 `found==0`；
  查询本身失败时返回 `executed_unverified`。
- **只有 query 的 `absent` 现在可用**（D02）：没有 `ref` 时直接按名字查询；
  以前这条路径永远等到超时。
- **焦点拿不到就不打字**（D03）：`type_verified` 与 `execute_verified(action="type")` 会先确认焦点；
  `SetFocus` 失败且控件当前没有焦点时返回 `focus_failed`，键盘调用次数为 0。
- **跳过动作不再伪装成动作成功**（D04）：`observe_only` 路径返回
  `status="verified_absent"` + `action_executed=false` + `observation_only=true`。
- **滚动计数如实**（D05）：分别返回 `wheel_scrolls` 与 `uia_scrolls`，`scrolls` 只统计真实滚轮事件；
  UIA 滚动成功后加一次短暂等待。
- **长文本截断覆盖全部返回**（D06）：`element_action` 的 `after`、`execute_verified` 的 `before`
  现在也经过 `_trim_state()`。

### 真机验证（Windows 11，本版 wheel）

本轮第一次在真实桌面上走完整链路，覆盖：元素状态读取、焦点校验后输入、窗口移动后的引用解析、
`set_value` 的真实结果、OCR 融合候选。结果见 `docs/v1.4/RELEASE-v1.4.1rc4.md`。

### 验证

- 回归：**857 项 / 0 失败 / 0 错误 / 3 跳过**（新增 9 项，覆盖 D01–D06）

## [1.4.1-rc3] - 2026-11-08

> 修 RC2 的引用完整性与目标解析问题。仍然不新增工具。

### 元素引用（C01/C02/C03/C07）

- **AutomationId 不再拿错东西比较**：`_norm_cand()` 保留 `automation_id`；重定位只在
  「保存时有 AutomationId 且当前也有」时才比较，不再用几何哈希 `element_id` 去比 UIA 的 AutomationId
  （那会把有效引用判成 stale）。
- **窗口移动后重算点击中心**：以前 `setdefault('cx')` 保留旧中心，导致"窗口挪了 → 引用还在 → 点不到"。
  现在每次重定位都按新矩形计算。
- **不传 hwnd 也能拿到引用**：`find_element()` 在只有 query 时会解析前台窗口并据此生成快照，
  不再出现"找到了目标却没有 ref"。
- **快照寿命取最长引用**：混合 UIA/OCR 结果的快照整体 TTL 以前取 5 秒，会让 120 秒的 UIA 引用被
  新查询提前清掉；现在快照按最长期限保存，每个引用按自己的 TTL 判断有效性。

### 目标解析与执行验证（C04/C05/C06）

- **引用失效 ≠ 元素消失**：`execute_verified(expect.kind="absent")` 在引用失效后会按名字重新查询，
  只有确认查不到才返回 `verified_success`，否则 `executed_unverified`。
- **指定目标却定位失败时不再打字**：`type_verified(name=...)` / `execute_verified(action="type", query=...)`
  在目标无法解析时返回 `no_target`，**不发送任何按键**；只有自由输入（不指定目标）才沿用旧行为。
- **同名控件规则统一**：四个元素工具共用一个 `_resolve_element()`，两个同名候选一律返回 `ambiguous`，
  不再出现"element_action 会拒绝、execute_verified 却默默选第一个"。

### 滚动（C08）

- **ScrollIntoView 成功后不再补轮滚轮**：以前 UIA 已经把目标滚进视野，紧接着又发一次滚轮，
  可能把它滚出去。现在只有 Pattern 失败或不可用时才用滚轮。

### 验证

- 回归：**848 项 / 0 失败 / 0 错误 / 3 跳过**（新增 10 项针对 C01–C08）
- 每个修复都有对应回归：AutomationId 不误判、窗口移动后的中心、无 hwnd 取引用、混合快照不提前清理、
  引用失效不假成功、缺目标不打字、同名歧义统一、ScrollIntoView 后不补滚

## [1.4.1-rc2] - 2026-11-08

> 修 RC1 审计提出的问题。**不新增工具**，只把已有六个的语义对齐。

### 发布阻断项

- **UIA 动作不再假装成功**：`Invoke` / `Toggle` / `Select` / `SetFocus` / `ScrollIntoView` 抛异常时，
  `element_ops.perform()` 现在返回 `ok=False` 并带上异常类型；以前一律 `ok=True`。
- **`SetValue` 用对方法**：改用 `ValuePattern.SetValue()`（原来写的是属性赋值），写入后读回校验，
  只读控件直接拒绝。
- **融合定位不再丢结构**：`_norm_cand()` 保留 `path` / `name` / `type` / `element_id`；
  以前 UIA 候选经过融合就退化成 5 秒视觉引用。
- **混合批次按节点判定**：`snapshots.attach()` 每个候选单独给 TTL，一个 OCR 候选不会拖累整个结果。

### 主要功能问题

- **`wait_for(any=...)` 真正接通**：分发层以前漏传该参数，多条件等待退化成默认的屏幕变化等待；
  新增经过完整分发层的回归测试。
- **`type_verified(clear_first=true)` 只输入一次**：顺序改为「聚焦 → 全选 → 删除 → 输入 → 回读」。
- **`absent` 不再假成功**：没有引用可观察时返回 `executed_unverified`，不再把解析失败当成元素消失。
- **同名控件不再瞎选**：`element_action` / `execute_verified` 按名定位遇到多个同名候选时返回
  `code: "ambiguous"` 并列出候选，不再默默取第一个。
- **无 `hwnd` 时补前台窗口**：按名定位会显式解析前台窗口，不再丢失窗口上下文。
- **输入验证更严**：值完全没变时判 `no_effect`（即使原文已包含目标文本）。
- **引用身份增加 AutomationId**：列表重排后同一路径换了控件，会报 `stale_element` 而不是点到别的东西。

### 细节

- **同分候选改为优先小控件**：以前平局时选面积大的（与注释意图相反）。
- **`scroll_into_view` 不再多滚一次**：最后一次检查失败后不再发送滚轮事件。
- **长文本默认摘要**：`element_state` 与 `type_verified` 默认只回 `value_length` + 首 200 字符，
  需要全文时用 `full=true`。
- **版本号对齐**：包版本从 `1.4.1` 改为 `1.4.1rc2`，与 tag 一致。

## [1.4.1] - 2026-11-08

> 功能增强版。授权模型不变（连接即授权 + 急停 + 接管），补的是**定位准不准、输入有没有真的进去、一次调用能干多少事**。

### 新增工具（6 个，90 → 96）

| 工具 | 解决什么 |
|---|---|
| `find_elements_ranked` | 多来源融合定位：UIA/OCR/模板一起看，输出排序、置信度、`ambiguous` |
| `element_state` | 直接读控件的 enabled/offscreen/focus/value/toggle/selected，不用截图猜 |
| `element_action` | 按控件能力执行 invoke/set_value/toggle/select/click，可选回读校验 |
| `type_verified` | 输入后回读目标控件，丢字/焦点错位会被判 `no_effect` |
| `execute_verified` | 定位 → 执行 → 等后置条件 → `verified_success`/`no_effect`/`target_changed` |
| `scroll_into_view` | 长列表滚到目标可见；先试 UIA ScrollItem，再滚轮，找不到就明说 |

### 现有工具升级

- **元素引用可重新解析**：UIA 候选带子控件索引路径，解析时重走树取**当前**坐标；
  窗口移动不再让引用失效，附着也不再截图。OCR/模板候选保留原来的短 TTL（它们没有结构可复位）。
- **`find_element` 不再先命中先返回**：便宜的 UIA 先跑，缺失或有歧义才跑 OCR/模板；
  两个候选分差 < 0.1 直接标 `ambiguous`。置信度按来源校准，**不相加**。
- **`screenshot` 支持 `region` / `regions=[...]`**：一次调用截多块，每块一张图。
- **`ocr_read` 支持 `regions=[...]`**：一次 OCR 多区域，返回每块的文本和错误。
- **`wait_for` 支持 `any=[...]`**：多个条件任一满足即返回，超时会列出试过哪些。
- **`ui_tree` 节点带 `path`**，新增 `control_at_path()` 按路径复读控件。

### 工程

- `tools/snapshot_tools.py`：契约快照（`docs/tools-snapshot.json`）由注册表重新生成，
  不再手改；`--check` 用于 CI 前的漂移检查。
- 发布门禁的工具数量改为**从注册表读取**，不再写死 90。

### 验证

- 回归：**822 项 / 0 失败 / 0 错误 / 3 跳过**（新增 49 项）
- 真机：微信定位联系人 → 读控件状态 → 输入草稿 → 校验未发送

## [1.4.0] - 2026-11-07

> 正式版。授权系统已经移除，急停与接管保留；旧的 32 项授权基准测试随之删除。

### 相对 rc2 的修复（第二轮审计）

- **`policy enable` 不再等价于恢复**：以前它会顺手写新的授权时间，等于把急停顶掉；现在只改模式。
- **恢复与急停的竞争**：`resume()` 不再删除急停闩，也不再依赖"我的时间戳更新"这种同刻度会失效的比较；
  恢复前记录闩的文件指纹，恢复期间出现新急停就抛错并保持停止。
- **非法授权时间不再被采信**：NaN / ±inf / 负数 / 未来 5 分钟以上的时间一律视为无授权；
  已有记录但时间不可用时不再"自动修复"，只能显式 resume。
- **`policy disable` 明确报告是否生效**：被环境变量覆盖时返回码 3 并给出 warning，不再假装成功。
- **headless 下人工接管不再被时间戳夺回**：接管判定里的"授权比用户输入新"分支只对旧的人工授权模式生效。
- **进程终止收紧**：`exit_app` 默认 `force=False`、按进程名精确匹配、终止前复核创建时间；
  宏里的 `exit_app` 默认改为不强制结束。
- **撤销后仍可用**：强制退出接受通配授权（上一轮遗留的死角）。
- **诊断不再谎报**：local 模式下 `control_status` 不再查询 consent IPC；急停提示改为
  `python -m computer_mcp.policy resume`，不再指向已被移除的授权窗口。
- **隐私测试修复**：改为检查 args/result/target/labels 等可能承载用户数据的字段，
  不再让随机 48 位会话 ID 被误判成银行卡号（这就是之前偶发失败的根因）。

### 删除

- 32 项桌面验收基准（`docs/v1.3/DESKTOP-BENCHMARKS.md`、`tools/desktop_acceptance.py`、
  `tools/acceptance_report.py`、`tests/manual/fixture_app.ps1`、`cover_window.ps1`、证据目录）——
  这套东西是为人工授权流程设计的，授权流程已经不存在。
- `tools/release_gate.py` 重写为轻量发布门禁：版本一致、回归绑定提交且全绿、
  stdio/http 都是 90 工具且版本一致、HTTP 无凭证必须 401。旧门禁里
  `continue-on-error` 掩盖失败的问题一并修掉：被拦下的正式 tag 现在会让工作流红。

### 结果

- 回归：**773 项 / 0 失败 / 0 错误 / 3 跳过**
- 发布门禁本地实测通过（版本 / 提交绑定 / 90 工具 / 401）

## [1.4.0-rc2] - 2026-11-07

> 发布候选第 2 版，修的是 RC1 审计提出的问题。目标不变：免人工授权，但急停与接管必须可靠。

### 安全阻断项（P0）

- **急停不再被"策略文件丢失"绕过**：`authorized_at()` 以前在记录缺失/损坏时会新建一条以当前时间授权的记录，
  而急停判定正是比较这个时间——删掉文件就等于取消急停。现在只要急停闩存在，就**不会凭空生成授权**，
  记录缺失/损坏一律按"未授权"处理。新增 4 项回归（删记录、改坏记录、全新安装、运行时状态）。
- **安装/升级/回滚不再恢复控制**：`tools/install.ps1` 两处 `policy.resume()` 改为 `policy.ensure_initialised()`——
  只在"没有记录且没有急停"的全新安装里创建记录，已有记录或已急停时**什么都不做**。
- **`policy disable` 真的生效**：`mode()` 现在按「环境变量 → 记录里的 mode → 默认 local」解析，
  以前 CLI 只写记录、运行模式根本不看它。新增 2 项测试（disable/enable 后真实输入被拒/放行）。

### 可靠性（P1）

- **不再跨客户端复用会话身份**：`state()` 以前整份缓存，包含 `agent_session.current()`；HTTP 多凭证时
  客户端 B 可能拿到 A 的会话而被 `check_scope` 拒绝。现在只缓存"文件事实"（授权时间、急停是否存在），
  授权负载每次按调用方重新构建。新增 2 项会话隔离测试。
- **写入失败不再假装成功**：`_save()` 以前 8 次重试后直接 `return payload`。现在写后回读校验，
  失败抛 `OSError`；进程内写入用锁串行，跨进程靠 12 次退避重试。新增 2 项失败注入测试。
- **`resume()` 显式清除急停闩**：不再依赖"我的时间戳比停止时间新"（同一时钟刻度内会失败），
  恢复就是你按下恢复这个动作本身。

### 兼容性（P2）

- **强制退出适配通配授权**：`appkit.exit_app(force=True)` 以前要求进程记录精确出现在 `applications` 里，
  本地模式给的是 `['*']`，导致强制结束永远跳过。现在通配也放行。新增 1 项测试。

### 审计未采纳的建议

- 没有重新引入"控制权/授权代际"这类额外权限机制。RC2 只修 bug，不改变授权模型：
  连接即授权 + 急停 + 接管 + 目标窗口校验。
- 审计提到的"持久停止代际"没有单独实现：急停闩的时间戳 + `resume()` 显式清除已经覆盖该语义，
  再加一层代际只会让状态更难解释。

### 结果

- 回归：**762 项 / 0 失败 / 0 错误 / 3 跳过**（新增 14 项审计整改测试）
- 审计提交：`8c0de31`（RC1）

## [1.4.0-rc1] - 2026-11-07

> 发布候选版本（RC）。正式版要等 32 项真机验收在发布提交上签收后再发。
> 安装即生效：默认本地执行策略，没有授权窗口、没有托盘、没有热键；需要旧流程时设 `ICON_CONTROL_POLICY=human`。

- **架构：默认改为本地执行策略（headless）。** 工具调用不再需要人工授权窗口、授权桥心跳、scope 租约或 30 天信任记录；是否允许执行由「已连接的 MCP 会话 + 执行保护」决定。详见 `docs/v1.4/HEADLESS.md`。
- 新增 `_patched/policy.py`：`LocalExecutionPolicy`，提供 `state()` / `runtime_state()` / `resume()`；授权时刻记录在 `state/local-policy.json`。
- `permission.status()` 在本地模式下直接返回策略状态；`_request_consent()` 不再弹窗。
- `capabilities.require_launch()` 与 `workspace.readable_path()` 支持通配授权 —— 修复了两个既有死角：**信任模式下无法启动程序、无法读取外部文件**。
- `launcher.py` / `mcp.run_stdio()` 本地模式不再拉起授权桥与托盘宿主，桥缺失不再影响工具调用。
- `control_status` 增加 `policy: {mode, runtime}`，运行时状态为 `ready / user_takeover / stopped / error`。
- `tools/install.ps1` 安装与回滚不再无条件写急停闩；本地模式写策略记录。升级后无需重新授权。
- 保留人工授权模式：`ICON_CONTROL_POLICY=human`，行为与 1.3.9 一致；`tools/verify.py` 默认用它跑旧回归。
- 新增 `tests/test_v140_headless.py`（14 项）与 `tools/smoke_headless.py`（无桥冒烟）。
- 回归：**735 项 / 0 失败 / 0 错误 / 3 跳过**。

## [1.3.9-beta.11] - 2026-11-06

- **修复：授权面板永久显示「无法连接授权桥」**。宿主通常比桥先启动（后台宿主由 launcher 拉起，桥稍后就绪），启动同步失败后，面板打开时只试一次就放弃，于是整个宿主生命周期里热键/托盘都只能弹「授权状态未知」。
  - 面板打开时改为重试同步（4 次、间隔 0.5 秒）；桥稍后就绪即可正常显示授权状态与按钮。
  - 新增测试：重试到成功、用尽次数后放弃、首次成功不额外等待。
- 全量 721 项通过（22 项 consent 测试）。

## [1.3.9-beta.10] - 2026-11-06

- **修正撤销语义**：桥在 startup / shutdown 写入的否定状态属于「租约结束」，不是用户撤销。信任校验现在会看该状态的 `origin`：来自 startup/shutdown 的撤销不再否定信任（来自用户动作的撤销、急停仍然否定）。
  - 这条同时修掉了 b8/b9 之前遗留的“代际被启动/退出推进”对既有信任记录的影响，无需重新授权。
- 全量 718 项通过。

## [1.3.9-beta.9] - 2026-11-06

- **修复：桥每次启动/退出都推进撤销代际**。`permission_bridge` 在 start/shutdown 时用 `event='action'` 写了否定状态，而代际只应因**用户动作**推进——于是每重启一次助手，30 天信任就被判“撤销更晚”作废。
  - 启动/退出改为 `event='hb'`（心跳语义）：状态仍然立即变为未授权，但不动代际。
  - 至此撤销代际只由三种情况推进：用户点「立即撤销」、急停、桥的显式 revoke 请求。
- 全量 718 项通过。

## [1.3.9-beta.8] - 2026-11-06

- **修复：宿主重启会推进撤销代际，从而废掉 30 天信任**。b6 只解决了“退出清信任”，但退出仍走 `revoke`，代际 +1，下一次 `validate()` 就判定“撤销晚于信任”。
  - 退出改为发送**否定心跳**（`_release_lease()`）：会话租约立即失效，但不动撤销代际；只有「立即撤销」按钮才推进代际并清信任。
  - 新增回归用例：退出发负心跳、不清信任、不改代际。
- 全量 718 项通过。

## [1.3.9-beta.7] - 2026-11-06

- **修复：同一安装的不同进程算出不同的信任主体**。原来主体里包含 `workspace_identity()`，而它取自进程 cwd —— MCP 服务进程与 CLI 的 cwd 不同，于是在 CLI 里点「信任 30 天」，服务进程却不认。
  - 主体改为 **安装目录 + 工具指纹 + 主机名**（与调用方 cwd 无关）；`workspace` 仅作展示字段。
  - 对已经签发的旧记录做**一次性迁移**（`schema 1 → 2`）：只校验签名、工具指纹、未撤销、未过期，保留原授权时间与到期时间，不扩大任何权限。迁移只发生一次，之后主体变化仍会正常失效。
- 全量 717 项通过。

## [1.3.9-beta.6] - 2026-11-06

- **修复：授权宿主退出会清掉 30 天信任**。原来 `run()` 退出时调用 `revoke()`，而 `revoke()` 会连带撤销信任记录——意味着页面刷新、MCP 重连或进程重启都会把用户刚点过的「信任 30 天」抹掉。
  - 现在宿主退出只撤销**会话租约**（`_revoke_state()`）；只有「立即撤销」按钮才同时清信任。
  - 新增回归用例：按钮撤销会清信任；退出撤销不清信任。
- 全量 717 项通过。

## [1.3.9-beta.5] - 2026-11-06

- **修复：撤销后建立的信任不生效**。真机验收发现：桥在磁盘上保留的“已撤销”状态会让 `status()` 直接返回 `permission_revoked`，根本不去看之后建立的信任记录——表现为“刚点了信任 30 天，工具仍然报未授权”。
  - 现在先查信任记录（信任会按代际与授权时间判断自己是否晚于撤销），再回答 `permission_revoked`。
  - 新增回归用例：撤销之后授权信任 → 必须生效；信任之后撤销 → 必须拒绝。
- 全量 715 项通过。

## [1.3.9-beta.4] - 2026-11-06

- **帧失效判定**：截图会记录目标窗口的矩形与 DPI；`to_physical()` 在使用前复核，窗口被移动、改尺寸、DPI 变化或已关闭 → 直接拒绝该 `frame_id`（"stale frame_id; the target window moved or resized"）。截图时若几何未知，则不做误判。
- `double_click` 接受 `frame_id` + `x/y`（图像坐标）；`drag` 接受 `frame_id`，起止点都按图像坐标换算。
- `screen_state` 返回最新可用帧的 `frame_id`，让"看一眼 → 点一下"可以串成一次调用。
- 快照 `docs/tools-snapshot.json` 同步 `click/double_click/drag` 三条；工具总数仍 90。
- 新增测试到 `tests/test_v139_frames.py`（共 22 项）：窗口移动/DPI 变化/窗口关闭失效、几何未知不误判、双击与拖拽换算、`screen_state` 帧号。全量 713 项通过。

## [1.3.9-beta.3] - 2026-11-06

- **坐标契约（PR-1 第一步）**：`screenshot` 现在返回 `frame_id`、`source_rect`（物理屏幕区域，支持副屏负坐标）、`image_size`、`dpi`、`hwnd`，并保留原有 `width/height/scale`。
- `click` 新增可选 `frame_id`：给了它，`x/y` 就被解释为**该帧的图像坐标**，由服务端换算成物理像素；不给则维持旧的物理坐标语义（兼容）。
- `to_physical()` 校验：未知帧、超过 15 秒的陈旧帧、落在帧外的点一律 `ValueError`（上层映射为 `invalid_argument`）。
- 帧登记表有上限（32 帧）并按 TTL 清理，不会无限增长。
- `docs/tools-snapshot.json` 同步 `click` 的新描述与 schema；工具总数仍为 90。
- 新增测试 `tests/test_v139_frames.py`（11 项）：几何换算、全屏负坐标、未知/陈旧帧、越界点、登记表上限、捕获返回字段、click 换算与拒绝路径。全量 702 项通过。

## [1.3.9-beta.2] - 2026-11-06

- **撤销代际**（`revocation_generation`）：桥每收到一次显式撤销就 +1，并随状态文件持久化；桥重启后从文件恢复，不会把老租约“复活”。
- 状态文件新增 `revocation_generation` / `revoked_at`；`permission.status()` 对撤销后的状态返回 `code='permission_revoked'`（未授权但未撤销返回 `permission_denied`）。
- `execution.authority_stamp()` 与 `check()` 的取消判据加入代际：运行中的宏在下一次边界检查就会被中止，而不是只看会话/修订号。
- **撤销压过信任**：`trust.validate()` 会比较桥的代际与信任记录里记录的代际；桥的代际更高即判定信任失效（旧记录无代际时回退到时间比较，避免同一时钟刻度下的误判）。
- **撤销即停**：`execution.authority_stamp()` 在判定撤销或接管时先释放所有按住的键鼠（`input_guard.release_all()`），再抛 `PermissionDenied`。
- 授权窗口新增「信任此助手 30 天」按钮（`ask_status` 第三个按钮）；「立即撤销」会**同时撤销会话授权与 30 天信任**，一次点击不留残留。
- 新增测试 `tests/test_v139_revocation.py`（9 项）：代际单调、持久化、状态块、执行戳取消、信任被撤销压制。
- 本地全量 689 项中 2 项因“用户正在动鼠标”被控制权守卫拦截（环境相关，非回归）；CI 仍为权威全量结果。

## [1.3.9-beta] - 2026-11-06

- 新增 **30 天信任**（`computer_mcp/trust.py`）：用户点一次「信任 30 天」后，同一安装、同一工作区、同一工具指纹的助手不再每次重授。
  - 信任记录用安装令牌 HMAC 签名（`security.signature`），存在 `state/desktop-trust.json`，原子写入；
  - 主体指纹 = `workspace_id + tools_sha256 + 主机名`：**升级助手（工具指纹变）、换工作区、换主机都会失效并要求重新授权**；
  - 信任不是授权：`permission.status()` 仍然每次调用都跑，信任只提供一个 15 分钟的短租约，来源标记为 `source='trust'`；
  - 撤销（`trust.revoke()`）与急停（`emergency-stop.json` 晚于授权时间）都会压过信任；
  - 全局目标策略：信任授权带 `applications=['*']`，但仍保留目标身份校验，且**权限 UI 永不可被自动化**；
  - 一次性授权只能经原生弹窗 `native_dialog.ask_trust()` 触发：`trust.grant()` 必须拿到确认回调，CLI `python -m computer_mcp.trust grant|revoke|status` 也只在弹窗返回 True 后写入。
- 工具指纹在进程内缓存，避免 `status()` 热路径重复哈希全部工具 schema。
- 新增测试 `tests/test_v139_trust.py`（20 项）：签名/篡改、过期、撤销、主体变化、急停优先、CLI 拒绝路径、通配目标与权限 UI 排除。全量 680 项通过。

## [1.3.9-alpha] - 2026-11-06

- 授权宿主新增 `--intent=background|show`（默认 background）。安装、重启、MCP 重连后的宿主只常驻托盘与续期，**不再自动弹窗**；只有用户主动（托盘、热键、`icon-control://`、需要批准的调用）才 `show`。
- 单实例 mutex 命中时，后台意图不再向已有窗口发送 `WM_SHOW`，因此刷新页面/重连不会把授权窗顶到前台；后台启动只刷新托盘与 `consent-host.json`（新增 `intent`、`last_sync_ok` 字段）。
- 授权桥不可用时，后台启动**不再弹「无法连接授权桥」模态框**：托盘显示“状态未知”，状态文件记录 `last_sync_ok=false`，工具侧返回 `authority_unavailable`。
- 修复 `DefWindowProcW` 未声明原型导致的 `OverflowError: int too long to convert`（64 位 lParam 消息会让 ctypes 回调反复抛异常）。
- 授权桥 `/status` 增加只读 `health` 字段（pid/transport/clients/revision/lease/uptime），供 doctor 与工具诊断；不新增写入路径。
- 工具拒绝结果新增机器可读 `code`（`authority_unavailable` / `permission_denied` / `permission_revoked` / `invalid_argument` / `internal_error` 等），权限闸门异常按类型分类，不再一律报「未授权」。
- `key_press` 支持 `ctrl+f`、`ctrl+shift+f` 形式的组合键（修饰键先按、逆序释放）；`key_down`/`key_up` 明确拒绝组合键并返回 `invalid_argument`；`batch` 内的 `key_down`/`key_up` 步骤给出明确提示而不是报成权限问题。
- 新增测试：`test_v139_consent_intent.py`、`test_v139_error_codes.py`、`test_v139_gate_codes.py`、`test_v139_key_chords.py`；全量 660 项通过（3 项跳过）。

## [1.3.8] - 2026-11-05

- PR #8 审计整改：统一包内工具名称清单供安装/协议验证使用；修正旧测试契约、必填宏参数声明和窗口夹具。
- guarded_click 强制正向页面身份特征、完整文字匹配及合理模板阈值，拒绝零/非法阈值和无 OCR 证据；明确绑定顶层 HWND，并在实际按钮按下前检查同 PID 遮挡。
- 独立滚动定位与事件检查 scroll 自身权限。以上均为代码修改及未执行的回归用例定义。

- 新增运行进程版本/工具契约指纹及 click schema 诊断；构建时嵌入源码 SHA/dirty 元数据，未知来源明确报告 null，不把独立解释器结果冒充 DSH 运行状态。
- 没有可信目标时强制人工选择应用（包括单候选），不默认勾选首项，过滤工具/不激活覆盖层。
- 输入结果提供长度、UTF-16 单元数、直引号计数及哈希，保留 executed_unverified 并提示核对草稿。点击与滚动也明确区分事件提交和应用结果。
- 新增 scroll，保留原 89 个工具（总数 90），支持限定幅度、可选坐标及注入前目标复核。
- 新增 guarded_click 页面前后条件及微信朋友圈示例；条件失败停止、单步不自动重试，OCR 错误不得被当作文字不存在的证据。
- 修正技能文档、微信启动方法、收尾与精确会话授权说明。
- 修复阶段按用户要求未执行测试、验收或构建；用户随后明确批准合并 PR #8 并发布 v1.3.8 正式版。发布阶段仅打包，未额外运行验证，也未补造验收记录。

## [1.3.7] - 2026-11-05

- 第五轮整改：剪贴板快捷键统一归一化字符、VK 字母键及左右修饰键，数字 Ctrl+V/C/X 不再绕过独立剪贴板权限；同一键对象同时携带 char/VK 时合并所需权限。
- 窗口输入测试补齐模拟线程/PID/进程创建时间/路径，并隔离缓存控制器；新增 VK 拒绝注入和窗口生命周期变化的回归用例代码，未运行。

- 正常 key_up/button_up 重新检查授权与目标；仅 cleanup 对实际持有输入绕过授权。指定窗口控制器绑定 PID、进程创建时间、路径和窗口线程，失效句柄不再接收清理消息。
- 复制/剪切快捷键要求 clipboard_write，粘贴要求 clipboard_read；覆盖标准 Edit 消息、SendInput 回退和窗口键盘控制器，兼容 Ctrl+Insert / Shift+Insert / Shift+Delete。
- Release 工作流遇到非零测试退出码立即终止，并核对新生成报告的字段、源码 SHA、完整测试范围和干净源码状态。
- WM_CLOSE 请求已提交与窗口已关闭分开返回，未确认关闭时报告 executed_unverified。
- verify_flow 按完整验证计划声明 screen_read/file_read/report file_write，直接 Python 调用也在执行前检查。
- 本轮修复阶段未执行测试、CI 核查或桌面验证；用户完成审计后明确批准发布 v1.3.7 正式版。发布时未另行运行验证。

## [1.3.7rc3] - 2026-11-04

- 后续整改：旧自动授权测试按 IPC 命令分别模拟 open/request_status，并断言窗口仅打开一次且查询绑定实际会话。
- 新增缓存复用/终态替换、调用者隔离、异常通知保持打开时否定心跳不被锁阻塞的测试定义。本轮未执行测试或其他验证。

- 授权与撤销异常通知在状态锁释放后显示，避免模态窗口阻塞否定心跳。
- 请求缓存复用前由后端核对调用者和请求状态，失效请求重新申请。
- 发布说明缺失时回退到 CHANGELOG；RC 标签始终发布为非 latest 预发布版本。
- 本轮仅修改代码及发布候选包，未运行测试、验证脚本或桌面验收；验证由用户执行。

## [1.3.7rc2] - 2026-11-04

- 执行点发现实际目标应用未获批准时，为当前调用者生成补授权请求。
- 宏 paste 包括旧剪贴板保存/恢复的读取路径明确要求 clipboard_read。
- 即时回收授权队列终态记录，活跃重复请求去重并保持原到期时间，限制单会话占用。
- 工作区摘要固定在首次签名注册，同进程 chdir 不再改变授权身份。
- 原生授权增加操作 ID、回读确认和取消记录，迟到授权不得覆盖已取消操作。
- 心跳网络操作与界面状态分离，UI 线程按本地代际处理结果。
- 迁移旧测试的会话注册、缓存类型和跨会话租约断言，并更新两个变更 API 的快照；新增请求与异常路径的测试定义。
- 本轮按用户要求不执行测试、验证脚本或桌面操作；RC2 为待用户检测的预发布代码。

## [1.3.7rc1] - 2026-11-04

- 使用带 request_id、TTL、签名、实际连接方和生命周期的独立授权请求，替代全局待授权字段。
- 移除“找不到请求方就选择最新会话”及“同 cwd 共用许可”的回退路径。
- 补授权优先核对会话、应用和权限，提供本次所需权限选项与待请求处理入口。
- 错误窗口仅展示通知；撤销失败和通信中断显示状态未知并停止正向续期。
- control_status 提供实际调用者诊断，验收预检不再新建 Python 会话冒充 DSH。
- click 支持可选坐标对，并在注入前固定与复核目标进程。
- 按用户指示，本次仅交付代码，未执行测试、真机操作或发布验收。

## [1.3.6] - 2026-11-04

- 修复：同时开出多个授权窗口。单实例互斥体的错误码用 kernel32.GetLastError() 读，值已被封送冲掉，每个宿主都以为自己是第一个；改用 ctypes.get_last_error() 并给 show() 加重入保护。
- 修复：授权窗口打开时心跳会停（WM_TIMER 被模态对话框阻塞），状态 15 秒变旧导致后续调用被判未授权；心跳改到后台线程。
- 修复：窗口显示前先向桥核对真实状态，撤销后不再显示「已授权」。
- 验收工具链：新增 tools/acceptance_run.py（七项前置检查 + 失败分类 harness/product + --repeat 抖动检测）；证据与 acceptance.json 改为运行产物不进 git；修正 B22 遮挡窗口过大、B28 依赖滚轮落点的问题。
- 修复：test_independent_review 读 pid 文件的空内容竞态。
- 回归：550 项运行 / 0 失败 / 0 错误 / 3 跳过；真机 S5 15 项全过（提交 494b4e5e）。

## [1.3.5] - 2026-11-04

- 授权窗口会说出缺什么：被拦下的调用把缺失作用域带到窗口，标题下直接写“本次调用需要：file_write”，并自动预选能覆盖它的最小预设（只读 / 常用 / 全部）。
- 新增 tools/acceptance_report.py：acceptance.json 的唯一生成入口，按 SHA 绑定与哈希校验组装证据，跨提交的旧证据会标 stale。
- 新增 S5 用例 B22（遮挡）与 tests/manual/cover_window.ps1。
- 回归：550 项运行 / 0 失败 / 0 错误 / 3 跳过（新增 4 项预设选择用例）。

## [1.3.4] - 2026-11-04

- 被拒的调用会自动拉起授权窗口：permission.check_tool 在缺少授权或权限范围不足时请求 open，20 秒内只弹一次，可用 ICON_CONTROL_AUTO_CONSENT=0 关闭。
- 未授权提示改为可操作文案（按 Ctrl+Alt+Shift+F9 或点托盘），不再指向已删除的旧开关。
- 回归：546 项运行 / 0 失败 / 0 错误 / 3 跳过（新增 2 项自动弹窗用例）。

## [1.3.3] - 2026-11-04

- 托盘点击改为直接打开授权窗口：TrackPopupMenu 在后台隐藏窗口上弹不出来，改为窗口内撤销/续期/退出。
- 租约到期由客户端自己判定（permission.status 检查 lease_expires_at），桥崩溃也不会延长租约。
- 宿主启动即写 state/consent-host.json（pid / 热键 / 托盘状态），便于排障。
- 新增 CONSENT-USAGE.md 用户指南与 AUDIT-1.3.2.md 实现记录。
- 回归：544 项运行 / 0 失败 / 0 错误 / 3 跳过。

## [1.3.2] - 2026-11-04

单窗口授权：一次点击、一小时租约、不再"点完授权先被冻 10 秒"。

- 新增原生授权窗口（`comctl32!TaskDialogIndirect`）：三档预设（常用/只读/全部）+「60 分钟内本工作区自动沿用」+ 一键授权，默认回车即批准。
- 新增身份级租约：授权主体从进程会话扩展为「安装目录 + 工作区」派生的 `agent_id`，同一身份在 60 分钟内新起进程自动继承，不再重复弹窗。
- 修复"授权即被接管"：授权时间晚于最后一次物理输入时，控制权直接交给 AI，不再出现 `控制权在用户手上（0.0s 前）`。
- 租约到期（默认 60 分钟）与撤销均立即失效；撤销后心跳进程自动退出。
- `consent.main` 默认走原生窗口；`--tk` 仍可打开旧控制中心（仅内部调试入口）。
- 新增托盘常驻与全局热键 `Ctrl+Alt+Shift+F9`（被占用时自动退到 F7 / F12 / G，实际绑定写入 `state/consent-host.json`）；托盘菜单：打开授权 / 立即撤销 / 退出。
- 移除 DSH 胶囊：`plugin/client.js` 不再渲染任何按钮，`quick_grant.py` 与 `quick_bind/quick_preview/quick_grant` 三条 IPC 删除，授权窗口也不再提供「高级…」入口。
- 回归：540 项运行 / 0 失败 / 0 错误 / 3 跳过；新增 13 项租约、交接与宿主分发用例。

## [1.3.1] - 2026-11-04

安全修补版，对应独立审计 v1.3.0 的 P0 与 P1 项。

- 修复快捷授权身份漂移：保存的 Agent 退出后，即使它是唯一在线会话也不再沿用旧目标，必须重新绑定（P1-01）。
- 新增 `clipboard_read` 作用域：宏里的 `clipboard_get` / `assert_clipboard` 不能再凭 `text_entry` 读取系统剪贴板；执行日志与错误只记录长度与是否匹配，不回显内容（P1-02）。
- 新增 `clipboard_write` 作用域：`clipboard_set` 与带文本的 `paste` 需要显式授权；内部临时粘贴在剪贴板未被其他程序改写时恢复原内容（P1-03）。
- 一键授权界面写明"读取整个桌面（含未授权窗口）"，并补上剪贴板读写两项的人类可读说明（P1-04）。
- `capture_daemon` 不再声明未使用的 `file_write`，只要求 `screen_read`（P2-01）。
- 发布流程接入 Release Gate：正式版必须通过 `tools/release_gate.py` 的 SHA 绑定证据校验，未通过时只能发布预发布版（P0）。
- 回归：536 项运行、0 失败、0 错误、3 跳过；89 个 MCP 工具与 stdio/HTTP 协议自检不变。
- 真机验收（DESKTOP-BENCHMARKS 32 项）仍未签收，`docs/v1.3/acceptance.json` 保持 `blocked`。

## [1.3.0] - 2026-11-04

- Windows 原生一键授权胶囊，按 Agent 会话、能力和应用进程身份授权，常用模式授予屏幕读取、鼠标与文字输入。
- 组合操作按真实动作检查权限，文件读取、输出、删除及训练数据按范围与所有者隔离。
- 物理鼠标连续移动满 1 秒接管，点击、键盘、滚轮与双 ESC 保持即时停止与持键释放。
- 修复中文输入法改写文字，统一 Unicode 注入并核对实际注入计数，标准编辑控件支持明确的全选、复制、剪切和粘贴。
- 保留 89 个 MCP 工具及旧别名，提供 wheel/sdist、安装回滚与认证 MCP stdio/HTTP。
- 基于 c841bf5 发布。用户提交第二轮中文输入法真机冒烟 3/3 通过报告，并明确批准正式发布。该报告列出的其他验收项目仍保留原始记录。

## [1.3.0rc2] - 2026-11-03

本轮安全整改仍沿用 RC2，未发布新的 RC 或正式版：

- 原生权限中心按 Agent、能力和具体应用授权；渲染端没有长期密钥，撤销、断线及过期均不能由心跳重新授权。
- 限制文件输出、清理和急停进程范围；训练及错误脱敏；录像、缓存和轨迹按屏幕权限及会话隔离。
- 修复独立复审发现的 14 项执行路径缺陷；稳定画面验证必须有健康且新鲜的采集证据，发布闸门核对原始单项执行结果。
- 保留旧证据但重新开始本轮桌面验收；干净 Windows 账号尚未提供，正式发布条件未满足。详见 docs/v1.3/SECURITY-REMEDIATION.md。

以下为 3a0b8dab 的历史 RC2 记录：

- 按用户要求，真人鼠标连续移动满一秒才接管；短挪不累加，键盘／点击／滚轮／双 ESC 仍立即生效。
- 修复 SetCursorPos 不带注入标记的自我接管，统一 SendInput 及物理像素坐标；已用真实按钮与拖拽复核。
- 权限检查异常无条件阻断；89 项效果声明显式注册并区分纯读参数；授权长期密钥移到请求头。
- 修复客户端热重载和 DSH 后台计时器节流，使用认证网络事件确认心跳，服务器推送不能自行授权或续期。
- 通过现有 run_script 增加滚动指令；409 项回归运行，404 通过、5 明确跳过、零失败。
- 新候选版实测 9 项通过，旧报告冲突和其余发布条件仍待签收，未发布正式版。

## [1.3.0rc1] - 2026-11-02

Icon Control v1.3 稳定性重构候选版，保留 89 个 MCP 工具。未完成 S5，不发布正式 v1.3.0。

- S0：冻结 v1.2.0 / 98b38b4，隔离验证目录，记录工具清单与可复现基线。
- S1：首请求 Token、签名状态、撤销与乱序事件处理、执行点名单和能力检查；物理接管不再被静默窗吞掉；监听失败拒绝；双 ESC 释放持键并跨进程重启保持停止。
- S2：branch 真正执行、photo 保存可验证证据、失败步不计完成；任务与微脚本明确报告未验证、超时和未知指令。
- S3：窗口元素引用绑定进程、窗口、DPI 和内容；保留旧参数并修正同名 UIA 目标索引。
- S4：完整源码 wheel/sdist、独立安装与回滚、官方 SDK stdio/Streamable HTTP、认证与 CI；只读截图和 OCR 不再切前台，定向 Unicode 输入逐事件校验。
- S5：提供 32 项真机任务和正式发布阻断器。独立 P0 复审、物理急停与接管、不同 DPI、干净 Windows 账号验收待完成。

迁移与验证限制见 docs/v1.3/MIGRATION.md、INSTALL.md、VALIDATION.md。

## [1.2.0] - 2026-11-02

**模块化 + 训练数据分区 + 控制权交接：从"能干活"到"能长期干活"。**

工具 79 → **89**，测试 242 → **298**，`mcp.py` 1806 → **190 行**。

---

### 一、结构：1806 行单文件路由 → 7 个分区

原来 `mcp.py` 一个文件里塞着 79 个工具定义（L40–1165）+ 80 个 if/elif 分发分支（L1165–1806）。
任何工具改动都要碰它，是天然的冲突热点。

现在按**决策阶段**切成 7 区（不是按 API 切）：

| 区 | 职责 | 工具 |
|---|---|---|
| Z0 治理 | 授权、控制权、配置、保留 | 4 |
| Z1 采集 | 截图、录屏、守护、模板抓取 | 7 |
| Z2 判据 | OCR、模板、数字、HUD、布局、世界状态、统一寻址、统一等待 | 25 |
| Z3 动作 | 鼠标、键盘、窗口、UIA | 31 |
| Z4 编排 | 脚本、宏、闭环、导航、验证 | 8 |
| Z5 资产 | 宏、模板、基线、字形 | 8 |
| Z6 训练数据 | 采样、查询、提升、导出、分拣、探索 | 6 |

新增：`tool_registry.py`（聚合 + 白黑名单）、`tool_spec.py`、`zones/*/tools.py`、
`zones/dispatch.py`（原 522 行分发链原样搬出）、`zones/aliases.py`（旧名→新名）。

**依赖单向**：Z0 ← 全部入口；Z1→Z2→Z3→Z4；Z5 只被读；**Z6 只被 tee 写，不被运行时读**。

### 二、训练数据分区（新）

每次工具调用被路由层的一个 tee 记成一条 episode（工具 + 脱敏参数 + 结果 + 耗时 + 分区）。

```
dataset/
  schema / writer / redact / query / retention / export / promote / triage / explore
  importers/   base + local_fixture + hf_grounding（外部数据转换框架）
```

- `dataset_status` / `dataset_query` / `dataset_promote` / `dataset_export` / `dataset_triage` / `dataset_explore`
- 失败样本同类 ≥3 次 → `dataset_triage` 自动生成 `cases/*.json` 回归用例（按签名去重）
- `dataset_explore` 随机游走采集**弱语义轨迹**（只调只读工具，样本打 `explore` 标签）
- **隐私**：抓屏默认关；六类脱敏（身份证/银行卡/手机/邮箱/token/家目录）落盘前完成；
  剪贴板与键盘原文**永不采集**；raw 保留 90 天、帧 30 天或 8 GB
- 刻意**不提供**"删除全部"工具，清理由保留策略负责

### 三、控制权交接（新 `control.py`）

授权是"允不允许"，控制权是"现在谁在用"——后者原来完全缺失。

- 物理鼠标一动 → 立即夺回；闲置 10 秒 → 自动回到 idle
- `Ctrl+Alt+Shift+Backspace` 强制夺回
- 闸门两层化：授权通过后再看控制权；被拒时返回 `control` 字段与剩余恢复秒
- 注入前后各 250 ms 静默窗——否则 pynput 会看到自己注入的事件，AI 每点一下把自己锁死

### 四、自绘界面寻址（新 `find_element`）

UIA 对微信 4.x / Electron / CEF / 游戏几乎无效。`find_element(query)` 依次尝试：

```
UIA 控件名 → OCR 文字 → 模板匹配
```

命中即返回，统一成 `{x,y,w,h,cx,cy,source,score}`；单条来源出错只记 `errors`，不中断。
定位与点击分离。

### 五、其它

- `wait_for(kind=change|text|template|element|focused)` 统一等待入口（**委托**已有实现，不重写轮询）
- `ui_tree` 每个节点新增稳定 `element_id`；`ui_click` 支持按 id 点
- `DSH_UI_EXCLUDE_PROCESSES`：绕开卡死的 UIA 提供者（VS Code / Cursor 这类 Electron 应用）
- `DSH_TOOLS_ALLOW` / `DSH_TOOLS_DENY`：按场景裁剪模型可见的工具
- 截图后端 `dxcam → mss` 自动探测 + 回退；`capture_config` 报告当前 `backend`
- `anchor_mem` 坐标分层：窗口尺寸未变用**绝对坐标**（误差 0），变了才退回 corner/比例
- `train.py` → `conveyor.py`（消除与"训练数据"的撞名），`train.py` 保留为兼容层

### 六、修掉的 bug

| bug | 现象 | 根因 |
|---|---|---|
| 权限状态「前端绿、后台灰」 | 界面已授权，工具仍被拦 | ① 桥单槽状态被多窗口心跳互相覆盖；② 负向结果缓存 45s，期间不问桥；③ OCR 把「已授权」认成「床授权」直接判灰 |
| `asyncio.run` 在事件循环里静默失败 | 探索器 `ok=true` 但 `recorded=0` | 被 `call_tool` 在已运行的 loop 里调用 → 改独立线程 + 自己的 loop |
| `threading.local` 不跨线程 | 探索样本拿不到 `explore` 标签 | 标签作用域开在主线程 → 移到子线程内 |
| PowerShell 写入 UTF-8 BOM | `ast.parse` 报 `U+FEFF` | `Set-Content -Encoding UTF8` 会带 BOM |

### 七、验证

```
298 项测试全绿（5 项环境相关跳过）
控制权   claim → ai；物理输入 → user/takeover；闲置到期 → idle
静默窗   注入期间事件不算接管（test_quiet_window_ignores_our_own_events）
wait_for 五种 kind 全测：change 命中、其余正确超时
anchor   learn→locate source=absolute，坐标与期望完全一致
explore  3 步 → 记录 3 条、失败 0，labels=['explore','weak-semantic']
```

## [1.1.0] - 2026-10-27

**通用健壮性：窗口句柄自愈 + 点击丢包重试（不针对任何具体应用）。**

### 新增 computer_mcp/winutil.py

| 函数 | 作用 |
|---|---|
| `is_alive` / `win_rect` | 句柄失效时返回 False / None，**不抛异常** |
| `find_window(title, pid)` | 按标题片段 / 进程号找窗口 |
| `heal(hwnd, title)` | 句柄被重建后按标题重找（没有线索就不乱找） |
| `activate(hwnd)` | 置顶 + 前台，并校验是否真的到了前台 |
| `point_owner(x, y)` | 屏幕坐标落点属于哪个顶层窗口（判断是否被盖住） |
| `ensure_front(hwnd, probe)` | 上面几步的组合，返回 (可用句柄, 是否就绪) |

### click 支持 verify / retries

```json
{"kind":"click","rel_frac":[0.5,0.55],"verify":true,
 "verify_region":[0.4,0.5,0.2,0.1],"retries":3,"settle_ms":250}
```

自绘 UI（Unity / CEF / Electron）按帧处理输入，点太快会被吞：
实测 0.32s 间隔连点 12 次只生效 6 次，0.55~0.75s 全部生效。

### 顺带修的两个真 bug

| bug | 现象 |
|---|---|
| `pid_of(0)` 返回垃圾值（-840758880） | "按 pid 过滤"的代码在无效句柄下会找错窗口 |
| `heal()` 在没有标题/pid 时调 `find_window("")` | 会命中**任意第一个窗口**，等于乱抓 |

### 测试

232 → **241** 项全绿（新增 winutil 9 项，含真 Tk 窗口的 find/heal/point_owner）
## [1.0.0] - 2026-10-27

指令流（program）落地并跑通：facts.json + program.jsonl，一行一条指令。

### 新增 computer_mcp/program.py

| 能力 | 说明 |
|---|---|
| load_facts / load_program | 不变量 + 指令流（JSONL，支持 # 注释，报第几行） |
| expand | @name 取结构值、$name 插值；找不到就 KeyError 停下 |
| run | 按序执行；每条可带 expect（轮询）与 on_fail |
| 帧环自管 | changed / stable 需要的 FrameWheel 由 run 创建与回收 |

### 首次跑通（微信，04:18）

    L3 click 发现 -> L4 click 朋友圈(changed) -> L5/L6 scroll
    L7 回聊天(changed) -> L8 send(面板/输入/会话区/残留 四段全过)
    L9 assert 通过  ->  ok=True done=7 · 6.0 秒 · 截图两条气泡

文件：programs/wx_facts.json、programs/wx_send.jsonl

### 顺手修掉四个 bug

| bug | 现象 |
|---|---|
| FrameWheel 参数传错（hwnd 当 ring） | 0 帧，changed 永远 False |
| 后置条件一次性判 | 朋友圈要 1-2 秒加载，立刻判必 False |
| since 每轮重置成 now | 永远只看最近 120ms，变化率恒 0 |
| assert 不轮询 | OCR 把流读成氵夼，一次判死 |

### 全链路状态

    微信全轨道 7 步 done，消息真发出（闭环验证 04:16:24）
    指令流 ok=True done=7（指令流 04:18:00 / 04:18:28）
    回归测试 clicks=1（无 expect 的步骤确实执行）
    测试 234 / 235 全绿

## [0.9.1] - 2026-10-27

**给 0.9.0 那个根因 bug 补一个不依赖外部应用的回归测试，并记录"子窗口句柄"这个坑。**

### 新增 `tools/track_nopred_demo.py`

自开一个 Tk 窗口 + 按钮（点一次记一次），然后跑一条**只有 action、没有 expect** 的轨道：

```
修好之前：status=done、0.2 秒、clicks=0   ← 正是那个 bug 的样子
修好之后：status=done、0.14 秒、clicks=1  ← 动作真的执行了
```

退出码 0 = 通过。**这是今晚唯一一个能独立证明修复生效的证据**（不需要微信、不需要 Steam）。

### 顺带挖出来的坑

`root.winfo_id()` 是**客户区子窗口**，对它 `SetWindowPos(HWND_TOPMOST)` 抬不动 toplevel，
点击会落到别的应用上 —— 演示脚本第一版就是这么假的（clicks 恒 0）。
要用 `int(root.wm_frame(), 16)`，且比例坐标必须按 `GetWindowRect(frame)` 算。

### 验证状态

- 回归测试：**通过**（clicks=1）
- 微信全轨道复跑：**仍未完成** —— 微信登录态失效（弹「请重新登录」），需要用户扫码
## [0.9.0] - 2026-10-27

**根因修复：`check_expect(None)` 返回 True，导致"只带动作的步骤"永远不执行，
而轨道照样报 done —— 这是这一小时所有"假成功"的总根源。**

### 修的 bug

```python
# 以前
if not expect:
    return True          # 没有判据 → 当成"已达成"
# 结果：Runner 先判 pred，True 就跳过动作 → send/paste/scroll 全都没执行
```

```python
# 现在
if not expect:
    return None          # 没有判据 = 判不了
# 并且：动作成功且 expect is None → 这步算完成
```

### 为什么这个 bug 特别坏

它**不会报错、不会超时、不会异常**，只会安静地让轨道"跑完"，
然后在截图里发现什么都没做。今晚我三次据此宣布"done"，三次被截图推翻。

### 附带完成

| 内容 | 说明 |
|---|---|
| `send` 动作 | 点输入框 → 粘贴 → 验文字 → 回车 → **用会话带 OCR 验证文字真的出现** |
| 面板校验 | 发之前先读标题区，面板没开就点一次会话行（点已开的会把它关掉） |
| `skip_if` | 幂等步骤：已是目标状态就跳过 |
| 证据来源选择 | 会话带 OCR 可靠；列表预览那一行 OCR 会在"名字/副标题"之间跳，只能当诊断 |

### 验证状态（诚实记录）

```
✅ send 单动作连发 3 次：ok=True×3，截图 6 条气泡（04:10:15/22/29/45/49/53）
✅ 全轨道跑到最后一步：会话带末读到「全流程 04:12:28」（消息确实发出）
⚠️ 最后一次全轨道复跑没做完：微信弹「请重新登录」，登录态失效（需用户扫码）
```

测试 222 项全绿
## [0.8.3] - 2026-10-27

**track 支持中途换目标窗口（微信独立聊天窗的通用解法）+ 文本判据支持 upscale。**

### 新增

| 能力 | 用法 |
|---|---|
| step 级 `focus` | `{"focus": {"title": "文件传输助手"}}` → 找到就 retarget（换帧环+rect），找不到默认沿用当前窗口 |
| `expect` 支持 `upscale`/`boost`/`region` | 输入框小字 1× 读不到；**中文别用 boost**（件→亻牛） |

### 实测（这轮 9/10 步）

```
✅ 点会话行用 find 命中「文 件 传 ． “ 03 ： 52」score 0.85 —— 软选择器第一次在真轨道里生效
❌ 卡在粘贴/回车：粘贴的 stable 判据"达成"但输入框其实是空的
结论：发送类步骤的终判据必须用"气泡出现"（画面变化），不能用"输入框里有字"
```
## [0.8.2] - 2026-10-27

**软选择器在真实界面上的三个硬要求（微信实测），rel 占比 100% → 33%。**

### 复测数据

```
会话行「文件传...」  within + upscale=2  → text, score 0.85, 165 ms
聊天标题「传输助手」  within 顶部区        → text（OCR 读成「文亻牛传输助手」，LCS 救回）21 ms
输入框              text:"发送"           → rel（发送键是灰的）→ 这类区域保留 rel
```

### 三个硬要求

| 要求 | 依据 |
|---|---|
| **小字必须 `upscale: 2`** | 11px 列表行 1× OCR 完全读不到（只读到时间戳/角标）；2× 才出名字 |
| **CJK 不要 `boost`** | `件` 会被拆成 `亻牛`（实测三次一致） |
| **截断按最长公共前缀 ≥3 判** | OCR 读成「文件传 ． “ 03 ： 52」，名字后面粘着时间 |

### 顺带

- `recipes/wechat.json` 增加 `find_specs`：三个目标可直接抄的参数
- ACF 滞后 / 日志验证（0.8.1 已记）
## [0.8.1] - 2026-10-27

**真实任务跑出来的三处修正（微信 / Steam / QQ）。**

### 修的

| 修正 | 依据 |
|---|---|
| Steam 订阅验证改读 `workshop_log.txt` | ACF 的 mtime 停在 03:53，而订阅发生在 03:55（滞后 2 分钟），用它判断会误判"没订上" |
| 依赖弹窗用**固定坐标**点「仅订阅此项目」 | 弹窗打开时页面不响应悬停，OCR 判它是否打开会漏判 |
| 取消订阅 = 再点同一个绿按钮 | 日志会写 `Unsubscribed from item` + `removing unused item` |
| `selector.score_line` 支持**截断前缀** | 微信会话行显示成「文件传...」，query「文件传输助手」原本匹配不上 |
| `selector` 支持 OCR `upscale` | 输入框占位符是灰字，1× 读不出（ocr_read 支持 upscale/boost） |

### 实测记录

```
微信  03:52「自动化验证 · 软选择器跑通」已发出（主窗口流程）
      method 统计：会话行=rel，输入框=rel → 软选择器在该界面尚未生效（已修）
Steam 03:55 订 2 张（the awakend army / Pumpkin Patch），03:55:52、03:55:56 全部取消
QQ    QQNT 没有可用窗口，且按键落到 QQ音乐 → 跳过硬编码
```

### 测试

214 → **217** 项（selector 17 项，新增截断/前缀 3 条）
## [0.8.0] - 2026-10-27

**第 1 步落地：软选择器（selector）—— 按语义找控件，找不到才退回坐标。**

用户要求：「先做小、能验证的那一步；可以用就放大，不行再想办法。」

### 新增 `selector.py`

```
三级降级：text（OCR 找那一行）→ template（cv2 匹配图标）→ rel（比例坐标兜底）
返回值带 method，便于统计"退化率"（rel 占比高 = 这套在该应用上没起作用）
```

动作里这样用：
```json
{"kind":"click","find":{"text":"文件传输助手","within":[0.06,0.1,0.24,0.9],"rel":[0.142,0.331]}}
```

### 可复现 A/B（`tools/selector_demo.py`）

自己开 Tk 窗口当靶子，量一次 → 挪走+改尺寸 → 三种各点一次，**由被点窗口自己记账**：

```
A 硬坐标（旧绝对位置）   ✗ 点空
B 软选择器·文本          ✓ 命中「发 现」score=1.0
C 软选择器·模板          ✓ 模板 score=1.00
```

### 做的过程中踩到并修掉的两个真 bug

| bug | 现象 | 修法 |
|---|---|---|
| OCR 行是扁平 `{text,x,y,w,h}`，我按嵌套 `rect` 取坐标 | 文本选择器永远失败（但 OCR 明明读到了） | `_geom()` 兼容三种形态 |
| `cv2.imread` 读中文路径返回 None | 模板永远匹配不上，还不报错 | `imdecode(np.fromfile(...))` |

（另外：Tk 不能跑在子线程 → 演示脚本改成双进程；子进程残留会互相覆盖 state → 每轮独立文件名）

### 测试

213 → **216** 项（`test_v11_selector.py` 15 项：文本归一化/LCS、候选打分、
同分选小控件、within 过滤、rel 兜底、嵌套 rect 兼容）
## [0.7.0] - 2026-10-27

**把这几轮实验里所有弱点和踩坑，全部收进 skill（9 个分册）。**

用户原话：「会踩坑的那些东西、记忆库那些东西、agent 那些东西，还有这几次实验下来的
那些弱的东西缺点，全部写进优化之后的 skill 里。」

### 新增两个分册

| 分册 | 内容 |
|---|---|
| `references/pitfalls.md` | **事实**：启动（ShellExecuteW vs cmd start 管道）、窗口（鬼影/SW_HIDE 毁输入）、DPI、输入（丢字/对话框/UWP）、Shell（UTF-8/解释器/pip/curl）、性能（实测毫秒数） |
| `references/failures.md` | **我的病历**：30 条「症状 → 真因 → 正确做法」，分 A看/判断、B时间、C状态输入、D工程流程、E收尾 |

### SKILL.md 重写

```
顶部加「失败模式速查」10 行表（卡住先看这张）
核心循环 / 三条铁律 / 判活三连 / 输入方式 / 工具分层 / 收尾 / 分册索引
```

### 分册补写（这轮真跑出来的）

- `wechat.md`：**会话开在独立窗口里**（标题=聊天名，919×971）—— 点会话行后主窗口右侧
  永远是空白，看起来像"没反应"。附实测发出的完整流程。
- `train.md`：v0.7 实战补丁 9 条 —— 每步置顶+置前、scroll 的 `at_rel_frac`、
  `changed` 改锁存、第一帧不算变化、文本归一化+LCS、默认整窗、对话框特征词、
  ShellExecuteW 启动、滚动类判据用 `stable`。

### 这次迁移掉的 AGENTS.md 内容

```
长期记忆约定 / 清理与保留策略 / 验证助手用法 / 本机工具链与解释器 / UTF-8 改文件规则
→ 全部进 references/toolbox.md
AGENTS.md 只留指针 + 用户偏好
```

### 测试

199 / 200 项全绿（desktop-mcp / 仓库）
## [0.6.1] - 2026-10-27

**修 0.6.0 的一个致命命名 bug + 加一次性自测脚本。**

### bug：`self._stop` 覆盖了 `threading.Thread._stop()`

```
FrameWheel 里把停止事件命名为 self._stop
→ Thread.join() 内部会调用 self._stop() → TypeError: 'Event' object is not callable
→ 任何 track/selfcheck 在收尾时崩溃
```
单元测试抓不到（它们不启动真线程），是**一次性自测脚本第一枪**打出来的。
改名 `_stop_evt`。

### 新增 `tools/track_oneshot.py`（用户只需要跑这一条）

```
① 抓帧自检 6 秒      → fps / 环形上限 / 线程异常
② 记事本轨道 3 步    → 点击 → 粘贴 → 文本断言 → 稳定
③ 看门狗演练         → 故意超预算，验证会报异常并在 2 次后停车
④ 清理               → 关掉记事本
退出码 0=全过；11 项检查
```

### 实测（自测脚本输出）

```
① 27.8 fps · 环形 167 帧 / 3490 KB（有上限）· 线程无异常
② status=done · 3/3 步 · 0.8 秒 · 异常 0 · 对话框 0 · 拼图 6 KB
③ anomalies=2 · status=stall · 2.0 秒停车
```
## [0.6.0] - 2026-10-27

**列车（track）：三轮回转 + 看门狗。用户原话：「指令是轨道，截图是轮子，
车要一直开，不是做一次卡一次。」**

### 新增 `train.py`（三层轮子，一个工具）

```
轮子1 入帧   抓**目标窗口**（不是全屏）+ numpy 块平均 → 灰缩小图 + JPEG → 环形缓冲
轮子2 处理   差分 → 变化块 → 状态机 STABLE/TRANSITION → 事件（SETTLED/STALL/ANOMALY）
轮子3 出     最新稳定帧 + 变化块拼图 + 事件时间线（交回模型的约 7–30 KB）
看门狗       每步 budget_ms；>3× 判异常并出拼图；连续 2 次异常停车
对话框检测   OCR 读到「是否保留/要创建新文件/另存为…」→ 记 ANOMALY，别再无脑重试
```

**工具只加 1 个**：`track(action=run|start|status|stop|selfcheck)`。
`start` 后台跑，`status` 随时取新鲜摘要（含一张新拼图）——我思考期间车不熄火。

### 实测（2560×1440，本机）

```
抓帧        29.8 fps（目标 30）   单帧 18.2 ms = 抓窗口 13.7 + 块平均 4.5
环形缓冲    150 帧 / 0.4–0.7 MB   恒定（帧上限与字节上限都验证过）
进程内存    128.5 MB，60 秒一条直线，不增长
3 步轨道    0.9 秒跑完（点击 → 粘贴 → 文本断言 → 稳定）
看门狗      6.1s / 7.5s 准确触发（2.0s / 2.5s 预算的 3 倍）
```

### 这轮修掉的 5 个真 bug（都是自测抓出来的）

| bug | 现象 | 修法 |
|---|---|---|
| OCR 每 20 ms 调一次 | 全车被拖慢，判据挤占抓帧 | 贵判据限频 150 ms |
| 文本直接 `in` 比对 | OCR 把 `TRACK-OK-2152` 读成 `TRACKOK2152` → 永远不成立 | 归一化 + LCS 0.8 |
| `region` 写小 | 把目标排除在区域外，静默失败 | 不传 region 默认整窗 |
| 记事本残留「是否保留更改」 | 后续按键全被吞 | 自动识别模态对话框并报 `dialog_hits` |
| 全屏抓 + PIL 缩放 | 17.8 fps，且我一度以为方案不可行 | 抓窗口 + numpy 块平均 → 29.8 fps |

### 测试

162 → **199 项**（`test_v10_train.py` 37 项：块平均 / 变化块 / 环形上限 /
事件上限 / 看门狗阈值与停车 / 轨道解析 / 拼图 / 文本归一化与 LCS）
## [0.5.1] - 2026-10-27

**修 0.5.0 的自测断链：规则搬走后，仓库里那条不变量还在看 AGENTS.md。**

验证助手直接判 FAIL：
```
测试【高】退出码 1
  test_agents_md_mentions_close_windows → 断言 AGENTS.md 里有「关窗/收尾」
```

### 修法（两边都改，不是放宽断言）

1. **测试跟着规则搬家**：改成 `test_rules_live_in_skill_not_agents_md`
   - 规则本体必须在 `skill/desktop-operator/SKILL.md`（含收尾/关窗）
   - `AGENTS.md` 必须留 `desktop-operator` 指针（断链也算失败）
2. **skill 补上确切词**：§5 收尾原来写"关掉/最小化"，没有 `close_windows`/「关窗」这两个词。
   改成写明 `close_windows`（只发 WM_CLOSE，不杀进程）与「关窗」，并补上边界
   （只关自己开的窗口、有未保存改动先问用户）。

### 结果
```
仓库测试 163 项 OK（skipped 7）
```
## [0.5.0] - 2026-10-27

**新增 Skill `desktop-operator`：把「规则」从 AGENTS.md 搬进可复用的技能，随本包一起发布。**

用户原话：「你缺一个 SKILL……把规则从 AGENTS.md 里删除，迁移到这个 skill 里，
然后把它一起上线开源平台，跟这个 MCP 在同一个包里面。」

### 为什么搬

AGENTS.md 里光桌面部分就 22 KB，越堆越长、每次都要整份加载，而且**混在通用记忆里**。
搬到 skill 后：
```
AGENTS.md   31.2 KB → 8.3 KB  （-73%）
skill       一个入口 + 4 个分册，按需读，不再每次全量加载
```

### 包内结构

```
skill/desktop-operator/
  SKILL.md               入口：开工顺序 / 三条铁律 / 判活三连 / 假阴性清单 / 工具分层
  references/wechat.md   微信 4.x：进入微信面板、主窗口比例坐标、发消息、朋友圈
  references/steam.md    Steam 创意工坊：卡片网格、+ 位置、只点一次、ACF 验证
  references/uwp-cef.md  UWP(记事本)/CEF/Electron 的通用判据与陷阱
  references/coords.md   DPI、四种坐标系、rel_frac、判活三连、读图预算
```

### 安装（一条命令）

```powershell
Copy-Item -Recurse "图标控制\skill\desktop-operator" "$env:USERPROFILE\.dsh\skills\"
```
装好后在 DSH 里直接说「帮我给微信发…」就会命中它。

### 这次迁移掉的（AGENTS.md）

```
· 开工顺序（配方 → 宏 → 工具 → 手写）
· 接管桌面 / 桌面 MCP 是手和眼
· 急停约定、鼠标授权开关说明
· v0.4 采集守护、快慢双层导航、布局标定与记忆
· 微信窗口唤不醒三条硬规则
→ 全部并入 skill（内容保留，位置变了）
```

### 同时修掉

- `diag_input.py`：L3 打不进去时不再断言「被系统拦截」，改判 **UNKNOWN** 并列出假阴性排查项
- `recipes/wechat.json`：补上实测通过的 15 步流程与比例坐标

## [0.4.5] - 2026-10-27

**把「零件」装回「会走路的车」。用户原话：「怎么感觉还变弱了呢？给他全部修好。」**

### 诊断
底层确实快了 100-300 倍（sense 0.010 ms / probe 0.155 ms / 41 步 0.41 s），
但任务级效率退步：

   微信发两段    宏本来 4.7 s    实际绕 1 小时（DPI、鬼影窗口、重复实例）
   Steam 订地图  配方本来 3 步   实际 1 小时只订上 1 张（还点两次取消了 1 张）

根因：新层与旧路（配方+宏）并行、入口没有仲裁、配方里的事实没沉淀进代码。

### 修法一：按比例坐标（让旧宏抗缩放）
宏引擎新增 `rel_frac: [fx, fy]` 与 `region_frac: [fx, fy, fw, fh]`（0~1）。
旧宏用绝对像素，窗口从 600x700 变 1566x1054 后 `type_verified` 整体偏移而失败。
新增 `macros/wechat_send_frac.json`：ensure_chat -> 点输入框（按比例）-> 剪贴板粘贴
-> 回车 -> 断言气泡。任何窗口尺寸都能用。

### 修法二：配方里的事实变成机器可读
`recipes/steam.json` 新增 `workshop_subscribe`：
卡片网格（按窗口宽的比例）、+ 按钮在缩略图右下角（0.776, 1.19 of card）、
每张只点一次（再点就是取消）、验证走 appworkshop_<appid>.acf + content/<fileid>、
依赖弹窗三个按钮的比例坐标。

`recipes/wechat.json` 新增 `send_message`（按比例路径）与 `window_sizes_seen`。

### 修法三：入口仲裁写进 AGENTS.md 第一条
    ① 配方有 -> 照抄   ② 宏有 -> macro_run   ③ 都没有 -> 才用新层   ④ 再没有 -> 手工
工具分层：78 个里只有 6 个是入口（macro_run/batch/ocr_read/find_text/layout_mem/sense）。

### 修掉的 bug
- 宏占位符 `${text_assert}` 没有默认值 -> 不变量测试抓到，改用 `${text}`
- `layout_mem.py` 未使用的 `import os` -> 验证助手 imports 检查抓到

### Tests
154 -> **162**（desktop-mcp）/ 163（仓库）：新增 `test_v09_frac_coords.py` 8 项
（按比例坐标在两种窗口尺寸下的换算、绝对 rel / br 锚点回归、区域最小 1px）

### 验证
    desktop-mcp  verify_start -> PASS（0 未回应）
    图标控制      verify_start -> PASS（收敛）

## [0.4.4] - 2026-10-27

**布局标定与记忆（走 A 路线）：看一眼 → 记住 → 复用。**

用户原话：「我要改的是通用的……我要提升自己的综合能力，不是专项化能力。
我就喜欢搞这种革命性的，而不是按着一个架构一直改。」

### 为什么不做「自动识别布局」
实测（3 张真实截图，四个探测器）：
```
内容区（去黑边）   应该 806x640      → 判成整窗 1233x1019
HUD 文字行         应该 3 行          → 0 行
网格面板（小地图） 应该 pitch≈11      → 0 个 / 误报 pitch=4
进度条             应该 2 根          → 12 根（全是抗锯齿噪线）
```
结论：纯像素启发式打不过真实画面，再调阈值只是对单张图作弊。
`screen_model.py` 保留为**实验性**（默认关闭，docstring 写明实测结论）。

### Added `layout_mem.py`（通用，不绑应用）
```
① 人对着一张截图看一次，报 4 个区域的**归一化坐标**（相对画布 0~1）
② 存成档案，键 = 应用名（标题去版本号）+ 画布尺寸
③ 之后窗口缩放/移动 → resolve 按档案换算成像素框，每次 0 成本
④ 换应用 = 再看一次（2 分钟），不是"再写一套常量"
```
两种缩放模式（这是踩出来的）：
- `fixed`（默认）：程序以固定尺寸绘制并贴左上角（游戏常见）→ 用档案画布，不按客户区裁剪
- `fit`：随窗口拉伸（编辑器/浏览器）→ 用当前客户区

### 新工具（76 → 78）
- **`layout_mem`**：`save` / `list` / `resolve` / `delete`
- `world_state` 现在会自动套用匹配的档案（调用时不用再传坐标）
- `screen_layout`：通用布局探测（实验性）

### 端到端验证（真实游戏窗口，800x600 客户区）
```
save  → key=canity, regions={map,prompt,bar,hud}
resolve → map=[1410,772,268,248] prompt=[1128,878,298,47] bar=[1005,928,189,22]
裁图核对 → hud 区域正好是 LEVEL 1 / SANITY 4% / FUSES 0/2 ✅
```

### Tests
137 → **154**（`test_v08_layout_mem.py` 15 项：去版本号 / 区域校验 /
存取 / 匹配 / fixed 与 fit 两种缩放 / 最小 1px；另加 clamp 回归）

## [0.4.3] - 2026-10-27

**快慢双层导航：把我从内环挪到外环。**

用户原话：「你就做不到像那个实时屏幕共享的实时读取了。就是提高你的思考回馈路径。
可以设计点新东西，干什么都行，能解决这个问题就行。」

### 问题的数学
```
模型      0.2–0.5 次/秒决策（每次 2–5 s 生成）
人类/豆包  20–60 次/秒视觉伺服
差距 100×  —— 把 sense() 从 10 ms 压到 1 ms 也救不了，瓶颈是 token 生成
```

### Added `navigator.py`（三层）
| 层 | 类 | 职责 | 频率 |
|---|---|---|---|
| M1 | `WorldState` | 画面 → 结构化状态（小地图网格 / 玩家格 / 目标格 / 提示 / 电量） | 15–20 Hz |
| M2 | `Servo` | 目标格 → 动作（每步重算方位误差并修正） | 20–30 Hz |
| M3 | `Supervisor` | 跑计划，只在「达成/卡住/不确定/新事件」时回到模型 | 事件驱动 |

**三个关键设计**
- **小地图自动标定**：列投影求格子间距（实测 10.5 px），不硬编码坐标
- **朝向自校准**：不读罗盘 —— 走一小步，看玩家标记在地图上的**位移方向**，
  就得到朝向（`Servo.estimate_heading`），任何有地图的游戏都能用
- **只在卡住时交回**：`approach` 防振荡（连续 6 步没更近就退出），
  `Supervisor` 返回一页状态文本（<300 token），不是一张图

### 新工具（73 → 76）
`world_state` / `servo`（calibrate·face·approach·forward·turn）/ `navigate`（跑计划）

### 单测抓出的 3 个真 bug
| bug | 现象 | 修法 |
|---|---|---|
| 角度符号反了 | 转完朝向变成 `2*have - want`，越走越远 | `face_deg(-diff)`（鼠标右移 = 数学角减小） |
| stuck 检测错 | 拿 `history[-1]` 比 `history[-3]`，"转向+前进"交替被误判成卡死 | 只比较相邻两次 |
| 对角振荡 | 在 `(8,2) ↔ (6,4)` 之间来回晃，dist 恒 1.41 | 容差 1.0→1.5 + 6 步无进展就退出 |

### Tests
118 → **127**（新增 `tests/test_v06_navigator.py` 9 项：地图解码 / 朝向自校准 /
走到目标 / 卡住上报 / 计划完成 / 卡住交回 / 急停中止）

## [0.4.2] - 2026-10-27

**新增保留策略：这个助手跑起来不再产生垃圾文件。**

用户原话：「你要考虑我以后这个鼠标助手跑起来不会产生垃圾文件。」

问题不是「有临时文件」，而是**没人负责删**：`_draw/` 每次截图都多一张、
`recordings/` 每次录制一个目录、`%TEMP%` 崩一次留一堆。

### Added — `retention.py`
```
区域                上限                      超了删什么
_draw               80 个文件 / 80 MB / 3 天   最老的先删
recordings          10 个目录 / 300 MB / 7 天  最老的目录整个删
vision/baselines    40 个文件 / 30 天          最老的先删
%TEMP% 自己的东西   vh-* / canity_* / t_*.py   超过 6 小时的
```
**资产永不删除**：`macros/`、`recipes/`、`templates/`、`vision/glyphs.json`、`_patched/`。

### 什么时候自动跑（不用你记得清）
- `capture_daemon start` —— 每次开始接管屏幕时
- `snapshot` 写完图之后
- `record` 存完录制之后

### 新工具
- **`housekeeping`**：`action=status` 看用量（只读）、`action=sweep` 清扫（可 dry_run）

### Fixed
- `%TEMP%` 清理名单里**移除了 `dsh-`**：那是 DSH 宿主自己的临时目录
  （`dsh-spill-*` / `dsh-subprocess-*`），删了会影响运行中的会话
- `templates/` 一度被写进"可裁剪"策略里 —— 它是资产，测试当场抓出来了

### Tests
108 → **118**（新增 `tests/test_v05_retention.py` 10 项：按数量/天龄裁剪、
最新保留、资产不动、录制目录上限、%TEMP% 只碰自己前缀、housekeeping 契约）

## [0.4.1] - 2026-10-27

补上 v0.4.0 漏掉的东西，并让仓库自带的测试第一次真正跑通。

### Added
- `doctor.py`（环境体检，6 组检查）与 `panic_watch.py`（急停看守进程）——
  这两个文件 v0.4.0 没跟进来，仓库里的不变量测试一直在等它们
- `tests/_bootstrap.py`：没有装 `computer_mcp` 的机器上，整组测试**明确跳过**
  （以前是几十个 ImportError，把「没环境」误报成「测试失败」）

### Fixed
- 仓库测试的 `PROJECT` 解析：优先 `DSH_DESKTOP_MCP` → 本机默认位置 → 跳过
- `test_copies_match`：区分「未脱敏文件必须字节相等」与「脱敏文件只查结构」——
  发布版把真实应用名换成了中性示例（ChatClient / app-01_send），
  要求字节相等是误报
- `test_sanitized_keeps_public_api`：新增，脱敏可以改名但不能删公开接口
- 过期断言：`auto_bot*.py` 已移除 → 缺失时跳过；配方清单改为按实际文件校验

### Tests
仓库测试 **109 项**（跳过 7）在本机 venv 下全绿。

## [0.4.0] - 2026-10-27

架构升级：**把"看屏幕"从每动作一张图，改成常驻采集 + 端上感知 + 端上闭环**。

### Added — 采集守护
- `capture_daemon.py`：常驻线程按 12~20 fps（静止时降到 3~5 fps）抓屏，
  缩放到 0.5 放进 120 帧环形缓冲；每帧算平均差异、脏区矩形、哈希、前台窗口标题
- 隐私护栏：命中"密码/登录/凭据/1password"等标题的帧**不保存像素**
- `wait(predicate)`：事件等待，替代"sleep + 再截图"

### Added — 感知原语（0.1~3 ms）
- `perceive.py`：`prompt`（亮字占比）、`bar`（彩色条填充率）、`openness`（视野开阔度）、
  `color_blob`、`diff_region`、**`locate_rows`（按颜色自动定位 HUD 行）**
- 实测：`probe(prompt)` 0.155 ms、`probe(openness)` 0.301 ms、
  `sense()` **0.010 ms**（读内存）

### Added — 数字识别（P2）
- `digits.py`：切字 → 归一化 5×7 → 模板匹配；内置 0-9 标准点阵 + **运行时学习**（`glyph` 工具）
- 实测读像素字体 1.3~2.6 ms；Windows OCR 在同一 HUD 上读出 "L E E L 1" 且要 120~180 ms

### Added — 端上闭环（P1）
- `micro.py`：微脚本解释器（key/press/turn/move/click/sleep/loop/if/until/log），
  条件在本地求值，带步数与时长预算、嵌套深度上限
- 实测：41 步闭环 **0.41 s**（走模型往返约 123 s）

### Added — 工具与证据
- 14 个新工具（58 → 72）：`capture_daemon` / `sense` / `watch` / `probe` / `hud` /
  `snapshot` / `run_script` / `act_until` / `frame_mark` / `frame_diff` / `trace` /
  `glyph` / `read_digits` / `record`
- `record` 把环形缓冲落盘（JPEG q80，实测 PNG 9.4 MB → JPEG 0.3 MB 量级）

### Fixed
- 数字读取默认走**全分辨率区域抓取**（缩放帧上的字形太小，5×7 会抹平）
- `hud` 自动定位：窗口从 806×640 变成 537×427 后，硬编码坐标当场失效

### Tests
- 新增 `tests/test_v04_live.py`：22 项（原语 / 数字 / 解释器 / 守护 / 工具契约）
- 合计 **86 → 108** 项，venv 与系统 Python 双绿

## [0.3.2] - 2026-10-26

修复脱敏脚本造成的**语法错误** —— 发布之后由验证助手 v1.10.5 扫出来的真问题。

### Fixed
- **环境变量名被替换成中文**：`DSH_E2E` 曾变成 `对话壳（***）_E2E`，成了非法标识符 → 还原 ASCII
- **类名被替换成中文**：`TestBilibiliRecipe` 一类同样被替换 → 统一改为 ASCII 命名
- **失效引用**：`recipes/***.json` 指向不存在的文件 → 改指真实的 `app-03.json`
- 影响 33 个文件；修复后全仓 `ast.parse` 通过，验证助手判定 PASS

### Changed
- 版本 0.3.2

# Changelog

所有改动记录在此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.3.1] - 2026-10-26

修 v0.3.0 里三个会让通道「看起来接了、其实没通」的问题。

### Fixed
- **客户端模块改动不随刷新生效**：DSH Host 缓存了 client 模块，F5 无效。
  → `_authorized` 改为**来源校验（Origin 或 Referer）**，无 token 也可接受，
  这样 Host 里那份旧模块也能立刻上报；带 token 的请求一旦出现，自动收紧为「只收带 token」。
- **图片信标没有 Origin**：`<img>` 请求不带 Origin，只靠 Origin 校验等于对任何站点敞开。
  → 加本机 token（`state/bridge-token.txt`，不进源码/仓库；仓库里只有 `__BRIDGE_TOKEN__` 占位符）。
- **client.js 被写成乱码**：读写文件时混用了系统编码。
  → 整文件按 UTF-8 重写，并加体检（UTF-8 合法性、token 存在性、`/beacon?k=` 存在性）。

### Added
- `GET /beacon?k=<token>&granted=1|0` 图片信标通道：不受 fetch 的 CSP/CORS 限制
- 心跳从「组件 effect」提到「插件级」：热重载/重挂不会再把它清掉
- `visibilitychange` / `focus` 补发：Electron 节流后台定时器时尽快恢复
- 桥日志记录 `REJECT`（路径 / 来源 / token），排查时不用猜

### Changed
- 测试仍 **86 项**（断言已跟上新实现：`DEFAULT_PORT` / `const BRIDGE` / `/beacon`）

## [0.3.0] - 2026-10-26

把「有没有授权」从**看屏幕像素**改成**走程序层通道**。

### Added — 授权状态通道（本地桥）
- `computer_mcp/permission_bridge.py`：只听 `127.0.0.1:18765` 的小服务
  - GUI 插件每 5 秒把真实授权状态 POST 过来，Host 直接读状态文件
  - **无 token**：改校验 `Origin`（只接受 `dsh-app://` / `file://` / `127.0.0.1` / `localhost`）
    —— token 写死在源码里，发布即公开；Origin 由浏览器设置，普通网页改不了
  - 只写一个 JSON 状态文件，源码里没有任何执行命令的调用
- 客户端插件：挂载即上报 + 5 秒心跳 + 点击立即上报（`no-cors` 简单请求，无预检）
- 闸门（`permission.py`）**桥优先**：新鲜桥状态 0.1 ms 直接用；桥没起来会**自愈拉起**；
  OCR 仅作后备，且有效期从 45 s 缩到 **15 s**（桥挂了不会一直"以为已授权"）

### Fixed — 一个方向最危险的假阳性
- 旧实现里扫描区域第三条是 `(0,1000,2560,440)`（整个窗口下 1/3），
  OCR 会读到**聊天正文里**的「鼠标·已授权」字样，再撞上一处绿色像素 → 判成已授权
- 修法：扫描区收窄到输入框工具栏（高度 ≤ 200）；正面判定必须
  「检测到绿色胶囊」**且**「文字含 鼠标 + 已授权」同时成立；否则 unknown → 按未授权处理
- `tools/mouse_permission.py` 不再自己 OCR，改为调 `permission.status()`，与闸门同源

### Changed
- 测试 **75 → 86** 项（新增 11 项守桥：模块常量、写入/读取、无秘密、Origin 校验、
  TTL 短于 OCR、新鲜状态不触发 OCR、过期状态不信任、插件三处上报、CLI 同源、扫描区高度）
- 工具数仍 **58**（桥是支撑进程，不是 MCP 工具）

## [0.2.0] - 2026-10-25

把 v0.1 的"能力面"补成"可治理面"：**授权下沉到执行点**、**验证变成分级留证**。

### Added — 权限硬闸门（Host 侧）
- `computer_mcp/permission.py`：输入类工具的**统一闸门**
  - 未授权时在 `call_tool` 路由之前直接返回结构化拒绝，**不产生任何鼠标/键盘动作**
  - **fail closed**：读不到授权状态时按未授权处理
  - 45 s 缓存（命中约 0 ms，不给每次点击加 IO）
  - `DSH_MOUSE_GATE=off` 仅供自动化测试关闭；`DSH_MOUSE_STATE` 可指向别的状态文件
  - 状态来源：GUI 上那个「鼠标·已授权 / 未授权」胶囊（OCR 读取），只读不写
- 覆盖 19 个输入类工具（`click` / `type` / `key_press` / `batch` / `macro_run` / `ui_click` /
  `click_template` / `hover_probe` …）；只读工具（截图、OCR、模板匹配、状态查询）不受影响

### Added — 分级验证 `verify_flow`
- 新工具 `verify_flow`：**按级验证、遇错即停、每级留证据**
- 五种断言：`text`（区域 OCR + 容错）/ `template`（模板命中）/ `baseline`（基线偏离）/
  `stable`（连采稳定）/ `file`（存在 + 内容包含）
- 报告含每级耗时、每条断言的具体证据（OCR 片段 / 置信度 / diff / 文件大小）
- `stop_on_fail=False` 时跑完全部，`failed_stage` 记**第一处**失败，`failed_stages` 记全部
- 可写 JSON 报告留档（`report_path`）
- 只做验证、不做动作 —— "动作做了没生效"与"根本没做"能在报告里分开

### Changed
- 工具总数 **57 → 58**
- 测试 **64 → 75** 项（新增 11 项守闸门与分级验证）
- `verify_flow` 的失败语义修正：多级失败时 `failed_stage` 不再被最后一级覆盖

### Fixed
- 清掉 6 处未使用的 import（两个演示脚本 / 三个测试文件）
- 探测性 import 显式标注用途，避免静态检查误报

### Docs
- 文档与示例统一脱敏：应用名以「软件性质（***）」表示，不含个人信息

## [0.1.0] - 2026-10-25

首个公开版本。能力面打通：**能看、能点、能验、能停、能授权**。

### Added — 采集与感知
- 采集层重写：默认 0.5 倍缩放 + JPEG q75，单次截图 **128 ms → 61 ms**、**962 KB → 121 KB**
- `screen_state`（不带图，43 ms，回报 changed / diff / hash）
- `wait_for_change`（事件驱动等待，替代模型轮询）
- `capture_config`（运行时改 scale / quality / format / diff_threshold / mask_bottom）

### Added — 执行层
- `batch`：一串动作合成一次调用（20 步协议层 2 ms，往返 20 → 1）
- UI Automation 五件套：`ui_tree` / `ui_find` / `ui_click` / `ui_invoke` / `ui_set_text`
- 宏引擎 `macro_run`：相对坐标、`anchor:"br"`、`expect` 校验、自动 restore、越界拒点、
  `retry` / `repeat` / `ensure_chat` / `assert_text` / `assert_file` / `clipboard_*` / `paste`
- OCR 三件套：`ocr_read` / `find_text` / `click_text`，支持 `upscale` + `boost` 认小字与灰字

### Added — 视觉状态判据（本版核心）
- `capture_template` / `match_template` / `wait_template` / `click_template`：灰度模板自学 + 匹配
- `set_baseline` / `diff_baseline` / `wait_baseline_change`：区域偏离基线的程度
- `sample_stable`：连采多次一致才算数，防动画中途误判
- `hover_probe`：悬停 → 等待 → 比较 → 移开，识别"悬停才出现"的控件
- `vision_list`：模板/基线清单 + 运行统计（calls / failures / retries / failure_rate）
- 工具总数 **31 → 57**

### Added — 应用生命周期
- `appkit.launch`（走 Explorer shell，规避 Electron 静默秒退）
- `appkit.wait_window` / `appkit.exit_app`（关窗 ≠ 退出，托盘进程显式结束）
- `appkit.activate`（AttachThreadInput 强攻前台，SetForegroundWindow 常被拒）

### Added — 安全
- 急停：`panic.PanicSwitch`（1.5 s 内连按两次 ESC 立即硬停，粘住不复位）
- `panic_watch.py`：进程外看守，触发即杀掉所有自动化进程
- 鼠标接管授权闸门：GUI 插件 `@local/dsh-mouse-permission`（灰色 = 无权限 / 绿色 = 可接管）
  + 只读检查器 `mouse_permission.py`（退出码 0 / 2 / 3）

### Added — 工程保障
- 64 项不变量测试，系统 Python 与 venv Python 双跑全绿
- `doctor.py` 六组体检（身份 / 显示 / 输入 / 驱动 / 补丁 / 记忆库）
- `diag_input.py`：用"TextEditor打字 + 剪贴板回读"当唯一可信判据
- `clean.py`：白名单清理临时文件，不碰宏、补丁、用户目录
- `recipes/`：每个已验证应用一份配方（ChatClient / 某ChatApp / GamePlatform / SecurityApp / TextEditor / VideoClient / MusicClient）
- `_patched/reapply.py`：重装依赖后一键重放所有补丁

### Fixed
- `_patched/appkit.py` 与安装副本漂移（旧版 14,653 B 缺评分匹配、启动前校验、`activate`）→ 已同步并留备份
- 补丁脚本全部改为"先 assert 旧片段存在再替换"，避免静默失效
- 截图变化检测默认遮掉底部 60 px，否则任务栏时钟会让静止画面被判成一直在变

### Known limitations
- 仅在 Windows 11 验证；DPI 150% 下必须 `SetProcessDpiAwareness(2)`
- 授权闸门的状态存在浏览器本地（客户端无法直连 Host），agent 通过读界面文字判定
- 第三层（逆向）默认关闭，需要逐次授权

"""dataset/explore.py — 随机游走采集（P2-10，weak-semantic 轨迹）

依据：ScaleCUA 的 ablation 显示「无目标的随机游走片段」对导航能力有实际贡献
（WebArena-Lite-v2 8.4 → 14.3），而且规则驱动的游走比让 VLM 自己探索覆盖面更广。

安全边界（硬编码，不靠自觉）：
  · 只调用 registry 里 read_only=True 的工具
  · 再排除元工具（dataset_*/housekeeping/control_*/trace/find_element）
  · 参数一律空字典 —— 不点、不输入、不改任何状态
"""

from __future__ import annotations

import random
import time

from . import label_scope, writer

EXCLUDE = {
    "housekeeping", "control_status", "control_claim", "trace",
    "dataset_status", "dataset_query", "dataset_promote", "dataset_export",
    "dataset_triage", "dataset_explore", "capture_config", "set_config",
}


def candidates() -> list:
    """可安全游走的只读工具名。"""
    from computer_mcp import tool_registry as R

    return sorted(
        name for name, spec in R.TOOLS.items()
        if spec.read_only and name not in EXCLUDE
    )


def run(steps: int = 12, interval_ms: int = 400, seed: int | None = None) -> dict:
    """随机游走 N 步；每步都是只读观察，样本自动被 tee 记下并打 explore 标签。"""
    import asyncio

    from computer_mcp import mcp as M

    pool = candidates()
    if not pool:
        return {"ok": False, "error": "没有可用的只读工具"}
    rng = random.Random(seed)
    before = writer.stats()["episodes_total"]
    used, failed = {}, 0
    t0 = time.perf_counter()

    async def _walk():
        nonlocal failed
        for _ in range(max(1, int(steps))):
            name = rng.choice(pool)
            used[name] = used.get(name, 0) + 1
            try:
                await M.call_tool(name, {})
            except Exception:                            # noqa: BLE001
                failed += 1
            if interval_ms:
                await asyncio.sleep(max(0, int(interval_ms)) / 1000.0)

    def _thread_main():
        # 关键 1：本函数常常是被 call_tool 在**已经在跑的事件循环**里调用的，
        #         直接用 asyncio.run 会报 "coroutine was never awaited"，
        #         所以放到独立线程里给它一个自己的 loop。
        # 关键 2：label_scope 用的是 threading.local，必须**在新线程里**开作用域，
        #         否则样本拿不到 explore 标签。
        with label_scope(["explore", "weak-semantic"]):
            asyncio.run(_walk())

    import threading

    th = threading.Thread(target=_thread_main, name="dataset-explore")
    th.start()
    th.join()

    after = writer.stats()["episodes_total"]
    return {"ok": True, "steps": int(steps), "tools_used": used,
            "failures": failed, "episodes_before": before,
            "episodes_after": after, "recorded": after - before,
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "labels": ["explore", "weak-semantic"]}

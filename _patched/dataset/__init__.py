"""dataset/ — 训练数据分区（Z6）

每次工具调用被路由层的一个 tee 记成一条 episode（JSONL），用于：
  · 成功轨迹 → 坐标/时序校准集
  · 失败轨迹 → 回归用例（R7）
  · 异常轨迹 → 看门狗预算表

硬约束：
  · **单向**：只被写，不被运行时读取（避免"改样本 → 改行为"）
  · 默认只记元数据，不抓屏（`config.json` 的 frames 打开才抓）
  · 剪贴板、键盘原文永不采集
  · 任何异常都在本模块内吞掉，绝不影响工具调用
"""

from __future__ import annotations

import contextlib
import threading
import time
import traceback

from . import schema, writer

__all__ = ["enabled", "record", "tee", "status", "config"]


def config() -> dict:
    return writer.load_config()


def enabled() -> bool:
    return bool(config().get("enabled", True))


def status() -> dict:
    cfg = config()
    st = writer.stats()
    return {
        "success": True,
        "enabled": bool(cfg.get("enabled", True)),
        "frames": bool(cfg.get("frames", False)),
        "root": str(writer.ROOT),
        "episodes_today": st["episodes_today"],
        "episodes_total": st["episodes_total"],
        "bytes_by_day": st["bytes_by_day"],
        "last_episode": st["last_episode"],
        "zones_seen": st["zones_seen"],
    }


def record(tool: str, arguments, zone: str, result_text: str | None,
           ok: bool | None, latency_ms: float, error: str | None = None) -> None:
    """写一条 episode。任何异常都吞掉。"""
    try:
        if not enabled():
            return
        ep = schema.build_episode(tool=tool, arguments=arguments, zone=zone,
                                  result_text=result_text, ok=ok,
                                  latency_ms=latency_ms, error=error,
                                  labels=current_labels())
        writer.append_episode(ep)
    except Exception:                                   # noqa: BLE001
        if config().get("debug"):
            traceback.print_exc()


async def tee(name: str, arguments, call, zone_lookup) -> object:
    """包住一次工具调用：执行 → 采样 → 原样返回结果。"""
    t0 = time.perf_counter()
    ok, err, text = None, None, None
    try:
        out = await call()
        text = schema.text_of(out)
        ok = schema.ok_of(text)
        return out
    except BaseException as exc:                        # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            record(name, arguments, zone_lookup(name),
                   text, ok, (time.perf_counter() - t0) * 1000.0, err)
        except Exception:                               # noqa: BLE001
            pass


# ── P2-10：标签作用域 ────────────────────────────────────────────────
# 让「探索采集」期间的每条样本都带上 explore 标签，而不用改 tee 的签名。
_TLS = threading.local()


@contextlib.contextmanager
def label_scope(labels):
    prev = getattr(_TLS, "labels", None)
    _TLS.labels = list(labels or [])
    try:
        yield
    finally:
        _TLS.labels = prev


def current_labels():
    return list(getattr(_TLS, "labels", None) or [])

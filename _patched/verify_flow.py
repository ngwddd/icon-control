"""verify_flow.py — 分级验证（v0.2）

为什么需要它：v0.1 里"验证"散落在每个脚本里，谁写谁验、标准不一，
于是出现过"全 5 难度一口气上，失败了不知道是哪一环坏了"这种事。

`verify_flow` 把验证变成**分级的、留证据的、遇错即停的**流程：

    stages = [
        {"name": "1-界面在不在", "assert": [{"kind": "text", "query": "设置"}]},
        {"name": "2-目标控件出现", "assert": [{"kind": "template", "name": "btn"}]},
        {"name": "3-动作生效",     "assert": [{"kind": "baseline", "name": "grid", "changed": True}]},
        {"name": "4-结果落盘",     "assert": [{"kind": "file", "path": "out.txt"}]},
    ]

每级只在上一级通过后才跑；每级记录耗时与每条断言的**证据**（OCR 到的文字片段、
模板置信度、基线 diff、文件大小）。最后返回结构化报告，可写盘留档。

支持的断言 kind：
    text      区域 OCR 里是否出现 query（去空格 + 最长公共子串容错）
    template  模板是否命中（vision_state.match_template）
    baseline  区域偏离基线是否超过阈值（vision_state.diff_baseline）
    stable    区域连采多次是否稳定（vision_state.sample_stable）
    file      文件是否存在 + 可选内容包含

设计取向：**只做验证，不做动作**。动作交给 macro_run / batch 等既有工具，
这样"做什么"和"验什么"分开，报告里能清楚看到"动作做了但没生效"还是"根本没做"。
"""

from __future__ import annotations

import os
import re
import time

NORM = lambda s: re.sub(r"\s+", "", str(s or ""))


def _lcs_len(a: str, b: str) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ch in a:
        cur = [0] * (len(b) + 1)
        for j, bc in enumerate(b, 1):
            if ch == bc:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _check_text(spec: dict) -> dict:
    from computer_mcp import ocr_ext

    query = NORM(spec.get("query"))
    region = spec.get("region")
    hwnd = spec.get("hwnd")
    absent = bool(spec.get("absent", False))
    if not query:
        return {"ok": False, "detail": "缺少 query"}

    res = ocr_ext.ocr_read(region=region, hwnd=None if region else hwnd, max_lines=120,
                           upscale=float(spec.get("upscale", 1.5)),
                           boost=bool(spec.get("boost", True)))
    lines = [NORM(ln.get("text")) for ln in (res.get("lines") or [])]
    hit = any(query in h for h in lines)
    if not hit:                      # 允许 OCR 错字：最长公共子串占比够也算命中
        share = max((_lcs_len(query, h) / max(1, len(query)) for h in lines), default=0.0)
        hit = share >= float(spec.get("min_lcs_share", 0.6))
    ok = (not hit) if absent else hit
    return {"ok": ok, "detail": {"query": query, "absent": absent, "hit": hit,
                                 "sample": lines[:6]}}


def _check_template(spec: dict) -> dict:
    from computer_mcp import vision_state as vs

    name = str(spec.get("name") or spec.get("template") or "")
    absent = bool(spec.get("absent", False))
    if not name:
        return {"ok": False, "detail": "缺少 name"}
    r = vs.match_template(name, region=spec.get("region"), hwnd=spec.get("hwnd"),
                          confidence=float(spec.get("confidence", 0.8)))
    if not r.get("success"):
        return {"ok": False, "detail": r}
    found = bool(r.get("found"))
    return {"ok": (not found) if absent else found,
            "detail": {"found": found, "score": r.get("score"), "at": r.get("center")}}


def _check_baseline(spec: dict) -> dict:
    from computer_mcp import vision_state as vs

    name = str(spec.get("name") or "")
    if not name:
        return {"ok": False, "detail": "缺少 name"}
    want_changed = bool(spec.get("changed", True))
    r = vs.diff_baseline(name, region=spec.get("region"), hwnd=spec.get("hwnd"),
                         threshold=float(spec.get("threshold", 8.0)))
    if not r.get("success"):
        return {"ok": False, "detail": r}
    return {"ok": bool(r.get("changed")) == want_changed,
            "detail": {"diff": r.get("diff"), "changed": r.get("changed"),
                       "threshold": r.get("threshold"), "want_changed": want_changed}}


def _check_stable(spec: dict) -> dict:
    from computer_mcp import vision_state as vs

    r = vs.sample_stable(region=spec.get("region"), hwnd=spec.get("hwnd"),
                         times=int(spec.get("times", 2)), gap_ms=int(spec.get("gap_ms", 200)))
    if not r.get("success"):
        return {"ok": False, "detail": r}
    want = bool(spec.get("stable", True))
    return {"ok": bool(r.get("stable")) == want,
            "detail": {"stable": r.get("stable"), "hashes": r.get("hashes")}}


def _check_file(spec: dict) -> dict:
    path = os.path.expanduser(str(spec.get("path") or ""))
    if not path:
        return {"ok": False, "detail": "缺少 path"}
    exists = os.path.isfile(path)
    info: dict = {"path": path, "exists": exists}
    if exists:
        try:
            info["size"] = os.path.getsize(path)
        except OSError:
            info["size"] = None
    ok = exists
    contains = spec.get("contains")
    if ok and contains:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            info["contains"] = str(contains) in body
            ok = bool(info["contains"])
        except Exception as exc:
            info["read_error"] = str(exc)
            ok = False
    return {"ok": ok, "detail": info}


KINDS = {
    "text": _check_text,
    "template": _check_template,
    "baseline": _check_baseline,
    "stable": _check_stable,
    "file": _check_file,
}


def run(stages: list, stop_on_fail: bool = True, report_path: str | None = None) -> dict:
    """按顺序跑分级验证。返回结构化报告（含每级证据）。"""
    t_all = time.time()
    report: dict = {"ok": True, "stages": [], "failed_stage": None,
                    "failed_stages": [], "elapsed_ms": 0}
    stages = stages or []

    for idx, stage in enumerate(stages):
        name = str(stage.get("name") or f"stage-{idx + 1}")
        wait_ms = int(stage.get("wait_ms", 0) or 0)
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)

        t0 = time.time()
        checks = []
        stage_ok = True
        for spec in (stage.get("assert") or stage.get("checks") or []):
            kind = str(spec.get("kind") or spec.get("type") or "").lower()
            fn = KINDS.get(kind)
            if fn is None:
                checks.append({"kind": kind, "ok": False, "detail": f"未知断言类型 {kind!r}"})
                stage_ok = False
                continue
            try:
                res = fn(spec)
            except Exception as exc:
                res = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
            checks.append({"kind": kind, "ok": bool(res.get("ok")), "detail": res.get("detail")})
            if not res.get("ok"):
                stage_ok = False

        report["stages"].append({
            "index": idx + 1,
            "name": name,
            "ok": stage_ok,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "checks": checks,
        })
        if not stage_ok:
            report["ok"] = False
            report["failed_stages"].append(name)
            # failed_stage 记**第一处**失败（多级失败时最有诊断价值的那个）
            if report["failed_stage"] is None:
                report["failed_stage"] = name
            if stop_on_fail:
                break

    report["elapsed_ms"] = int((time.time() - t_all) * 1000)
    report["ran"] = len(report["stages"])
    report["planned"] = len(stages)

    if report_path:
        try:
            import json
            p = os.path.expanduser(report_path)
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
            report["report_path"] = p
        except Exception as exc:
            report["report_error"] = str(exc)

    return report

"""retention.py — 保留策略 / 自动清扫（v0.5）

用户原话：「你要考虑我以后这个鼠标助手跑起来不会产生垃圾文件。」

问题不是「有临时文件」，而是**没人负责删**：
    · `_draw/` 每次 snapshot/截图都新增一张，长期几千张
    · `recordings/` 每次 record 一个目录，几十 MB
    · `%TEMP%` 里 `t_*.py`、`vh-*` 这类脚本/目录，崩一次留一堆
    · `vision/baselines` 是"区域基线"，会随时间越积越多

设计原则：
    ① **资产不动**：`macros/`、`recipes/`、`vision/templates`、`_patched/` 一律不删
    ② **按需保留**：可用文件数 / 总字节 / 天龄三个上限，先删最老的
    ③ **自己负责**：清扫在写入后自动跑（snapshot / record / daemon 启动），
       也提供一个 `housekeeping` 工具手动看/清
    ④ **只碰自己的**：%TEMP% 只认 `t_*.py`、`vh-*`、`dsh-*` 前缀

用法：
    from computer_mcp import retention
    retention.sweep()                 # 清扫
    retention.usage()                 # 只看用量，不删
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

HOME = Path.home()
# 工具根目录以 _draw 的位置为准更稳（venv 布局各不相同）
DRAW_ROOT = HOME / ".dsh" / "tools" / "desktop-mcp"

# 每个区域的保留策略：files=最多文件数, mb=最多总字节, days=最老天龄
# None 表示该维度不限制。资产类目录**不列在这里**，就永远不会被删。
POLICY: dict[str, dict] = {
    "_draw": {"files": 80, "mb": 80, "days": 3, "recursive": True},
    "recordings": {"files": None, "mb": 300, "days": 7, "recursive": True,
                   "dirs": 10},
    "vision/baselines": {"files": 40, "mb": None, "days": 30, "recursive": False},
}
# 注意：`templates/`（自学的模板图）是**资产**，和 macros 同级，不进 POLICY。
# 上一版我把它写进 POLICY 还写进 KEEP，策略自相矛盾 —— 测试当场抓出来了。

# 绝不删除（资产）
KEEP = ("macros", "recipes", "templates", "vision/glyphs.json", "_patched")

# %TEMP% 里属于自己的东西。
# ⚠️ 绝不要把 "dsh-" 放进来：那是 DSH 宿主自己的临时目录
# （实测有 dsh-spill-* / dsh-subprocess-* / dsh-workspace-changes-*），
# 删了会影响运行中的会话。
TEMP_PREFIXES = ("vh-", "canity_")
TEMP_FILE_GLOBS = ("t_*.py", "t_*.json", "_dsh_*.py", "patch_*.py")


def _dir_stats(files: list[Path]) -> tuple[int, int]:
    return len(files), sum(f.stat().st_size for f in files if f.is_file())


def usage(root: Path | None = None) -> dict:
    """各区域当前占用（不删任何东西）。"""
    root = Path(root or DRAW_ROOT)
    out: dict[str, dict] = {}
    for rel in POLICY:
        d = root / rel
        if not d.exists():
            out[rel] = {"files": 0, "bytes": 0, "exists": False}
            continue
        files = [f for f in d.rglob("*") if f.is_file()] if POLICY[rel].get("recursive") \
            else [f for f in d.glob("*") if f.is_file()]
        n, size = _dir_stats(files)
        out[rel] = {"files": n, "bytes": size, "exists": True,
                    "mb": round(size / 1048576, 1)}
    total = sum(v.get("bytes", 0) for v in out.values())
    return {"areas": out, "total_mb": round(total / 1048576, 2),
            "root": str(root)}


def _prune_one(path: Path, rule: dict, now: float) -> tuple[list[str], int]:
    """按策略删一个目录里的文件，返回 (删掉的, 释放字节)。只删最老的。"""
    removed: list[str] = []
    freed = 0
    if not path.is_dir():
        return removed, freed
    files = [f for f in (path.rglob("*") if rule.get("recursive") else path.glob("*"))
             if f.is_file()]
    if not files:
        return removed, freed
    files.sort(key=lambda f: f.stat().st_mtime)          # 最老的先删

    def _del(f: Path) -> None:
        nonlocal freed
        try:
            size = f.stat().st_size
            f.unlink()
            removed.append(str(f))
            freed += size
        except Exception:
            pass

    # ① 天龄
    days = rule.get("days")
    if days:
        cutoff = now - days * 86400
        for f in list(files):
            try:
                if f.stat().st_mtime < cutoff:
                    _del(f)
                    files.remove(f)
            except Exception:
                continue

    # ② 总字节
    cap_mb = rule.get("mb")
    if cap_mb:
        cap = cap_mb * 1048576
        total = sum(f.stat().st_size for f in files if f.is_file())
        while total > cap and files:
            f = files.pop(0)
            try:
                total -= f.stat().st_size
            except Exception:
                continue
            _del(f)

    # ③ 文件数
    cap_n = rule.get("files")
    if cap_n:
        while len(files) > cap_n:
            _del(files.pop(0))

    # ④ 子目录数（recordings 这种一次一个目录的）
    cap_dirs = rule.get("dirs")
    if cap_dirs and path.is_dir():
        subs = sorted([d for d in path.iterdir() if d.is_dir()],
                      key=lambda d: d.stat().st_mtime)
        while len(subs) > cap_dirs:
            d = subs.pop(0)
            try:
                size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                shutil.rmtree(d, ignore_errors=True)
                removed.append(str(d))
                freed += size
            except Exception:
                pass

    return removed, freed


def sweep(root: Path | None = None, dry_run: bool = False) -> dict:
    """按 POLICY 清扫工具自己的目录。资产目录不在 POLICY 里，永远不碰。"""
    root = Path(root or DRAW_ROOT)
    now = time.time()
    removed: list[str] = []
    freed = 0
    if dry_run:
        # 只报告"会删什么"，用临时目录试算
        planned: dict[str, int] = {}
        for rel, rule in POLICY.items():
            d = root / rel
            if not d.is_dir():
                continue
            files = [f for f in (d.rglob("*") if rule.get("recursive") else d.glob("*"))
                     if f.is_file()]
            cap_n = rule.get("files")
            if cap_n and len(files) > cap_n:
                planned[rel] = len(files) - cap_n
        return {"dry_run": True, "would_trim": planned, "root": str(root)}

    for rel, rule in POLICY.items():
        r, f = _prune_one(root / rel, rule, now)
        removed += r
        freed += f
    return {"removed": removed, "removed_count": len(removed),
            "freed_bytes": freed, "freed_mb": round(freed / 1048576, 2),
            "root": str(root)}


def sweep_temp(max_age_hours: float = 6.0, dry_run: bool = False) -> dict:
    """清 %TEMP% 里自己的东西（本工具与它的脚本留下的）。别的程序一概不碰。"""
    base = Path(tempfile.gettempdir())
    cutoff = time.time() - max_age_hours * 3600
    removed: list[str] = []
    freed = 0

    for entry in base.iterdir():
        try:
            mine = (entry.is_dir() and entry.name.startswith(TEMP_PREFIXES))
        except Exception:
            continue
        if not mine:
            continue
        try:
            if entry.stat().st_mtime > cutoff:
                continue
            size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            if not dry_run:
                shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry.name)
            freed += size
        except Exception:
            continue

    for pat in TEMP_FILE_GLOBS:
        for f in base.glob(pat):
            try:
                if not f.is_file() or f.stat().st_mtime > cutoff:
                    continue
                size = f.stat().st_size
                if not dry_run:
                    f.unlink(missing_ok=True)
                removed.append(f.name)
                freed += size
            except Exception:
                continue

    return {"removed": removed[:200], "removed_count": len(removed),
            "freed_bytes": freed, "freed_mb": round(freed / 1048576, 2),
            "max_age_hours": max_age_hours, "dry_run": dry_run}


def sweep_all(dry_run: bool = False) -> dict:
    """工具目录 + %TEMP% 一起清（写入后自动调用的就是它）。"""
    a = sweep(dry_run=dry_run)
    b = sweep_temp(dry_run=dry_run)
    return {"tool": a, "temp": b,
            "freed_mb": round((a.get("freed_bytes", 0) + b.get("freed_bytes", 0)) / 1048576, 2)}

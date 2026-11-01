"""importers/hf_grounding.py — HuggingFace grounding 数据集骨架（P1-8）。

grounding 样本（截图 + bbox + 标签）→ 我们的 episode：
    bbox 中心点 → args{x,y}；bbox 尺寸 → meta；图幅 → target.screen_w/h

注意：
  · 需要 `datasets` 库；没装就抛 RuntimeError（不静默跳过）
  · **先确认许可**再跑，许可证写进 manifest
  · 只产出 click 样本，不产出 cases
"""

from __future__ import annotations

from . import base


def load(repo: str, split: str = "train", limit: int = 500,
         source: str = "hf", license_: str = "UNVERIFIED") -> list:
    try:
        from datasets import load_dataset
    except Exception as exc:                             # noqa: BLE001
        raise RuntimeError("需要 pip install datasets") from exc

    ds = load_dataset(repo, split=split, streaming=True)
    eps = []
    for i, row in enumerate(ds):
        if i >= limit:
            break
        bbox = row.get("bbox") or row.get("box")
        if not bbox or len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
        w = int(row.get("width") or row.get("image_width") or 0)
        h = int(row.get("height") or row.get("image_height") or 0)
        if not w:
            img = row.get("image")
            w = getattr(img, "width", 0) or 0
            h = getattr(img, "height", 0) or 0
        ep = base.to_episode(
            source=source,
            key=f"{repo}-{i}",
            tool="click",
            zone="Z3",
            args={"x": int((x1 + x2) / 2), "y": int((y1 + y2) / 2)},
            screen=(w, h),
            verdict="success",
            license_=license_,
            note=f"bbox={int(x2 - x1)}x{int(y2 - y1)}",
        )
        eps.append(ep)
    return eps

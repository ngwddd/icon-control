"""dataset/importers/ — 外部数据集导入（P1-8）。

每个来源一个模块，统一输出 base.to_episode 的结构；
落盘到 dataset/raw/external/<source>/，并记进 importers/manifest.json。

规则见 base.py 顶部：打 external 标签、绝不写 cases、坐标带分辨率。
"""

from . import base, hf_grounding, local_fixture  # noqa: F401

__all__ = ["base", "local_fixture", "hf_grounding"]

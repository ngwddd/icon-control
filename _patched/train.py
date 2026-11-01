"""train.py — 兼容层（R10 起真实模块叫 conveyor.py）

为什么改名：`train` 与「训练数据」（dataset/ 分区）在同一个包里撞名，
而且这个模块跟机器学习训练毫无关系 —— 它是「一列不停的车」：
三个轮子（入帧 / 处理 / 出）+ 看门狗 + 轨道执行器。

本文件只做**全量再导出**（含下划线开头的私有名），让旧的
`from computer_mcp import train as T` 继续可用。新代码请写 conveyor。
"""

from __future__ import annotations

import sys as _sys

from computer_mcp import conveyor as _conveyor

_this = _sys.modules[__name__]
for _k, _v in vars(_conveyor).items():
    if not _k.startswith("__"):
        setattr(_this, _k, _v)

del _k, _v, _this, _sys
__all__ = [n for n in dir(_conveyor) if not n.startswith("__")]

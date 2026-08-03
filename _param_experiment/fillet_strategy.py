"""榫槽 fillet 圆角策略 — 角色语义驱动，保证圆角始终正确。

核心思想：
  不给 fillet_sketch 传裸顶点索引（绑定点数结构，换结构即失效），
  而是给每个轮廓点标注 construction_role，fillet 规则按"角色"匹配顶点。
  这样无论齿数/点数如何变化，角色→需要圆角的顶点始终正确。

角色定义（上侧，下侧镜像）：
  mouth            口部
  neck             齿根/颈部（外斜面起点、内斜面端）
  tip_flank_top    齿顶外斜面端
  tip_platform_end 齿顶平台端
  connector        齿间连接线端
  bottom_flare     槽底外扩角
  bottom_platform  槽底平台端
  root             根部

用法:
  roles = annotate_roles(teeth_count)
  targets = compute_fillet_targets(roles, teeth_count,
              tip_fillet=0.8, neck_fillet=0.5, bottom_fillet=0.6)
  # targets = {'tip': [2,3,6,7,...], 'neck': [1,4,8,...], 'bottom': [...]}
"""

from __future__ import annotations

import math


def annotate_roles(teeth_count: int) -> list[str]:
    """标注上侧每点的角色（长度 = 5 + 4*teeth_count）。"""
    n = teeth_count
    roles = ["mouth"]            # [0]
    roles.append("neck")         # [1] 齿0外斜面起点
    for i in range(n):
        # 齿 i 独占 4 点：外斜面顶 / 齿顶平台端 / 内斜面端 / 连接线端
        roles.append("tip_flank_top")     # 2+4i
        roles.append("tip_platform_end")  # 3+4i
        roles.append("neck")              # 4+4i 内斜面端
        roles.append("connector")         # 5+4i 连接线端
    # 底部 3 点
    roles.append("bottom_flare")     # 5+4n
    roles.append("bottom_platform")  # 6+4n
    roles.append("root")             # 7+4n
    assert len(roles) == 5 + 4 * n, f"角色数 {len(roles)} != 5+4n"
    return roles


def compute_fillet_targets(
    roles: list[str],
    teeth_count: int,
    tip_fillet: float | None = None,
    neck_fillet: float | None = None,
    connector_fillet: float | None = None,
    bottom_fillet: float | None = None,
) -> dict[str, list[int]]:
    """按角色规则选出需要圆角的顶点索引（早期策略，权威见 fillet_corners.py）。

    **注**：本模块为早期角色策略，权威实现已演进至 `fillet_corners.py`
    （FILLET_ROLES 含 connector 与 bottom_platform）。此函数保持同步：
      - tip: 齿顶两端（tip_flank_top + tip_platform_end）→ 用 tip_fillet
      - neck: 齿根/颈部（neck 角色，含齿0起点和各内斜面端）→ 用 neck_fillet
      - connector: 齿间连接线端 → 用 connector_fillet
      - bottom: 底部（bottom_flare + bottom_platform + root）→ 用 bottom_fillet

    若某 fillet 半径未提供（None），则该类不圆角。
    """
    n_upper = 5 + 4 * teeth_count
    if len(roles) < n_upper:
        raise ValueError(f"roles 长度 {len(roles)} 不足 {n_upper}")
    upper = roles[:n_upper]
    targets: dict[str, list[int]] = {}
    if tip_fillet is not None:
        targets["tip"] = [i for i, r in enumerate(upper) if r in ("tip_flank_top", "tip_platform_end")]
    if neck_fillet is not None:
        # neck 角色：齿0起点[1] + 各内斜面端。但排除根部的 root（不同角色）
        targets["neck"] = [i for i, r in enumerate(upper) if r == "neck"]
    if connector_fillet is not None:
        targets["connector"] = [i for i, r in enumerate(upper) if r == "connector"]
    if bottom_fillet is not None:
        targets["bottom"] = [i for i, r in enumerate(upper) if r in ("bottom_flare", "bottom_platform", "root")]
    return targets


def full_indices(indices: list[int], teeth_count: int) -> list[int]:
    """把上侧索引扩展为完整（含下侧镜像）。

    上侧点数 = 5+4n，总 = 2*(5+4n)。
    下侧点 i 对应上侧 (5+4n-1-i) 的镜像。
    """
    n_upper = 5 + 4 * teeth_count
    upper_set = set(indices)
    # 下侧镜像：上侧点 k 的镜像在总序列中的索引 = n_upper + (n_upper-1-k)
    out = list(indices)
    for k in upper_set:
        out.append(n_upper + (n_upper - 1 - k))
    # 去重（口部点0 和 根部可能共享）
    seen = set()
    uniq = []
    for i in out:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    return uniq


def apply_fillet_plan(pts: list, teeth_count: int, plan: dict) -> dict:
    """把圆角计划附加到点数据（标注每个点是否/在哪类圆角）。"""
    roles = annotate_roles(teeth_count)
    n_upper = 5 + 4 * teeth_count
    upper = roles[:n_upper]
    out = []
    for i, pt in enumerate(pts):
        d = dict(pt)
        if i < n_upper:
            d["role"] = upper[i]
            d["fillet"] = []
            for cls in ("tip", "neck", "bottom"):
                if i in plan.get(cls, []):
                    d["fillet"].append(cls)
        else:
            # 下侧镜像：role 与上侧对称点相同
            mirror = n_upper - 1 - (i - n_upper)
            d["role"] = upper[mirror]
            d["fillet"] = []
            for cls in ("tip", "neck", "bottom"):
                if mirror in plan.get(cls, []):
                    d["fillet"].append(cls)
        out.append(d)
    return out


if __name__ == "__main__":
    # 自检：2/3/4 齿角色与索引
    for n in (2, 3, 4):
        roles = annotate_roles(n)
        plan = compute_fillet_targets(roles, n, tip_fillet=0.8, neck_fillet=0.5,
                                      connector_fillet=0.5, bottom_fillet=0.6)
        print(f"--- {n}齿 (上侧{5+4*n}点) ---")
        for i, r in enumerate(roles):
            marks = []
            for cls, idxs in plan.items():
                if i in idxs:
                    marks.append(cls)
            print(f"  [{i:2d}] {r:16s} {'<- '+','.join(marks) if marks else ''}")
        full_tip = full_indices(plan["tip"], n)
        print(f"  齿顶圆角完整索引: {full_tip}")
        print()

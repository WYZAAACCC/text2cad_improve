"""P0-2 论文 32 设计族种子定义（确定性数据，不触发 LLM）。

论文附件三：6 类 32 族 = 基础盘 4(3训/0验/1测) + 孔阵列盘 5(3/1/1) + 环槽盘 5(3/1/1)
+ 标准榫槽盘 8(5/1/2) + 耦合盘 6(4/1/1) + 复杂轮缘盘 4(2/0/2)。

每族定义：
  - category：basic / hole / groove / slot / coupled / complex_rim
  - split：train / val / holdout（论文分配）
  - od/bore/thick/hub/rim：主体尺寸标量（mm，落在论文参数范围）
  - features：类别特征参数（孔/环槽/榫槽）

需求文本由 _family_text() 按类别确定性生成（run_batch 候选文本来源）。
设计族匹配由 run_enrich 读 family_ref.json 显式标注（候选生成时写入），
参数向量匹配仅作榫槽盘兜底（G1-G5 保留）。
"""

from __future__ import annotations

# (od 外径, bore 中心孔, thick 轴向最大厚, hub 轮毂半厚, rim 轮缘半厚) —— mm
# 榫槽：(slots 槽数, teeth 齿数, R 分布半径, depth 槽深, throat 喉半宽, fr 齿根圆角)
# 孔：(holes 孔数, pcd 孔分布半径, hdia 孔径) 环槽：(grooves 环槽数, gw 槽宽, gd 槽深)

_BASE = {"od": 500, "bore": 120, "thick": 76, "hub": 38, "rim": 30}          # ≈ KT787
_BASE_SMALL = {"od": 460, "bore": 110, "thick": 70, "hub": 36, "rim": 28}
_BASE_LARGE = {"od": 600, "bore": 150, "thick": 90, "hub": 45, "rim": 38}
_BASE_XL = {"od": 700, "bore": 180, "thick": 110, "hub": 52, "rim": 44}

# 榫槽默认（t2 槽 slot2d 自然结构）：mouth=8（槽口16mm）、depth=21.2（N2 自然深度，不撑满榫底）、
# fr=0.97（fr_limit）。各族按 teeth 覆盖 depth/throat（t3 m6→22.4、t4 m7→28.1）。
SLOT_DEFAULTS = {"slots": 60, "teeth": 2, "R": 215, "depth": 21.2, "throat": 8.0, "fr": 0.97}

DESIGN_FAMILIES: dict[str, dict] = {
    # ── 1. 基础轮毂-腹板-轮缘盘（4：D01-D03 train, D04 holdout）─────────────────
    "D01": {"form": "standard", "category": "basic", "split": "train", **_BASE, "features": {}},
    "D02": {"form": "thin_web", "category": "basic", "split": "train", **_BASE_SMALL, "features": {}},
    "D03": {"form": "thick_rim", "category": "basic", "split": "train", **_BASE_LARGE, "features": {}},
    "D04": {"form": "large_hub", "category": "basic", "split": "holdout", **_BASE_XL, "features": {}},
    # ── 2. 中心孔与周向孔阵列盘（5：D05-D07 train, D08 val, D09 holdout）────────
    "D05": {"form": "standard", "category": "hole", "split": "train", **_BASE,
            "features": {"holes": 16, "pcd": 170, "hdia": 14}},
    "D06": {"form": "thin_web", "category": "hole", "split": "train",
            **{**_BASE, "od": 520}, "features": {"holes": 24, "pcd": 176, "hdia": 12}},
    "D07": {"form": "thick_rim", "category": "hole", "split": "train",
            **{**_BASE, "od": 560, "thick": 82}, "features": {"holes": 12, "pcd": 160, "hdia": 16}},
    "D08": {"form": "large_hub", "category": "hole", "split": "val", **{**_BASE_LARGE, "od": 600},
            "features": {"holes": 30, "pcd": 214, "hdia": 10}},
    "D09": {"form": "conical", "category": "hole", "split": "holdout", **{**_BASE_LARGE, "od": 640},
            "features": {"holes": 20, "pcd": 216, "hdia": 18}},
    # ── 3. 环槽与减重结构盘（5：D10-D12 train, D13 val, D14 holdout）────────────
    # 论文 2.2 减重结构：减重孔/冷却孔/环槽/径向局部切槽/局部减重（腹板环形腔）。
    # 各族特征组合不同 → 族内多样性；pcd/hdia 落在论文范围（孔径 4-26、分布半径 80-310）。
    "D10": {"form": "standard", "category": "groove", "split": "train", **_BASE,
            "features": {"grooves": 1, "gw": 10, "gd": 14, "groove_type": "collar",
                         "lh_holes": 12, "lh_pcd": 175, "lh_hdia": 16}},
    "D11": {"form": "thin_web", "category": "groove", "split": "train", **{**_BASE, "od": 520},
            "features": {"grooves": 2, "gw": 10, "gd": 14, "groove_type": "collar",
                         "cl_holes": 24, "cl_pcd": 176, "cl_hdia": 6}},
    "D12": {"form": "thick_rim", "category": "groove", "split": "train", **{**_BASE, "od": 540},
            "features": {"grooves": 1, "gw": 10, "gd": 20, "groove_type": "collar",
                         "rs_count": 60, "rs_depth": 10, "rs_half_width": 3}},
    "D13": {"form": "large_hub", "category": "groove", "split": "val", **{**_BASE, "od": 560},
            "features": {"grooves": 2, "gw": 10, "gd": 13, "groove_type": "collar",
                         "lh_holes": 16, "lh_pcd": 190, "lh_hdia": 14,
                         "cl_holes": 30, "cl_pcd": 198, "cl_hdia": 5}},
    "D14": {"form": "conical", "category": "groove", "split": "holdout", **{**_BASE, "od": 580},
            "features": {"grooves": 1, "gw": 10, "gd": 16, "groove_type": "collar",
                         "cl_holes": 36, "cl_pcd": 193, "cl_hdia": 5, "cl_pcd2": 204}},
    # ── 4. 标准枞树形榫槽盘（8：D15-D19 train, D20 val, D21-D22 holdout）────────
    "D15": {"form": "standard", "category": "slot", "split": "train", **_BASE,
            # 榫槽 slot2d 自然结构：mouth=8（槽口16mm）、depth=19.8（N2 自然深度，不撑满）、
            # slots=40。N2 比例 neck=[0.84,0.64,0.44]m、卡榫紧凑、连接线短。
            "features": {**SLOT_DEFAULTS, "slots": 40, "depth": 21.2, "throat": 8.0, "fr": 0.97}},
    "D16": {"form": "thin_web", "category": "slot", "split": "train", **_BASE,
            "features": {**SLOT_DEFAULTS, "slots": 48, "depth": 21.2, "throat": 8.0, "fr": 0.97}},
    "D17": {"form": "large_hub", "category": "slot", "split": "train", **_BASE_SMALL,
            "features": {**SLOT_DEFAULTS, "slots": 60, "depth": 18.8, "throat": 7.0, "fr": 0.93}},
    "D18": {"form": "conical", "category": "slot", "split": "train", **_BASE,
            "features": {**SLOT_DEFAULTS, "slots": 60, "depth": 21.2, "throat": 8.0, "fr": 0.97}},
    "D19": {"form": "standard", "category": "slot", "split": "train", **_BASE,
            "features": {**SLOT_DEFAULTS, "slots": 60, "teeth": 3, "depth": 22.4, "throat": 6.0}},
    "D20": {"form": "thick_rim", "category": "slot", "split": "val", **{**_BASE, "od": 540},
            "features": {**SLOT_DEFAULTS, "slots": 72, "teeth": 3, "depth": 22.4, "throat": 6.0}},
    "D21": {"form": "large_hub", "category": "slot", "split": "holdout", **{**_BASE, "od": 580},
            "features": {**SLOT_DEFAULTS, "slots": 84, "teeth": 3, "depth": 22.4, "throat": 6.0}},
    "D22": {"form": "conical", "category": "slot", "split": "holdout", **{**_BASE, "od": 600},
            "features": {**SLOT_DEFAULTS, "slots": 84, "teeth": 4, "depth": 28.1, "throat": 7.0, "R": 230}},
    # ── 5. 榫槽-孔阵列-环槽耦合盘（6：D23-D26 train, D27 val, D28 holdout）─────
    "D23": {"form": "standard", "category": "coupled", "split": "train", **_BASE,
            "features": {**SLOT_DEFAULTS, "slots": 60, "depth": 21.2, "throat": 8.0, "fr": 0.97,
                         "holes": 12, "pcd": 170, "hdia": 12,
                         "grooves": 1, "gw": 10, "gd": 9, "groove_type": "collar"}},
    "D24": {"form": "thin_web", "category": "coupled", "split": "train", **{**_BASE, "od": 520},
            "features": {**SLOT_DEFAULTS, "slots": 48, "depth": 21.2, "throat": 8.0, "fr": 0.97,
                         "holes": 16, "pcd": 176, "hdia": 10,
                         "grooves": 1, "gw": 10, "gd": 9, "groove_type": "collar"}},
    "D25": {"form": "thick_rim", "category": "coupled", "split": "train", **{**_BASE, "od": 560},
            "features": {**SLOT_DEFAULTS, "teeth": 3, "depth": 22.4, "throat": 6.0,
                         "holes": 12, "pcd": 166, "hdia": 14,
                         "grooves": 1, "gw": 10, "gd": 14, "groove_type": "collar"}},
    "D26": {"form": "conical", "category": "coupled", "split": "train", **{**_BASE, "od": 540},
            "features": {**SLOT_DEFAULTS, "slots": 68, "depth": 21.2, "throat": 8.0, "fr": 0.97,
                         "holes": 24, "pcd": 182, "hdia": 10,
                         "grooves": 1, "gw": 10, "gd": 10, "groove_type": "collar"}},
    "D27": {"form": "large_hub", "category": "coupled", "split": "val", **{**_BASE, "od": 600},
            "features": {**SLOT_DEFAULTS, "teeth": 3, "depth": 22.4, "throat": 6.0,
                         "holes": 20, "pcd": 208, "hdia": 12,
                         "grooves": 1, "gw": 10, "gd": 9, "groove_type": "collar"}},
    "D28": {"form": "thick_rim", "category": "coupled", "split": "holdout", **{**_BASE, "od": 620},
            "features": {**SLOT_DEFAULTS, "slots": 84, "teeth": 3, "depth": 22.4, "throat": 6.0,
                         "holes": 16, "pcd": 188, "hdia": 16,
                         "grooves": 2, "gw": 10, "gd": 14, "groove_type": "collar"}},
    # ── 6. 复杂轮缘过渡与榫槽组合盘（4：D29-D30 train, D31-D32 holdout）────────
    # 曲线过渡：盘体 web-rim 交界用不同曲线族（transition，论文 2.1 曲线过渡）——
    # D29 S形 / D30 椭圆弧 / D31 幂曲线 / D32 外凸弧，族间过渡结构不同（非仅半径不同）。
    "D29": {"form": "thick_rim", "category": "complex_rim", "split": "train", **{**_BASE, "rim": 40},
            "features": {**SLOT_DEFAULTS, "slots": 60, "teeth": 3, "depth": 22.4, "throat": 6.0, "R": 225,
                         "rim_arc_radius": 20, "transition": "s_curve"}},
    "D30": {"form": "thick_rim", "category": "complex_rim", "split": "train", **{**_BASE, "rim": 36, "od": 560},
            "features": {**SLOT_DEFAULTS, "slots": 72, "teeth": 3, "depth": 22.4, "throat": 6.0, "R": 235,
                         "rim_arc_radius": 24, "transition": "ellipse"}},
    "D31": {"form": "thick_rim", "category": "complex_rim", "split": "holdout", **{**_BASE_LARGE, "rim": 45, "od": 640},
            # 厚轮缘(95mm)榫槽切透：m13/slots44/depth44(切深47%)；过渡幅度 rim_arc_radius=28
            "features": {**SLOT_DEFAULTS, "slots": 44, "teeth": 3, "depth": 44, "throat": 13.0, "fr": 0.65, "R": 250,
                         "rim_arc_radius": 28, "transition": "power"}},
    "D32": {"form": "thick_rim", "category": "complex_rim", "split": "holdout", **{**_BASE_LARGE, "rim": 48, "od": 680},
            # 厚轮缘(95mm)榫槽切透：m10/slots40/depth38(切深40%)；过渡幅度 rim_arc_radius=30
            # t4 大 mouth(12)榫槽使 runtime 崩溃缺 metadata → roundtrip fail；m10 减小计算量
            "features": {**SLOT_DEFAULTS, "slots": 40, "teeth": 4, "depth": 38, "throat": 10.0, "fr": 0.82, "R": 260,
                         "rim_arc_radius": 30, "transition": "arc_out"}},
}

CATEGORY_LABEL = {
    "basic": "轮毂-腹板-轮缘盘体", "hole": "轮毂-腹板-轮缘盘体，带周向安装孔阵列",
    "groove": "轮毂-腹板-轮缘盘体，带环槽", "slot": "轮毂-腹板-轮缘盘体，带枞树形榫槽",
    "coupled": "轮毂-腹板-轮缘盘体，带枞树形榫槽、周向孔阵列与环槽",
    "complex_rim": "轮毂-腹板-轮缘盘体，带厚轮缘与枞树形榫槽",
}


def _n(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _family_text(fam: dict) -> str:
    """按类别确定性生成需求文本（参数显式、措辞对齐 extract_requirements 正则）。"""
    p = [f"生成一个高压涡轮盘参考几何：{CATEGORY_LABEL[fam['category']]}",
         f"外径{fam['od']}mm，中心孔直径{fam['bore']}mm，轴向最大厚度{fam['thick']}mm",
         f"轮毂半厚{fam['hub']}mm，轮缘半厚{fam['rim']}mm"]
    f = fam.get("features") or {}
    if "slots" in f:
        p.append(f"轮缘上{f['slots']}个{f['teeth']}齿枞树形榫槽，分布半径{f['R']}mm，"
                 f"槽深{f['depth']}mm，喉部半宽{_n(f['throat'])}mm，齿根圆角{_n(f['fr'])}mm")
    if "holes" in f:
        p.append(f"周向均布{f['holes']}个安装孔，孔径{f['hdia']}mm，分布半径{f['pcd']}mm")
    if "grooves" in f:
        p.append(f"轮缘内侧{f['grooves']}道环槽，槽宽{f['gw']}mm，槽深{f['gd']}mm")
    if "lh_holes" in f:
        p.append(f"腹板上{f['lh_holes']}个减重孔，孔径{f['lh_hdia']}mm，分布半径{f['lh_pcd']}mm")
    if "cl_holes" in f:
        p.append(f"腹板上{f['cl_holes']}个冷却孔，孔径{f['cl_hdia']}mm，分布半径{f['cl_pcd']}mm"
                 + (f"，第二排分布半径{f['cl_pcd2']}mm" if f.get("cl_pcd2") else ""))
    if "rs_count" in f:
        p.append(f"轮缘外表面{f['rs_count']}个径向局部切槽，切槽深度{f['rs_depth']}mm，"
                 f"槽宽{int(2 * f['rs_half_width'])}mm")
    if "cavity_width" in f:
        p.append(f"腹板处环形减重腔，腔宽{f['cavity_width']}mm，腔深{f['cavity_depth']}mm")
    if f.get("rim_arc_radius"):
        tr_label = {"s_curve": "S形曲线", "ellipse": "椭圆弧", "power": "幂函数曲线",
                    "arc_out": "外凸圆弧", "arc_in": "内凹圆弧"}.get(f.get("transition"), "曲线")
        p.append(f"轮缘与腹板交界采用{tr_label}过渡，过渡幅度{f['rim_arc_radius']}mm")
    return "，".join(p) + "。参考几何，非适航件。"


def build_text(fam: dict) -> str:
    """按设计族 dict 生成需求文本（支持 features 覆盖，run_batch 槽数变体用）。"""
    return _family_text(fam)


def family_text(fam_id: str) -> str:
    return build_text(DESIGN_FAMILIES[fam_id])


def all_families() -> list[str]:
    return sorted(DESIGN_FAMILIES)


if __name__ == "__main__":
    for fid in all_families():
        f = DESIGN_FAMILIES[fid]
        print(f"[{fid}] {f['category']}/{f['split']}")
        print("   ", family_text(fid)[:100], "...")

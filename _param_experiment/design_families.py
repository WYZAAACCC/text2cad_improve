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

SLOT_DEFAULTS = {"slots": 60, "teeth": 2, "R": 215, "depth": 24, "throat": 4.0, "fr": 1.0}

DESIGN_FAMILIES: dict[str, dict] = {
    # ── 1. 基础轮毂-腹板-轮缘盘（4：D01-D03 train, D04 holdout）─────────────────
    "D01": {"category": "basic", "split": "train", **_BASE, "features": {}},
    "D02": {"category": "basic", "split": "train", **_BASE_SMALL, "features": {}},
    "D03": {"category": "basic", "split": "train", **_BASE_LARGE, "features": {}},
    "D04": {"category": "basic", "split": "holdout", **_BASE_XL, "features": {}},
    # ── 2. 中心孔与周向孔阵列盘（5：D05-D07 train, D08 val, D09 holdout）────────
    "D05": {"category": "hole", "split": "train", **_BASE,
            "features": {"holes": 16, "pcd": 210, "hdia": 14}},
    "D06": {"category": "hole", "split": "train",
            **{**_BASE, "od": 520}, "features": {"holes": 24, "pcd": 230, "hdia": 12}},
    "D07": {"category": "hole", "split": "train",
            **{**_BASE, "od": 560, "thick": 82}, "features": {"holes": 12, "pcd": 240, "hdia": 16}},
    "D08": {"category": "hole", "split": "val", **{**_BASE_LARGE, "od": 600},
            "features": {"holes": 30, "pcd": 260, "hdia": 10}},
    "D09": {"category": "hole", "split": "holdout", **{**_BASE_LARGE, "od": 640},
            "features": {"holes": 20, "pcd": 270, "hdia": 18}},
    # ── 3. 环槽与减重结构盘（5：D10-D12 train, D13 val, D14 holdout）────────────
    "D10": {"category": "groove", "split": "train", **_BASE,
            "features": {"grooves": 1, "gw": 12, "gd": 8}},
    "D11": {"category": "groove", "split": "train", **{**_BASE, "od": 520},
            "features": {"grooves": 2, "gw": 16, "gd": 10}},
    "D12": {"category": "groove", "split": "train", **{**_BASE, "od": 540},
            "features": {"grooves": 1, "gw": 20, "gd": 12}},
    "D13": {"category": "groove", "split": "val", **{**_BASE, "od": 560},
            "features": {"grooves": 2, "gw": 24, "gd": 14}},
    "D14": {"category": "groove", "split": "holdout", **{**_BASE, "od": 580},
            "features": {"grooves": 3, "gw": 8, "gd": 6}},
    # ── 4. 标准枞树形榫槽盘（8：D15-D19 train, D20 val, D21-D22 holdout）────────
    "D15": {"category": "slot", "split": "train", **_BASE,
            "features": {**SLOT_DEFAULTS}},
    "D16": {"category": "slot", "split": "train", **_BASE,
            "features": {**SLOT_DEFAULTS, "slots": 48, "depth": 28}},
    "D17": {"category": "slot", "split": "train", **_BASE_SMALL,
            "features": {**SLOT_DEFAULTS, "slots": 60, "throat": 3.5}},
    "D18": {"category": "slot", "split": "train", **_BASE,
            "features": {**SLOT_DEFAULTS, "throat": 3.0, "fr": 1.5}},
    "D19": {"category": "slot", "split": "train", **_BASE,
            "features": {**SLOT_DEFAULTS, "slots": 60, "teeth": 3, "depth": 30}},
    "D20": {"category": "slot", "split": "val", **{**_BASE, "od": 540},
            "features": {**SLOT_DEFAULTS, "slots": 72, "teeth": 3, "depth": 32}},
    "D21": {"category": "slot", "split": "holdout", **{**_BASE, "od": 580},
            "features": {**SLOT_DEFAULTS, "slots": 84, "teeth": 3, "depth": 36}},
    "D22": {"category": "slot", "split": "holdout", **{**_BASE, "od": 600},
            "features": {**SLOT_DEFAULTS, "slots": 96, "teeth": 4, "depth": 40, "R": 230}},
    # ── 5. 榫槽-孔阵列-环槽耦合盘（6：D23-D26 train, D27 val, D28 holdout）─────
    "D23": {"category": "coupled", "split": "train", **_BASE,
            "features": {**SLOT_DEFAULTS, "holes": 12, "pcd": 200, "hdia": 12, "grooves": 1, "gw": 10, "gd": 6}},
    "D24": {"category": "coupled", "split": "train", **{**_BASE, "od": 520},
            "features": {**SLOT_DEFAULTS, "slots": 48, "holes": 16, "pcd": 220, "hdia": 10,
                         "grooves": 1, "gw": 14, "gd": 8}},
    "D25": {"category": "coupled", "split": "train", **{**_BASE, "od": 560},
            "features": {**SLOT_DEFAULTS, "teeth": 3, "depth": 30, "holes": 12, "pcd": 240, "hdia": 14,
                         "grooves": 2, "gw": 12, "gd": 8}},
    "D26": {"category": "coupled", "split": "train", **{**_BASE, "od": 540},
            "features": {**SLOT_DEFAULTS, "slots": 72, "holes": 24, "pcd": 230, "hdia": 10,
                         "grooves": 1, "gw": 16, "gd": 10}},
    "D27": {"category": "coupled", "split": "val", **{**_BASE, "od": 600},
            "features": {**SLOT_DEFAULTS, "teeth": 3, "depth": 34, "holes": 20, "pcd": 250, "hdia": 12,
                         "grooves": 2, "gw": 18, "gd": 12}},
    "D28": {"category": "coupled", "split": "holdout", **{**_BASE, "od": 620},
            "features": {**SLOT_DEFAULTS, "slots": 84, "teeth": 3, "depth": 38, "holes": 16, "pcd": 260, "hdia": 16,
                         "grooves": 2, "gw": 20, "gd": 14}},
    # ── 6. 复杂轮缘过渡与榫槽组合盘（4：D29-D30 train, D31-D32 holdout）────────
    "D29": {"category": "complex_rim", "split": "train", **{**_BASE, "rim": 40},
            "features": {**SLOT_DEFAULTS, "slots": 60, "teeth": 3, "depth": 32, "R": 225}},
    "D30": {"category": "complex_rim", "split": "train", **{**_BASE, "rim": 36, "od": 560},
            "features": {**SLOT_DEFAULTS, "slots": 72, "teeth": 3, "depth": 34, "R": 235}},
    "D31": {"category": "complex_rim", "split": "holdout", **{**_BASE_LARGE, "rim": 45, "od": 640},
            "features": {**SLOT_DEFAULTS, "slots": 84, "teeth": 3, "depth": 38, "R": 250}},
    "D32": {"category": "complex_rim", "split": "holdout", **{**_BASE_LARGE, "rim": 48, "od": 680},
            "features": {**SLOT_DEFAULTS, "slots": 96, "teeth": 4, "depth": 42, "R": 260}},
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

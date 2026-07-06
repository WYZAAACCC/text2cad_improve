"""Pydantic params models for axisymmetric_base operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from seekflow_engineering_tools.generative_cad.ir.expr import DimExprOrFloat


class ProfileStation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    r_mm: DimExprOrFloat = Field(
        description="半径（RADIUS），不是直径。外径=2×r_mm。例如外径80mm的盘 r_mm=40."
    )
    z_front_mm: float = Field(
        description="该段起始 Z 位置（mm）。必须严格 < z_rear_mm（不允许零宽度段）。"
    )
    z_rear_mm: float = Field(
        description="该段结束 Z 位置（mm）。必须严格 > z_front_mm（不允许零宽度段）。"
    )
    label: str | None = Field(
        default=None,
        description="可选标签（如 'rim'/'hub'）。仅用于人类阅读，不影响几何。"
    )

    @model_validator(mode="after")
    def validate_z(self):
        if self.z_front_mm >= self.z_rear_mm:
            raise ValueError("z_front_mm must be strictly < z_rear_mm (zero-width stations forbidden)")
        return self


class RevolveProfileParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    axis: Literal["Z"] = "Z"
    profile_stations: list[ProfileStation] = Field(
        min_length=1,
        description=(
            "定义旋转体的 2D 截面外轮廓连续段。每个 station 描述一段圆柱面："
            "半径 r_mm 从 z_front_mm 延伸到 z_rear_mm。"
            "关键规则：profile 必须是 Z 的单值函数（同一 Z 只能有一个半径），"
            "描述外轮廓的连续台阶，不能按 bore/hub/web/rim 分区域输出。"
            "示例-外径80内径30厚12垫圈:[{r:40,zf:0,zr:2},{r:40,zf:2,zr:12},{r:15,zf:12,zr:13}]"
        ),
    )


class CutCenterBoreParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diameter_mm: DimExprOrFloat = Field(
        description="中心孔直径（mm）。注意这里是直径，不是半径。"
    )
    axis: Literal["Z"] = "Z"
    through_all: bool = True


class CutAnnularGrooveParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: Literal["front", "rear"] = Field(
        description="groove 切削方向：front=向 +Z 方向切削，rear=向 -Z 方向切削。"
        "若 z_position_mm 缺失，front 从 zmin 端面开始，rear 从 zmax 端面开始。"
    )
    inner_dia_mm: DimExprOrFloat = Field(
        description="groove 内径（mm）。必须 < outer_dia_mm。"
    )
    outer_dia_mm: DimExprOrFloat = Field(
        description="groove 外径（mm）。必须 > inner_dia_mm。"
    )
    depth_mm: DimExprOrFloat = Field(
        description="groove 深度（mm）。从起始 Z 位置沿切削方向延伸的距离。"
    )
    z_position_mm: DimExprOrFloat | None = Field(
        default=None,
        description="可选，切削起始 Z 位置（mm）。"
        "指定后从该 Z 位置开始切削 depth_mm 毫米（side 决定方向）。"
        "缺失时使用 side 决定的端面（front=zmin, rear=zmax）。"
        "示例：z_position_mm=10, side=front, depth=20 → 切削 Z=10→30 的环形槽。"
    )

    @model_validator(mode="after")
    def validate_dia(self):
        # Skip comparison if either value is a DimExpr (dict) — the comparison
        # will be validated at analysis time after DimExpr resolution.
        if isinstance(self.inner_dia_mm, dict) or isinstance(self.outer_dia_mm, dict):
            return self
        if self.inner_dia_mm >= self.outer_dia_mm:
            raise ValueError("inner_dia_mm must be < outer_dia_mm")
        return self


class CutCircularHolePatternParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=2, le=240, description="圆周均布孔数量。")
    pcd_mm: DimExprOrFloat = Field(
        description="孔所在圆周直径（PCD, mm）。孔中心位于该圆周上。"
    )
    hole_dia_mm: DimExprOrFloat = Field(description="每个孔的直径（mm）。")
    axis: Literal["Z"] = "Z"
    through_all: bool = True


class SlotProfileStation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    depth_mm: float = Field(
        ge=0,
        description="该 station 的径向深度（mm）。从外径向内测量。必须非递减。"
    )
    half_width_mm: float = Field(
        gt=0,
        description="该 station 的半宽（mm）。fir-tree 截面在 R-θ 平面的半宽。"
    )


class RimSlotProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["symmetric_station_profile"] = "symmetric_station_profile"
    stations: list[SlotProfileStation] = Field(
        min_length=2,
        description="fir-tree 截面站点列表。depth_mm 必须非递减（从外向内）。"
    )

    @model_validator(mode="after")
    def validate_depth_order(self):
        depths = [s.depth_mm for s in self.stations]
        if depths != sorted(depths):
            raise ValueError("slot profile station depths must be nondecreasing")
        return self


class CutRimSlotPatternParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(
        ge=2, le=360,
        description="圆周均布槽数量。例如涡轮盘常见 40-80 个。"
    )
    slot_depth_mm: DimExprOrFloat = Field(
        description="槽的总径向深度（mm）。应 >= stations 中最大的 depth_mm。"
    )
    slot_profile: RimSlotProfile


class ApplySafeChamferParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distance_mm: DimExprOrFloat = Field(
        description="倒角距离（mm）。复杂几何建议设为 required=False 以允许降级。"
    )
    target: Literal["all_external_edges"] = "all_external_edges"

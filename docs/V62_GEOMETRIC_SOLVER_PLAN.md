# v6.2 几何约束求解 + 智能路径扫掠 — 架构级修复方案

**作者**: CAD 编译器架构师 / 几何内核工程师
**日期**: 2026-06-04
**基于**: v6.1 35 case 测试 + s01/tm12 双约束陷阱 + 管道扫掠问题

---

## 一、问题诊断

### 问题 A: 几何约束无解时 LLM 无法自主修复

当前状态:
- Preflight 正确检测了 s01 (壁厚10mm, 孔径12mm) 和 tm12 (壁厚4mm, 孔径8mm) 的几何矛盾
- repair_hints.py 正确计算了可行参数范围
- LLM 收到提示后尝试调整, 但陷入单向调整陷阱 (改 PCD → 撞另一个约束)
- 5 次重试后仍失败

**根因**: LLM 不擅长多参数协调调整。它每次只改一个参数, 必然陷入双约束振荡。
**正确方案**: 在 LLM retry 之前, 用确定性求解器找到可行参数组合, 直接修复。

### 问题 B: 管道扫掠在复杂路径上质量差

当前状态:
- `make_circular_pipe_along_path` 使用三级混合策略 (BSpline→polyline→分段圆柱)
- 对缓和弯头效果好 (97-100%体积), 对紧密弯头回退到分段圆柱
- 但选策略是"try-and-fallback", 而非"analyze-and-choose"

**根因**: 缺少路径形状分析。应该先分析路径特征, 再选择最优方法。
**正确方案**: 添加 `path_analysis.py` 模块, 根据路径曲率、段长、弯角自动选择最佳扫掠策略。

---

## 二、方案 A: GeometricParameterSolver (确定性几何约束求解)

### 2.1 架构位置

```
LLM raw output
  → auto_fixer (format fixes)
  → Pydantic validation
  → Preflight validation
  → [NEW] GeometricParameterSolver ← 在这里!
  → LLM retry (with repair hints) ← 只在 solver 无法修复时
```

### 2.2 设计原则

1. **数学确定性**: solver 使用精确的几何约束方程, 不是启发式猜测
2. **最小改动**: 只调整必要的参数, 保持用户显式指定的参数不变
3. **完整审计**: 所有改动记录到 AssumptionLedger
4. **失败快速**: 如果找不到可行解, 立即返回明确错误, 不浪费 LLM 调用

### 2.3 约束模型

对于 axisymmetric 孔模式, 两个约束方程:

```
min_pcd = bore_dia + hole_dia + 2*MARGIN     (孔不撞中心孔)
max_pcd = 2*outer_radius - hole_dia - 2*MARGIN  (孔不超出外径)
Feasible: min_pcd <= max_pcd
         → bore_dia + 2*hole_dia + 4*MARGIN <= 2*outer_radius
         → wall >= hole_dia + 2*MARGIN  (其中 wall = outer_r - bore_r)
```

如果不可行, solver 在以下策略中选择最小改动:

| 策略 | 改动参数 | 条件 |
|------|---------|------|
| ReduceHole | hole_dia -= delta | delta = (min_pcd - max_pcd) / 2 |
| ReduceBore | bore_dia -= delta | delta = min_pcd - max_pcd |
| IncreaseOuter | outer_r += delta | delta = (min_pcd - max_pcd) / 2 |
| Combo | hole_dia -= x, bore_dia -= y | x+y = gap, distributed by confidence |

### 2.4 新文件

```
validation/geometric_solver.py   (~200 loc)
```

### 2.5 核心函数

```python
def solve_hole_pattern_constraints(
    params: dict,           # {outer_r, bore_dia, hole_dia, pcd, count}
    constraints: dict,       # {min_pcd, max_pcd} from preflight
) -> tuple[dict, list[str]]:
    """Find minimal parameter adjustments to satisfy hole pattern constraints.
    
    Returns (adjusted_params, audit_entries).
    Returns original params if already feasible.
    """
```

### 2.6 集成点

在 `auto_fix_with_report` 中作为新的 fix 函数 (category: CONTEXT_SAFE — 数学确定性):

```python
# In auto_fixer.py, after fix_phase_ordering:
if "hole_pattern" in str(err):
    fixed, audit = solve_hole_pattern_constraints(params, constraints)
    # Apply fix with full audit trail
```

---

## 三、方案 B: 智能路径扫掠分析器

### 3.1 架构位置

```
handle_sweep_profile(node, ctx)
  → [NEW] analyze_path_geometry(path_points, radius)
  → select_optimal_method(analysis)
  → execute_sweep(method)
  → validate_result(volume_ratio)
```

### 3.2 路径分类

```python
@dataclass
class PathAnalysis:
    point_count: int
    total_length: float
    min_segment_length: float
    max_bend_angle_deg: float     # 最大弯角
    min_bend_radius_ratio: float  # 最小弯角半径/管道半径
    is_straight: bool             # 所有点共线
    is_planar: bool               # 所有点在同一平面
    has_tight_bends: bool         # 弯角半径 < 3*pipe_radius
    recommendation: str           # "cylinder" | "polyline_sweep" | "bspline_sweep" | "segmented"
```

### 3.3 决策逻辑

```
IF point_count == 2 OR is_straight:
    → cylinder (BRepPrimAPI_MakeCylinder, 最快)
ELIF point_count == 3 AND max_bend_angle < 45°:
    → polyline_sweep (单弯头, MakePipe 可靠)
ELIF has_tight_bends (min_bend_radius_ratio < 3.0):
    → segmented (紧密弯头, 保证体积)
ELSE:
    → bspline_sweep (平滑路径, 最佳质量)
```

### 3.4 新文件

```
dialects/geometry_utils/path_analysis.py   (~120 loc)
```

### 3.5 修改文件

```
dialects/geometry_utils/ocp_pipe.py   — 使用 path_analysis 选择方法
dialects/loft_sweep/handlers.py       — handle_sweep_profile 使用分析器
```

---

## 四、实施顺序

### Step 1: GeometricParameterSolver (1-2h)
- 创建 `validation/geometric_solver.py`
- 实现 `solve_hole_pattern_constraints()`
- 集成到 `auto_fixer.py` 的修复序列

### Step 2: 路径分析器 (1-2h)
- 创建 `dialects/geometry_utils/path_analysis.py`
- 实现 `analyze_path_geometry()` 和 `select_optimal_method()`
- 集成到 `ocp_pipe.py` 的 `make_circular_pipe_along_path()`

### Step 3: 验证 (1-2h)
- 对 s01 + tm12 测试 geometric_solver
- 对 s13/s17/tm13/s09 测试 path_analysis
- 回归测试 (确保现有 33/35 不变)

---

## 五、验收标准

### GeometricParameterSolver:
```
s01 (r=250, bore=480, PCD=470, hole=12):
  → solver detects gap=8mm (min_pcd=494 > max_pcd=486)
  → applies strategy ReduceHole: hole_dia 12→8mm
  → result: min_pcd=490, max_pcd=490 → feasible ✓
  → audit: "Reduced hole_dia from 12 to 8mm to satisfy wall thickness constraint"

tm12 (r=80, bore=152, PCD=140, hole=8):
  → solver detects gap=12mm (min_pcd=162 > max_pcd=150)
  → applies strategy ReduceBore: bore_dia 152→130mm
  → result: min_pcd=150, max_pcd=154 → feasible ✓
  → audit: "Reduced bore_dia from 152 to 130mm to satisfy wall thickness constraint"
```

### PathAnalysis:
```
s13 (straight + gentle bends):
  → pipe_a: 3pt, max_bend=45° → polyline_sweep
  → main: 2pt, straight → cylinder

s17 (tight spatial bends):
  → 5pt, max_bend=72°, bend_radius/pipe_radius=2.1 → segmented (tight!)
  → volume ratio > 95% guaranteed
```

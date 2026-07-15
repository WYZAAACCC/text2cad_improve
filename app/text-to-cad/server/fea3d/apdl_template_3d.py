"""apdl_template_3d.py — 渲染 solve.inp (APDL 批处理输入文件).

用法: render_solve_inp(cfg: dict, job_dir: Path) -> Path
"""
from __future__ import annotations
import json, math
from pathlib import Path
from string import Template


def _str(v) -> str:
    """保证 ANSYS 读得懂的浮点数格式（不依赖 locale）。"""
    f = float(v)
    if abs(f) < 1e-30:
        return "0.0"
    return f"{f:.10g}"


def render(cfg: dict, job_dir: Path) -> Path:
    """渲染 solve.inp 到 job_dir, 返回文件路径."""
    g = cfg["geometry"]
    ld = cfg["load"]
    mat = cfg["material"]
    sol = cfg["solver"]

    # --- 材料参数 ---
    temps = mat["temps_c"]
    ex_mpa = mat["ex_mpa"]
    alpx = mat["alpx_1_c"]
    assert len(temps) >= 4, "材料表至少需 4 个温度点"

    # --- 求解参数 ---
    rpm = float(ld["rpm"])
    tb = float(ld["t_bore_c"])
    tr = float(ld["t_rim_c"])
    texp = float(ld["t_exponent"])
    tref = float(ld["t_ref_c"])
    rb = float(g["r_bore_mm"])
    ro = float(g["r_outer_mm"])
    thl = float(g["theta_low_deg"])
    thh = thl + float(g["sector_deg"])
    sect = float(g["sector_deg"])

    # APDL 固定参数
    prxy = float(mat["prxy"])
    dens = float(mat["dens_t_mm3"])

    # 模板 (用 $ 替代 $ 防止 format 破坏)
    tmpl = Template(r"""/BATCH
/FILNAME,turbine3d
/TITLE,HP Turbine Disc 3D cyclic sector - centrifugal + radial thermal
/PREP7
ET,1,187                          ! SOLID187 二阶四面体

! ============ GH4169 温度相关材料 ([人工确认]表) ============
MPTEMP                            ! 清空温度表
MPTEMP,1,${mt0},${mt1},${mt2},${mt3}
MPDATA,EX,1,1,${ex0},${ex1},${ex2},${ex3}
MPDATA,ALPX,1,1,${ax0},${ax1},${ax2},${ax3}
MP,PRXY,1,${prxy}
MP,DENS,1,${dens}                  ! tonne/mm3 !
TREF,${tref}

/INPUT,mesh,inp                   ! 读入 gmsh 导出的节点/单元

! ============ 参数 ============
PI=ACOS(-1)
OMG=${rpm}*2*PI/60                 ! rad/s
RB=${rb} $ RO=${ro}
TB=${tb} $ TR=${tr} $ TEXP=${texp}
THL=${thl} $ THH=${thh} $ SECT=${sect}

! ============ 节点旋入柱坐标系 (此后 UX=径向 UY=切向 UZ=轴向) ============
CSYS,1
NROTAT,ALL

! ============ 循环对称耦合: 仅选两切割面节点, CPCYC 自动配对 ============
! CSYS,1 下 NSEL LOC,Y 的单位是"度"
NSEL,S,LOC,Y,THL-0.01,THL+0.01
NSEL,A,LOC,Y,THH-0.01,THH+0.01
CPCYC,ALL,0.05,1,,SECT,,0         ! TOLER=0.05mm(网格严格周期匹配), KCN=1, DY=6$
ALLSEL

! ============ z=0 对称面 (镜像对称 → UZ=0, 同时消除轴向刚体平动) ============
NSEL,S,LOC,Z,-1E-3,1E-3
D,ALL,UZ,0
ALLSEL

! ============ 消除绕轴刚体转动: 孔壁近 z=0 的 1 个节点 切向UY=0 ============
CSYS,1
NSEL,S,LOC,X,RB-0.5,RB+0.5
NSEL,R,LOC,Z,0,2.0
*GET,NANCH,NODE,0,NUM,MIN
ALLSEL
D,NANCH,UY,0

! ============ 径向分带温度场 T(r) = TB+(TR-TB)*((r-RB)/(RO-RB))**TEXP ============
NBAND=80
*DO,I,1,NBAND
  R1=RB+(I-1)*(RO-RB)/NBAND
  R2=RB+I*(RO-RB)/NBAND
  RM=(R1+R2)/2
  TT=TB+(TR-TB)*((RM-RB)/(RO-RB))**TEXP
  RS1=R1 $ RS2=R2
  *IF,I,EQ,1,THEN
    RS1=R1-2
  *ENDIF
  *IF,I,EQ,NBAND,THEN
    RS2=R2+2
  *ENDIF
  NSEL,S,LOC,X,RS1,RS2
  BF,ALL,TEMP,TT
*ENDDO
ALLSEL

! ============ 离心载荷 (绕全局Z轴, 与 CSYS 无关) ============
OMEGA,,,OMG
FINISH

/SOLU
ANTYPE,STATIC
EQSLV,SPARSE
SOLVE
FINISH

! ============ 后处理: 全三维节点应力场导出 ============
/POST1
SET,LAST
RSYS,1                            ! 应力转柱坐标: SX=径向 SY=环向 SZ=轴向

*GET,NMAX,NODE,0,NUM,MAX
*DIM,NID,ARRAY,NMAX
*VFILL,NID(1),RAMP,1,1
*DIM,MSK,ARRAY,NMAX
*DIM,XX,ARRAY,NMAX
*DIM,YY,ARRAY,NMAX
*DIM,ZZ,ARRAY,NMAX
*DIM,SR,ARRAY,NMAX
*DIM,SH,ARRAY,NMAX
*DIM,SA,ARRAY,NMAX
*DIM,SV,ARRAY,NMAX
*DIM,SP1,ARRAY,NMAX
*DIM,SP3,ARRAY,NMAX
*VGET,MSK(1),NODE,1,NSEL          ! 1=选中 0=不存在 -1=未选 (Python 侧过滤)
CSYS,0                            ! 坐标导出用笛卡尔
*VGET,XX(1),NODE,1,LOC,X
*VGET,YY(1),NODE,1,LOC,Y
*VGET,ZZ(1),NODE,1,LOC,Z
*VGET,SR(1),NODE,1,S,X            ! 径向 (RSYS,1)
*VGET,SH(1),NODE,1,S,Y            ! 环向
*VGET,SA(1),NODE,1,S,Z            ! 轴向
*VGET,SV(1),NODE,1,S,EQV          ! Von Mises
*VGET,SP1(1),NODE,1,S,1
*VGET,SP3(1),NODE,1,S,3
*CFOPEN,nodal_stress_3d,csv
*VWRITE
('nid,x,y,z,s_radial,s_hoop,s_axial,s_eqv,s1,s3,sel')
*VWRITE,NID(1),XX(1),YY(1),ZZ(1),SR(1),SH(1),SA(1),SV(1),SP1(1),SP3(1),MSK(1)
(F9.0,',',F12.5,',',F12.5,',',F12.5,',',F11.3,',',F11.3,',',F11.3,',',F11.3,',',F11.3,',',F11.3,',',F4.0)
*CFCLOS

! ============ 交叉核对指标 (权威指标由 Python 从 CSV 计算) ============
NSORT,S,EQV
*GET,VMMAX,SORT,,MAX
NSEL,S,LOC,Z,-1E-3,1E-3
FSUM
*GET,FZSUM,FSUM,0,ITEM,FZ         ! 对称面轴向反力合力应≈0
ALLSEL
*CFOPEN,result_summary,txt
*VWRITE,VMMAX
('MAX_VON_MISES = ',F12.3,' MPa')
*VWRITE,FZSUM
('SYM_PLANE_FZ_SUM = ',E14.5,' N')
*CFCLOS
FINISH
""")

    # 用 Template 安全替换
    subs = {}
    for i in range(4):
        subs[f"mt{i}"] = _str(temps[i])
        subs[f"ex{i}"] = _str(ex_mpa[i])
        subs[f"ax{i}"] = _str(alpx[i])
    subs["prxy"] = _str(prxy)
    subs["dens"] = _str(dens)
    subs["tref"] = _str(tref)
    subs["rpm"] = _str(rpm)
    subs["rb"] = _str(rb)
    subs["ro"] = _str(ro)
    subs["tb"] = _str(tb)
    subs["tr"] = _str(tr)
    subs["texp"] = _str(texp)
    subs["thl"] = _str(thl)
    subs["thh"] = _str(thh)
    subs["sect"] = _str(sect)

    rendered = tmpl.safe_substitute(subs)

    solve_inp = job_dir / "solve.inp"
    solve_inp.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"[apdl] solve.inp 已渲染 → {solve_inp}")
    return solve_inp


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--job", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    job_dir = Path(args.job)
    job_dir.mkdir(parents=True, exist_ok=True)
    render(cfg, job_dir)

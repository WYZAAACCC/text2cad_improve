"""APDL template generators for common ANSYS 18.1 analyses.

Each function returns a complete APDL input string.  Units: mm, N, MPa.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Pre-built templates
# ---------------------------------------------------------------------------


def static_cantilever_beam_rect_apdl(
    length_mm: float,
    width_mm: float,
    height_mm: float,
    force_n: float,
    young_mpa: float = 210000.0,
    poisson: float = 0.3,
    element_size_mm: float = 10.0,
) -> str:
    r"""Rectangular cantilever beam — fixed at x=0, tip load at x=L.

    Generates SOLID185 mesh, static solve, and writes *result_summary.txt*
    containing ``MAX_DISPLACEMENT_MM``.
    """
    return f"""\
/CLEAR
/FILNAME,beam_job
/PREP7

! Units: N, mm, MPa

ET,1,SOLID185
MP,EX,1,{young_mpa}
MP,PRXY,1,{poisson}

BLOCK,0,{length_mm},0,{width_mm},0,{height_mm}

ESIZE,{element_size_mm}
VMESH,ALL

/SOLU
ANTYPE,STATIC

! Fix x=0 face
NSEL,S,LOC,X,0
D,ALL,ALL,0

! Apply force on x=L face in negative Z direction
NSEL,S,LOC,X,{length_mm}
*GET,NCOUNT,NODE,0,COUNT
F,ALL,FZ,{-abs(force_n)}/NCOUNT

ALLSEL,ALL
SOLVE
FINISH

/POST1
SET,LAST

! Maximum displacement magnitude
NSORT,U,SUM
*GET,MAXU,SORT,0,MAX

PRNSOL,U
PRNSOL,S,EQV

/OUTPUT,result_summary,txt
*VWRITE,MAXU
('MAX_DISPLACEMENT_MM=',E16.8)
/OUTPUT

FINISH
"""


# ---------------------------------------------------------------------------
# Template registry (Phase 2 will expand)
# ---------------------------------------------------------------------------

def plate_with_hole_tension_apdl(
    plate_width_mm=200.0,
    plate_height_mm=100.0,
    plate_thickness_mm=10.0,
    hole_diameter_mm=20.0,
    tensile_stress_mpa=100.0,
    element_size_mm=5.0,
):
    r"""Plate with central hole under uniform tension.

    Quarter-symmetry model.  Classical stress-concentration benchmark:
    theoretical Kt ≈ 2.5 for d/W ≈ 0.1.
    """
    half_w = plate_width_mm / 2.0
    half_h = plate_height_mm / 2.0
    radius = hole_diameter_mm / 2.0

    apdl = """\
/CLEAR
/FILNAME,plate_hole
/PREP7

! Units: N, mm, MPa
! Quarter-symmetry plate with central hole

ET,1,PLANE182
KEYOPT,1,1,1         ! plane stress with thickness
R,1,{thickness}       ! thickness

MP,EX,1,210000.0
MP,PRXY,1,0.3

! Create quarter-plate area
RECTNG,0,{half_w},0,{half_h}

! Create quarter-hole
CYL4,0,0,0,0,{radius},90

! Subtract hole from plate
ASBA,1,2

! Mesh
ESIZE,{element_size}
AMESH,ALL

! Boundary conditions
! Symmetry on x=0 (left edge)
LSEL,S,LOC,X,0
DL,ALL,,SYMM
! Symmetry on y=0 (bottom edge)
LSEL,S,LOC,Y,0
DL,ALL,,SYMM
ALLSEL,ALL

! Tensile load on right edge (negative = tension)
LSEL,S,LOC,X,{half_w}
SFL,ALL,PRES,{tensile}
ALLSEL,ALL

/SOLU
ANTYPE,STATIC
SOLVE
FINISH

/POST1
SET,LAST

! Maximum stress (at hole edge = stress concentration)
NSORT,S,X
*GET,SMAX_X,SORT,0,MAX

! Nominal stress = tensile_stress_mpa
! Stress concentration factor Kt = SMAX_X / nominal
NOMINAL = {tensile_stress_mpa}
KT = SMAX_X / NOMINAL

! Maximum displacement
NSORT,U,SUM
*GET,MAXU,SORT,0,MAX

/OUTPUT,result_summary,txt
*VWRITE,SMAX_X,MAXU,KT
('MAX_STRESS_MPA=',E16.8,' MAX_DISPLACEMENT_MM=',E16.8,' STRESS_CONCENTRATION_Kt=',F10.4)
/OUTPUT

FINISH
""".format(
        half_w=half_w,
        half_h=half_h,
        radius=radius,
        thickness=plate_thickness_mm,
        element_size=element_size_mm,
        tensile_stress_mpa=tensile_stress_mpa,
        tensile=-tensile_stress_mpa,
    )
    return apdl


def beam_thermal_apdl(
    length_mm=200.0,
    width_mm=20.0,
    height_mm=20.0,
    temp_left_c=100.0,
    temp_right_c=0.0,
    ambient_temp_c=25.0,
    element_size_mm=5.0,
):
    r"""Steady-state thermal analysis — bar with fixed end temperatures.

    Fourier law: q = -k·dT/dx.  Validates linear temperature gradient.
    """
    return """\
/CLEAR
/FILNAME,beam_thermal
/PREP7

! Units: mm, C, W

ET,1,SOLID70            ! 3D thermal solid

! Thermal conductivity (steel, W/(mm·C))
MP,KXX,1,0.050          ! ≈ 50 W/(m·K) in mm units

BLOCK,0,{length},0,{width},0,{height}

ESIZE,{element_size}
VMESH,ALL

/SOLU
ANTYPE,STATIC

! Fixed temperature on x=0 face
NSEL,S,LOC,X,0
D,ALL,TEMP,{temp_left}
ALLSEL,ALL

! Fixed temperature on x=L face
NSEL,S,LOC,X,{length}
D,ALL,TEMP,{temp_right}
ALLSEL,ALL

! Convection on remaining surfaces
! (skip for simplicity — pure conduction validation)

SOLVE
FINISH

/POST1
SET,LAST

! Mid-point temperature: pick the node closest to x={mid_x}
NSEL,S,LOC,X,{mid_x}-1,{mid_x}+1
*GET,NN,NODE,0,NUM,MIN     ! get first selected node number
*GET,TMID,NODE,NN,TEMP      ! get its temperature
ALLSEL,ALL

! Temperature gradient check
NSORT,TEMP,,0
*GET,TMIN,SORT,0,MIN
*GET,TMAX,SORT,0,MAX

/OUTPUT,result_summary,txt
*VWRITE,TMIN,TMAX,TMID
('TMIN_C=',E16.8,' TMAX_C=',E16.8,' TMID_C=',E16.8)
/OUTPUT

FINISH
""".format(
        length=length_mm,
        width=width_mm,
        height=height_mm,
        element_size=element_size_mm,
        temp_left=temp_left_c,
        temp_right=temp_right_c,
        mid_x=length_mm / 2.0,
    )


def cantilever_modal_apdl(
    length_mm=200.0,
    width_mm=20.0,
    height_mm=20.0,
    young_mpa=210000.0,
    density_kgmm3=7.85e-6,
    poisson=0.3,
    n_modes=5,
    element_size_mm=10.0,
):
    r"""Modal analysis of a cantilever beam — natural frequencies.

    Block Lanczos extraction; validates against Euler-Bernoulli theory:
    f1 ≈ (1.875²)/(2π·L²) · sqrt(E·I/(ρ·A))
    """
    return """\
/CLEAR
/FILNAME,cantilever_modal
/PREP7

! Units: N, mm, tonne, MPa
! Density: 7.85e-6 tonne/mm³ (steel)

ET,1,SOLID185

MP,EX,1,{young}
MP,PRXY,1,{poisson}
MP,DENS,1,{density}

BLOCK,0,{length},0,{width},0,{height}

ESIZE,{esize}
VMESH,ALL

! Fix x=0 face
NSEL,S,LOC,X,0
D,ALL,ALL,0
ALLSEL,ALL

/SOLU
ANTYPE,MODAL
MODOPT,LANB,{n_modes}
MXPAND,{n_modes},,,YES
SOLVE
FINISH

/POST1
*DIM,FREQ,ARRAY,{n_modes}

/OUTPUT,result_summary,txt
*DO,I,1,{n_modes}
SET,1,I
*GET,FREQ(I),ACTIVE,0,SET,FREQ
*VWRITE,I,FREQ(I)
('MODE ',F3.0,' FREQ_HZ=',E16.8)
*ENDDO
/OUTPUT

FINISH
""".format(
        length=length_mm,
        width=width_mm,
        height=height_mm,
        young=young_mpa,
        density=density_kgmm3,
        poisson=poisson,
        n_modes=n_modes,
        esize=element_size_mm,
    )


def buckling_column_apdl(
    length_mm=500.0,
    width_mm=20.0,
    height_mm=20.0,
    young_mpa=210000.0,
    poisson=0.3,
    element_size_mm=10.0,
    n_modes=3,
):
    r"""Eigenvalue buckling of a cantilever column under axial compression.

    Euler critical load for cantilever:
        Pcr = pi^2 * E * I / (4 * L^2)

    The buckling load factor (BLF) should be ~1.0 for a unit load
    close to Pcr.  First mode BLF = Pcr / P_applied.
    """
    area = width_mm * height_mm
    iz = width_mm * height_mm ** 3 / 12.0
    # Euler Pcr (cantilever: effective length = 2*L)
    pcr_euler = (3.14159265 ** 2) * young_mpa * iz / ((2.0 * length_mm) ** 2)
    # Apply ~60% of Pcr as reference load
    p_applied = pcr_euler * 0.6

    return """\
/CLEAR
/FILNAME,euler_column
/PREP7

! Column under axial compression — eigenvalue buckling
! Units: N, mm, MPa

ET,1,BEAM188
MP,EX,1,{young}
MP,PRXY,1,{poisson}

SECTYPE,1,BEAM,RECT
SECDATA,{width},{height}

! Create nodes along the column
N,1,0,0,0
N,{nnodes},{length},0,0
FILL

! Mesh
E,1,2
EGEN,{nnodes_minus_1},1,1

! Fix base
D,1,ALL,0

! Unit reference load at tip (axial)
F,{nnodes},FX,-{p_applied}

FINISH

/SOLU
ANTYPE,STATIC
PSTRES,ON           ! prestress for buckling
SOLVE
FINISH

/SOLU
ANTYPE,BUCKLE
BUCOPT,LANB,{n_modes}
MXPAND,{n_modes}
SOLVE
FINISH

/POST1
/OUTPUT,result_summary,txt
*DO,I,1,{n_modes}
SET,1,I
*GET,BLF,ACTIVE,0,SET,FREQ
P_CRIT = BLF * {p_applied}
*VWRITE,I,BLF,P_CRIT
('MODE ',F3.0,' BLF=',E16.8,' Pcr_N=',E16.8)
*ENDDO
/OUTPUT

FINISH
""".format(
        length=length_mm,
        width=width_mm,
        height=height_mm,
        young=young_mpa,
        poisson=poisson,
        esize=element_size_mm,
        n_modes=n_modes,
        nnodes=11,
        nnodes_minus_1=10,
        p_applied=p_applied,
    )


def bilinear_plastic_apdl(
    length_mm=100.0,
    width_mm=10.0,
    height_mm=10.0,
    young_mpa=210000.0,
    yield_stress_mpa=235.0,
    tangent_modulus_mpa=2100.0,
    displacement_mm=5.0,
    element_size_mm=5.0,
    n_substeps=20,
):
    r"""Bilinear kinematic hardening — cantilever under large tip displacement.

    Material goes plastic when stress exceeds yield.  Validates:
    - Nonlinear material model (BKIN)
    - Large displacement (NLGEOM,ON)
    - Multiple substeps with convergence
    """
    return """\
/CLEAR
/FILNAME,bilinear_plastic
/PREP7

! Units: N, mm, MPa
! Bilinear kinematic hardening plasticity

ET,1,SOLID185

MP,EX,1,{young}
MP,PRXY,1,0.3

! Bilinear kinematic hardening
TB,BKIN,1
TBDATA,1,{yield_stress},{tangent}

BLOCK,0,{length},0,{width},0,{height}

ESIZE,{esize}
VMESH,ALL

! Fix x=0 face
NSEL,S,LOC,X,0
D,ALL,ALL,0
ALLSEL,ALL

/SOLU
ANTYPE,STATIC
NLGEOM,ON            ! large displacement
NSUBST,{nsub},20,5   ! substeps with bisection
OUTRES,ALL,ALL
AUTOTS,ON

! Apply prescribed displacement at tip
NSEL,S,LOC,X,{length}
D,ALL,UY,{neg_disp}
ALLSEL,ALL

SOLVE
FINISH

/POST1
SET,LAST

! Reaction force at fixed end (= plastic limit load)
NSEL,S,LOC,X,0
FSUM
ALLSEL,ALL

! Max equivalent plastic strain
/OUTPUT,result_summary,txt
NSORT,EPPL,EQV
*GET,MAXPE,SORT,0,MAX
NSORT,U,Y
*GET,MAXUY,SORT,0,MIN
*VWRITE,MAXPE,MAXUY
('MAX_PLASTIC_STRAIN=',E16.8,' TIP_DISPLACEMENT_MM=',E16.8)
/OUTPUT

FINISH
""".format(
        length=length_mm,
        width=width_mm,
        height=height_mm,
        young=young_mpa,
        yield_stress=yield_stress_mpa,
        tangent=tangent_modulus_mpa,
        disp=displacement_mm,
        esize=element_size_mm,
        nsub=n_substeps,
        neg_disp=-displacement_mm,
    )


def turbine_disc_rotational_thermal_apdl(
    step_file_path: str = "",
    rpm: float = 15000.0,
    temp_rim_c: float = 650.0,
    temp_bore_c: float = 500.0,
    young_rim_mpa: float = 150000.0,
    young_bore_mpa: float = 175000.0,
    yield_mpa_650c: float = 900.0,
    density_tonnemm3: float = 8.24e-9,
    poisson: float = 0.3,
    alpha: float = 1.45e-5,
    element_size_mm: float = 5.0,
    n_slots: int = 60,
    slot_depth_mm: float = 20.0,
    # ── Geometry parameters (override to match actual CAD model) ──
    bore_r_mm: float = 60.0,
    hub_r_mm: float = 120.0,
    web_r1_mm: float = 120.0,
    web_r2_mm: float = 215.0,
    rim_r_mm: float = 250.0,
    hub_half_z_mm: float = 38.0,
    web_half_z1_mm: float = 22.0,
    web_half_z2_mm: float = 15.0,
    rim_half_z_mm: float = 30.0,
) -> str:
    r"""Turbine disc 2D axisymmetric thermal-structural analysis.

    Geometry is built from parameters (defaults match standard 500mm disc):
      bore R = {bore_r_mm}, hub R = {hub_r_mm}, web = {web_r1_mm}→{web_r2_mm},
      rim R = {rim_r_mm}, half-thicknesses: hub={hub_half_z_mm}, rim={rim_half_z_mm}.

    Loads: centrifugal (OMEGA about Y) + radial temperature gradient
           (T_bore → T_rim, linear with radius).  The gradient produces
           thermal stress; uniform T would produce none.

    Material: GH4169 / Inconel 718 with temperature-dependent EX via
              MPTEMP/MPDATA (E_bore at T_bore, E_rim at T_rim).

    Extracts: radial/hoop/von-Mises stress paths from bore to rim,
    safety factor = yield / von_Mises, plus nodal CSV for heatmap.
    """
    omega_rad_s = 2.0 * 3.14159265358979 * rpm / 60.0

    # Keypoints for disc cross-section (R, Z) — closed polygon, clockwise
    # Bore→Hub→Web→Rim→back, built from geometry parameters
    kp_rz = [
        (bore_r_mm, -hub_half_z_mm),
        (hub_r_mm, -hub_half_z_mm),
        (hub_r_mm, -web_half_z1_mm),
        (web_r2_mm, -web_half_z2_mm),
        (web_r2_mm, -rim_half_z_mm),
        (rim_r_mm, -rim_half_z_mm),
        (rim_r_mm, rim_half_z_mm),
        (web_r2_mm, rim_half_z_mm),
        (web_r2_mm, web_half_z2_mm),
        (hub_r_mm, web_half_z1_mm),
        (hub_r_mm, hub_half_z_mm),
        (bore_r_mm, hub_half_z_mm),
    ]
    nkp = len(kp_rz)
    kp_list = ",".join(str(i+1) for i in range(nkp))
    kp_cmds = "\n".join(
        f"K,{i+1},{r},{z},0" for i, (r, z) in enumerate(kp_rz)
    )

    return f"""\
/CLEAR,NOSTART
/FILNAME,turbine_disc
/TITLE,HP Turbine Disc — Rotational + Thermal, {rpm:.0f} RPM, Rim={temp_rim_c:.0f}C Bore={temp_bore_c:.0f}C

! ==============================================================================
! PARAMETERS
! ==============================================================================
RPM       = {rpm}
OMEGA     = {omega_rad_s:.6f}
T_RIM     = {temp_rim_c}
T_BORE    = {temp_bore_c}
E_RIM     = {young_rim_mpa}
E_BORE    = {young_bore_mpa}
S_YIELD   = {yield_mpa_650c}
DENS      = {density_tonnemm3:.6e}
NU        = {poisson}
ALPHA     = {alpha}
ESIZE     = {element_size_mm}
N_SLOTS   = {n_slots}
D_SLOT    = {slot_depth_mm}
! Disc geometry (mm)
BORE_R    = {bore_r_mm}
HUB_R     = {hub_r_mm}
WEB_R1    = {web_r1_mm}
WEB_R2    = {web_r2_mm}
RIM_R     = {rim_r_mm}
HUB_HZ    = {hub_half_z_mm}
WEB_HZ1   = {web_half_z1_mm}
WEB_HZ2   = {web_half_z2_mm}
RIM_HZ    = {rim_half_z_mm}

! ==============================================================================
! PREPROCESSOR — Axisymmetric Model
! ==============================================================================
/PREP7

! --- Element type: PLANE183, axisymmetric ---
! KEYOPT(1)=0: 8-node quad (default)
! KEYOPT(3)=1: Axisymmetric (X=radial, Y=axial, Z=hoop)
ET,1,PLANE183
KEYOPT,1,3,1      ! Axisymmetric

! --- Material: GH4169 / Inconel 718 ---
! Temperature-dependent Young's modulus: EX(T) interpolated between
! T_BORE (E_BORE, cooler → stiffer) and T_RIM (E_RIM, hotter → softer)
MPTEMP,1,T_BORE,T_RIM
MPDATA,EX,1,1,E_BORE,E_RIM
MP,PRXY,1,NU
MP,DENS,1,DENS
MP,ALPX,1,ALPHA

! --- Geometry: single closed polygon area ---
{kp_cmds}

! Create area from all {nkp} keypoints (single closed polygon)
A,{kp_list}

! --- Mesh ---
ESIZE,ESIZE
MSHAPE,0,2D       ! Quad-dominant
MSHKEY,0          ! Free mesh
AMESH,ALL

FINISH

! ==============================================================================
! SOLUTION — Static structural with thermal load
! ==============================================================================
/SOLU
ANTYPE,STATIC

! --- Rotational body force about symmetry axis Y ---
! For PLANE183 axisymmetric (X=radial, Y=axial): OMEGY = ω
OMEGA,,OMEGA,,

! --- Reference temperature (stress-free temperature) ---
TREF,20

! --- Thermal load: radial temperature gradient ---
! Linear ramp T(R) = T_BORE + (T_RIM-T_BORE)*(R-BORE_R)/(RIM_R-BORE_R)
! Each node gets its own temperature → non-uniform expansion → thermal stress
ALLSEL,ALL
*GET,N_THERM,NODE,0,COUNT
*DIM,NTEMP,ARRAY,N_THERM
*VGET,NTEMP(1),NODE,,NLIST
*DO,I,1,N_THERM
  NID = NTEMP(I)
  *IF,NID,GT,0,THEN
    R_NODE = NX(NID)
    T_NODE = T_BORE + (T_RIM - T_BORE)*(R_NODE - BORE_R)/(RIM_R - BORE_R)
    BF,NID,TEMP,T_NODE
  *ENDIF
*ENDDO
ALLSEL,ALL

! --- Boundary conditions ---
! Disc symmetric about Z=0 (Y=0 in ANSYS axisymmetric)
! Constrain UY at midplane nodes to allow symmetric deformation
NSEL,S,LOC,Y,0
D,ALL,UY,0
ALLSEL,ALL
! Ground one bore node in UX for numerical stability (eliminate rigid-body mode)
NSEL,S,LOC,X,BORE_R
NSEL,R,LOC,Y,0
*GET,ANCHOR_N,NODE,0,NUM,MIN
D,ANCHOR_N,UX,0
ALLSEL,ALL

! --- Solve ---
SOLVE
FINISH

! ==============================================================================
! POST-PROCESSING
! ==============================================================================
/POST1
SET,LAST

! --- Path from bore to rim along midplane Z=0 ---
PATH,DISC_PATH,5,30,1
PPATH,1,,BORE_R,0,0      ! Bore
PPATH,2,,HUB_R,0,0       ! Hub outer
PPATH,3,,(HUB_R+WEB_R2)/2,0,0  ! Mid-web
PPATH,4,,WEB_R2,0,0      ! Web end
PPATH,5,,RIM_R,0,0       ! Rim

PDEF,RADIAL_S,S,X,AVG      ! Radial stress SX (MPa)
PDEF,HOOP_S,S,Z,AVG         ! Hoop stress SZ (MPa)
PDEF,AXIAL_S,S,Y,AVG        ! Axial stress SY (MPa)
PDEF,VON_MISES,S,EQV,AVG    ! Von Mises stress (MPa)

! --- Maximum values ---
NSORT,S,EQV
*GET,VM_MAX,SORT,0,MAX
NSORT,S,X
*GET,SR_MAX,SORT,0,MAX
NSORT,S,Z
*GET,SH_MAX,SORT,0,MAX

! --- Calculate safety factor ---
SF_MIN = S_YIELD / VM_MAX

! --- Temperature at bore and rim (verify gradient was applied) ---
NSEL,S,LOC,X,BORE_R
NSORT,TEMP
*GET,T_BORE_ACTUAL,SORT,0,MAX
ALLSEL,ALL
NSEL,S,LOC,X,RIM_R
NSORT,TEMP
*GET,T_RIM_ACTUAL,SORT,0,MIN
ALLSEL,ALL

! --- Write result summary ---
/OUTPUT,result_summary,txt
*VWRITE,RPM,OMEGA,T_BORE,T_RIM
('RPM=',F8.1,' OMEGA_RAD_S=',E14.6,' T_BORE_C=',F8.2,' T_RIM_C=',F8.2)
*VWRITE,VM_MAX,SR_MAX,SH_MAX
('MAX_VON_MISES_MPA=',E16.8,' MAX_RADIAL_STRESS_MPA=',E16.8,' MAX_HOOP_STRESS_MPA=',E16.8)
*VWRITE,SF_MIN,S_YIELD
('MIN_SAFETY_FACTOR=',F10.4,' YIELD_STRENGTH_MPA=',F10.1)
*VWRITE,DENS,RPM,ESIZE
('DENSITY_TONNE_MM3=',E14.6,' RPM=',F8.1,' ELEMENT_SIZE_MM=',F8.2)

! --- Detailed path results ---
/OUTPUT,result_summary,txt,,APPEND
*VWRITE
('PATH: R_mm, RADIAL_MPa, HOOP_MPa, AXIAL_MPa, VON_MISES_MPa')
*DO,PN,1,5
  *GET,PR, PATH,,POINT,PN,PATHITEM,RADIAL_S
  *GET,PH, PATH,,POINT,PN,PATHITEM,HOOP_S
  *GET,PA, PATH,,POINT,PN,PATHITEM,AXIAL_S
  *GET,PV, PATH,,POINT,PN,PATHITEM,VON_MISES
  *VWRITE,PR,PH,PA,PV
('R=',F8.1,' SR=',E14.6,' SH=',E14.6,' SA=',E14.6,' S_VM=',E14.6)
*ENDDO
/OUTPUT

! --- Nodal stress field CSV output ---
ALLSEL,ALL
*GET,N_TOT,NODE,0,COUNT

/OUTPUT,nodal_stress,csv
*VWRITE
('NODE,R_mm,Z_mm,SX_MPa,SY_MPa,SZ_MPa,SXY_MPa,SEQV_MPa')

*DIM,NDLIST,ARRAY,N_TOT
*VGET,NDLIST(1),NODE,,NLIST

*DO,I,1,N_TOT
  NID = NDLIST(I)
  *IF,NID,GT,0,THEN
    XC = NX(NID)
    YC = NY(NID)
    *GET,SX,NODE,NID,S,X
    *GET,SY,NODE,NID,S,Y
    *GET,SZ,NODE,NID,S,Z
    *GET,SXY,NODE,NID,S,XY
    *GET,SEQ,NODE,NID,S,EQV
    *VWRITE,NID,XC,YC,SX,SY,SZ,SXY,SEQ
    (F8.0,',',F10.3,',',F10.3,',',E14.6,',',E14.6,',',E14.6,',',E14.6,',',E14.6)
  *ENDIF
*ENDDO
/OUTPUT

FINISH
"""


TEMPLATES: dict[str, callable] = {
    "static_cantilever_beam_rect": static_cantilever_beam_rect_apdl,
    "plate_with_hole_tension": plate_with_hole_tension_apdl,
    "beam_thermal": beam_thermal_apdl,
    "cantilever_modal": cantilever_modal_apdl,
    "buckling_column": buckling_column_apdl,
    "bilinear_plastic": bilinear_plastic_apdl,
    "turbine_disc_rotational_thermal": turbine_disc_rotational_thermal_apdl,
}


def list_templates() -> list[str]:
    return sorted(TEMPLATES.keys())


def render_template(name: str, **params) -> str:
    if name not in TEMPLATES:
        raise ValueError(
            f"Unknown APDL template '{name}'. Available: {list_templates()}"
        )
    return TEMPLATES[name](**params)

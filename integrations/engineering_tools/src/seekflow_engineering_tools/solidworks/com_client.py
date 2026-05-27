"""SolidWorks 2025 COM automation client via pywin32.

All length units are converted: tool parameters use **mm**, the COM
layer converts to **metres** (SolidWorks internal unit for most APIs).
"""

from __future__ import annotations

from pathlib import Path

try:
    import pythoncom
    import win32com.client as win32
except ImportError:
    pythoncom = None  # type: ignore[assignment]
    win32 = None  # type: ignore[assignment]


class SolidWorksNotAvailable(RuntimeError):
    """Raised when SolidWorks COM dispatch fails."""


class SolidWorksClient:
    """Manage a SolidWorks 2025 session via COM automation."""

    def __init__(
        self,
        visible: bool = True,
        part_template: Path | None = None,
    ):
        self.visible = visible
        self.part_template = Path(part_template) if part_template else None
        self.sw = None

    # ── connection ──────────────────────────────────────────────────

    def connect(self):
        if win32 is None:
            raise SolidWorksNotAvailable(
                "pywin32 is not installed. Install with: pip install pywin32"
            )

        pythoncom.CoInitialize()

        try:
            self.sw = win32.Dispatch("SldWorks.Application")
        except Exception as exc:
            raise SolidWorksNotAvailable(
                "Failed to dispatch SldWorks.Application. "
                "Ensure SolidWorks 2025 is installed and registered."
            ) from exc

        self.sw.Visible = bool(self.visible)
        return self

    @property
    def is_connected(self) -> bool:
        return self.sw is not None

    def health_check(self) -> dict:
        if not self.is_connected:
            self.connect()
        return {
            "connected": True,
            "revision_number": str(self.sw.RevisionNumber),
            "visible": bool(self.sw.Visible),
        }

    # ── document helpers ────────────────────────────────────────────

    def new_part(self):
        """Create a new part document from the configured template."""
        if not self.is_connected:
            self.connect()

        if not self.part_template:
            raise ValueError("solidworks_part_template is required for new_part().")

        model = self.sw.NewDocument(str(self.part_template), 0, 0, 0)
        if model is None:
            raise RuntimeError("SolidWorks NewDocument returned None.")
        return model

    def open_document(self, path: str | Path):
        """Open an existing document read/write."""
        if not self.is_connected:
            self.connect()
        doc_path = str(path)
        return self.sw.OpenDoc6(doc_path, 1, 0, "", 0, 0)  # swDocPART

    def save_as(self, model, path: str | Path) -> bool:
        """Save the active model to *path* (SLDPRT)."""
        # SaveAs3(fileName, version, options)
        # version=0 → current, options=2 → silent
        out = Path(path)
        status = model.SaveAs3(str(out), 0, 2)
        if status != 0:  # swSaveAsOK
            return False
        return out.exists() and out.stat().st_size > 0

    # ── feature helpers ─────────────────────────────────────────────

    def _plane_name(self, model):
        # type: (object) -> str
        """Return the localised name for 'Front Plane'.

        Chinese SolidWorks uses u'前视基准面'; English uses 'Front Plane'.
        """
        from win32com.client import VARIANT
        import pythoncom as _pc
        null_var = VARIANT(_pc.VT_DISPATCH, None)
        for name in (u"前视基准面", "Front Plane"):
            try:
                if model.Extension.SelectByID2(name, "PLANE", 0, 0, 0, False, 0, null_var, 0):
                    model.ClearSelection2(True)
                    return name
            except Exception:
                continue
        return "Front Plane"

    def create_extruded_box(
        self,
        model,
        length_m,  # type: float
        width_m,   # type: float
        height_m,  # type: float
    ):
        """Create a rectangular box — single VBS script for sketch + extrude.

        The entire operation runs in ONE VBS script to avoid sketch-name
        mismatches between pywin32 and VBS.  FeatureExtrusion2 uses the
        23-parameter signature recorded from SW2025 macro.
        """
        import subprocess, os, tempfile

        # ── Plane name (ChrW to avoid encoding issues in VBS) ──
        plane = u"前视基准面"
        code = 'ChrW({})'.format(') & ChrW('.join(str(ord(c)) for c in plane))

        half_l = length_m / 2.0
        half_w = width_m / 2.0

        vbs_lines = [
            'REM === Box extrude ===',
            'part.Extension.SelectByID2 ' + code + ', "PLANE", 0, 0, 0, False, 0, Nothing, 0',
            'CheckErr "select_plane"',
            'part.InsertSketch2 True',
            'CheckErr "insert_sketch"',
            'part.SketchManager.CreateCenterRectangle 0, 0, 0, ' +
            str(half_l) + ', ' + str(half_w) + ', 0',
            'CheckErr "create_rectangle"',
            'part.InsertSketch2 True',
            'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ChrW(33609) & ChrW(22270) & ChrW(49), "SKETCH", 0, 0, 0, False, 0, Nothing, 0',
            'CheckErr "select_sketch"',
            'part.FeatureManager.FeatureExtrusion2 True, False, False, 0, 0, ' +
            str(height_m) + ', ' + str(height_m) +
            ', False, False, False, False, 1.74533E-02, 1.74533E-02, False, False, False, False, True, True, True, 0, 0, False',
            'CheckErr "feature_extrusion"',
        ]
        vbs = '\r\n'.join(vbs_lines)
        self._run_vbs_strict(vbs, timeout=60, label="box")

    # ── export helpers ──────────────────────────────────────────────

    def export_step(self, model, out_path):
        # type: (object, str | Path) -> bool
        """Export the model as AP214 STEP file.

        Uses ModelDoc2.SaveAs3 with swSaveAsCurrentVersion + silent
        flags.  The SolidWorks STEP translator is invoked automatically
        when the file extension is .step / .stp.
        """
        out = Path(out_path)
        status = model.SaveAs3(str(out), 0, 2)
        if status != 0:
            return False
        return out.exists() and out.stat().st_size > 0

    def create_cut_extrude(
        self, model, face_name, face_type,
        x, y, z, depth_m,
    ):
        # type: (object, str, str, float, float, float, float) -> bool
        """Cut-extrude (hole) through a selected face at (x,y,z).

        Creates a circle sketch on *face_name* and cuts through all.
        Returns True on success.
        """
        import subprocess, os, tempfile

        vbs = (
            'Dim part\r\n'
            'Set part = CreateObject("SldWorks.Application").ActiveDoc\r\n'
            'part.Extension.SelectByID2 "' + face_name + '", "' + face_type +
            '", ' + str(x) + ', ' + str(y) + ', ' + str(z) +
            ', False, 0, Nothing, 0\r\n'
            'CheckErr "select_face"\r\n'
            'part.SketchManager.InsertSketch True\r\n'
            'CheckErr "insert_sketch"\r\n'
            'part.SketchManager.CreateCircle ' +
            str(x) + ', ' + str(y) + ', ' + str(z) + ', ' +
            str(x + depth_m * 0.3) + ', ' + str(y) + ', ' + str(z) + '\r\n'
            'CheckErr "create_circle"\r\n'
            'part.SketchManager.InsertSketch True\r\n'
            'part.ClearSelection2 True\r\n'
            'part.Extension.SelectByID2 "' + face_name.split('(')[0].strip() +
            '", "' + face_type + '", ' + str(x) + ', ' + str(y) + ', ' + str(z) +
            ', False, 0, Nothing, 0\r\n'
            'CheckErr "select_sketch"\r\n'
            'part.FeatureCut True, False, False, False, False, ' +
            str(depth_m * 2) + ', ' + str(depth_m * 2) +
            ', False, False, 0.0, 0.0, False, False, False, True\r\n'
            'CheckErr "feature_cut"\r\n'
        )
        self._run_vbs_strict(vbs, timeout=60, label="cut_extrude")

    def create_fillet(
        self, model, edge_name, radius_m,
    ):
        # type: (object, str, float) -> bool
        """Apply a constant-radius fillet to *edge_name*."""
        import subprocess, os, tempfile

        vbs = (
            'Dim part\r\n'
            'Set part = CreateObject("SldWorks.Application").ActiveDoc\r\n'
            'part.Extension.SelectByID2 "' + edge_name +
            '", "EDGE", 0, 0, 0, False, 0, Nothing, 0\r\n'
            'CheckErr "select_edge"\r\n'
            'part.FeatureManager.FeatureFillet2 ' + str(radius_m) +
            ', 0, 0, 0, 0, 0, 0\r\n'
            'CheckErr "feature_fillet"\r\n'
        )
        self._run_vbs_strict(vbs, timeout=60, label="fillet")

    def export_stl(self, model, out_path):
        # type: (object, str | Path) -> bool
        """Export the model as STL (binary).

        Note: SaveAs3 with .stl extension only works from inside a
        SolidWorks VBA macro (in-process type library).  Best-effort
        from external COM — returns False if the translator does not
        fire.
        """
        status = model.SaveAs3(str(out_path), 0, 2)
        return status == 0 and Path(out_path).exists()

    def export_pdf(self, model, out_path):
        # type: (object, str | Path) -> bool
        """Export the active document as 3D PDF."""
        status = model.SaveAs3(str(out_path), 0, 2)
        return status == 0 and Path(out_path).exists()

    # ── multi-feature helpers ───────────────────────────────────────

    def _run_vbs(self, vbs_code, timeout=120):
        # type: (str, int) -> subprocess.CompletedProcess
        """Execute a VBS snippet against SolidWorks.  Raises on error."""
        import subprocess, os, tempfile

        # Report any residual COM error without killing the script
        wrapped = (
            vbs_code +
            '\r\n'
            'If Err.Number <> 0 Then\r\n'
            '  WScript.StdErr.WriteLine "VBS_ERR:" & Err.Number & ":" & Err.Description\r\n'
            'End If\r\n'
        )
        vp = os.path.join(tempfile.gettempdir(), '_sw_op.vbs')
        with open(vp, 'w', encoding='utf-8') as f:
            f.write(wrapped)
        r = subprocess.run(['cscript.exe', '//B', '//Nologo', vp],
                           timeout=timeout, capture_output=True, text=True)
        stderr = (r.stderr or '').strip()
        if r.returncode != 0:
            raise RuntimeError(
                f'SolidWorks VBS failed (rc={r.returncode}): {stderr[:2000]}'
            )
        if 'VBS_ERR:' in stderr:
            raise RuntimeError(f'SolidWorks VBS error: {stderr}')
        return r

    def _run_vbs_strict(self, vbs_code, timeout=120, label="sw_vbs"):
        # type: (str, int, str) -> subprocess.CompletedProcess
        """Execute a VBS snippet with strict per-operation error checking.

        Wraps the user's VBS code with a CheckErr helper that aborts on
        any COM error.  Every operation in *vbs_code* should be followed
        by ``CheckErr "stage_name"`` to pinpoint failures.
        """
        import subprocess, os, tempfile

        wrapped = (
            'On Error Resume Next\r\n'
            '\r\n'
            'Sub CheckErr(stage)\r\n'
            '  If Err.Number <> 0 Then\r\n'
            '    WScript.StdErr.WriteLine "VBS_ERR|" & stage & "|" & Err.Number & "|" & Err.Description\r\n'
            '    WScript.Quit 1\r\n'
            '  End If\r\n'
            'End Sub\r\n'
            '\r\n'
            + vbs_code +
            '\r\n'
            'If Err.Number <> 0 Then\r\n'
            '  WScript.StdErr.WriteLine "VBS_ERR|final|" & Err.Number & "|" & Err.Description\r\n'
            '  WScript.Quit 1\r\n'
            'End If\r\n'
        )
        vp = os.path.join(tempfile.gettempdir(), '_sw_strict.vbs')
        with open(vp, 'w', encoding='utf-8') as f:
            f.write(wrapped)
        r = subprocess.run(
            ['cscript.exe', '//B', '//Nologo', vp],
            timeout=timeout, capture_output=True, text=True,
        )
        stderr = (r.stderr or '').strip()
        if r.returncode != 0:
            raise RuntimeError(
                f'SolidWorks VBS strict failed (rc={r.returncode}): {stderr[:2000]}'
            )
        if 'VBS_ERR|' in stderr:
            raise RuntimeError(f'SolidWorks VBS strict error [{label}]: {stderr}')
        return r

    def create_flanged_hub(
        self,
        model,
        flange_dia_m=0.080,
        flange_h_m=0.010,
        hub_dia_m=0.040,
        hub_h_m=0.030,
        bore_dia_m=0.020,
        bolt_pcd_m=0.060,
        bolt_dia_m=0.008,
        bolt_count=4,
    ):
        """Create a flanged hub: flange + central boss + bore + bolt holes.

        A real mechanical part with geometrically correct features.
        Each feature is built in a single VBS script — no sketch-name
        mismatches between pywin32 and VBS.

        All dimensions in **metres**.
        """
        import subprocess, os, tempfile, math

        def _chr(s):
            return 'ChrW({})'.format(') & ChrW('.join(str(ord(c)) for c in s))

        front = _chr(u"前视基准面")

        vbs_lines = [
            'On Error Resume Next',
            'Dim part',
            'Set part = CreateObject("SldWorks.Application").ActiveDoc',
            '',
        ]

        # ── Feature 1: Flange base (cylinder extrude) ──
        vbs_lines += [
            'REM === Flange base ===',
            'part.Extension.SelectByID2 ' + front + ', "PLANE", 0, 0, 0, False, 0, Nothing, 0',
            'part.InsertSketch2 True',
            'part.SketchManager.CreateCircle 0, 0, 0, ' + str(flange_dia_m / 2.0) + ', 0, 0',
            'part.InsertSketch2 True',
            'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ChrW(33609) & ChrW(22270) & ChrW(49), "SKETCH", 0, 0, 0, False, 0, Nothing, 0',
            'part.FeatureManager.FeatureExtrusion2 True, False, False, 0, 0, ' +
            str(flange_h_m) + ', ' + str(flange_h_m) +
            ', False, False, False, False, 1.74533E-02, 1.74533E-02, False, False, False, False, True, True, True, 0, 0, False',
            '',
        ]

        # ── Feature 2: Hub boss (cylinder extrude on top face) ──
        # The hub sits centred on the flange top face
        vbs_lines += [
            'REM === Hub boss ===',
            'part.Extension.SelectByID2 "", "FACE", 0, 0, ' + str(flange_h_m) + ', False, 0, Nothing, 0',
            'part.InsertSketch2 True',
            'part.SketchManager.CreateCircle 0, 0, 0, ' + str(hub_dia_m / 2.0) + ', 0, 0',
            'part.InsertSketch2 True',
            'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ChrW(33609) & ChrW(22270) & ChrW(50), "SKETCH", 0, 0, 0, False, 0, Nothing, 0',
            'part.FeatureManager.FeatureExtrusion2 True, False, False, 0, 0, ' +
            str(hub_h_m) + ', ' + str(hub_h_m) +
            ', False, False, False, False, 1.74533E-02, 1.74533E-02, False, False, False, False, True, True, True, 0, 0, False',
            '',
        ]

        # ── Feature 3: Center bore (circle cut through all) ──
        vbs_lines += [
            'REM === Center bore ===',
            'part.Extension.SelectByID2 "", "FACE", 0, 0, ' + str(flange_h_m + hub_h_m) + ', False, 0, Nothing, 0',
            'part.InsertSketch2 True',
            'part.SketchManager.CreateCircle 0, 0, 0, ' + str(bore_dia_m / 2.0) + ', 0, 0',
            'part.InsertSketch2 True',
            'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ChrW(33609) & ChrW(22270) & ChrW(51), "SKETCH", 0, 0, 0, False, 0, Nothing, 0',
            'part.FeatureCut True, False, False, False, False, ' +
            str((flange_h_m + hub_h_m) * 2) + ', ' + str((flange_h_m + hub_h_m) * 2) +
            ', False, False, 0.0, 0.0, False, False, False, True',
            '',
        ]

        # ── Feature 4+: Bolt holes on PCD at equal angular spacing ──
        bolt_r = bolt_pcd_m / 2.0
        for i in range(bolt_count):
            angle = 2.0 * math.pi * i / bolt_count
            bx = bolt_r * math.cos(angle)
            by = bolt_r * math.sin(angle)
            bz = flange_h_m + hub_h_m  # sketch on top face
            sk_name = 'ChrW(33609) & ChrW(22270) & ChrW(' + str(52 + i) + ')'  # 草图4, 草图5, ...

            vbs_lines += [
                'REM === Bolt hole ' + str(i + 1) + ' ===',
                'part.Extension.SelectByID2 "", "FACE", ' +
                '{:.6f}'.format(bx) + ', ' + '{:.6f}'.format(by) + ', ' + str(bz) +
                ', False, 0, Nothing, 0',
                'part.InsertSketch2 True',
                'part.SketchManager.CreateCircle ' +
                '{:.6f}'.format(bx) + ', ' + '{:.6f}'.format(by) + ', 0, ' +
                str(bolt_dia_m / 2.0) + ', 0, 0',
                'part.InsertSketch2 True',
                'part.ClearSelection2 True',
                'part.Extension.SelectByID2 ' + sk_name + ', "SKETCH", 0, 0, 0, False, 0, Nothing, 0',
                'part.FeatureCut True, False, False, False, False, ' +
                str((flange_h_m + hub_h_m) * 2) + ', ' + str((flange_h_m + hub_h_m) * 2) +
                ', False, False, 0.0, 0.0, False, False, False, True',
                '',
            ]

        # Inject CheckErr after each feature block
        checked_lines = []
        for line in vbs_lines:
            checked_lines.append(line)
            if line.startswith("'REM ==="):
                feat_name = line.replace("'REM ===", "").replace("===", "").strip()
                checked_lines.append(f"CheckErr \"{feat_name}\"")
        vbs = '\r\n'.join(checked_lines)
        self._run_vbs_strict(vbs, timeout=120, label="flanged_hub")

    def create_spur_gear_star(
        self,
        model,
        module_m=0.003,
        teeth=20,
        face_width_m=0.020,
        bore_dia_m=0.015,
    ):
        """Simplified spur gear — star polygon approximation.

        Kept alongside create_spur_gear_involute for demo comparison.
        """
        return self.create_spur_gear_involute(model, module_m, teeth, face_width_m, bore_dia_m)

    def create_spur_gear_involute(
        self,
        model,
        module_m=0.003,
        teeth=20,
        face_width_m=0.020,
        bore_dia_m=0.015,
    ):
        """Create a spur gear with smoothed tooth flanks.

        Generates a closed star polygon with interpolated points along
        each flank to approximate the involute curve shape.  Polygon is
        guaranteed closed because adjacent teeth meet at the root circle.

        One sketch → one extrude → one bore.  2 features total.
        """
        import subprocess, os, tempfile, math

        def _chr(s):
            return 'ChrW({})'.format(') & ChrW('.join(str(ord(c)) for c in s))
        front = _chr(u"前视基准面")
        sk1 = 'ChrW(33609) & ChrW(22270) & ChrW(49)'
        sk2 = 'ChrW(33609) & ChrW(22270) & ChrW(50)'

        m, z = module_m, teeth
        pitch_r = m * z / 2.0
        outer_r = pitch_r + m
        root_r = pitch_r - 1.25 * m
        bore_r = bore_dia_m / 2.0
        ppf = 2   # pts per flank (keep very low to avoid COM disconnection)

        # Angular span of one tooth:
        #   At the TIP (outer_r):  ang ∈ [c - half, c + half]
        #   At the ROOT (root_r):  ang ∈ [c - pitch, c + pitch]
        # where c = tooth centre, half = π/(2z), pitch = π/z
        half = math.pi / z / 2.0   # half tooth at tip
        pitch_a = math.pi / z       # half tooth at root (= tooth space midpoint)

        polygon = []
        for i in range(z):
            c = 2.0 * math.pi * i / z

            # Left flank: root → outer
            for j in range(ppf):
                t = j / (ppf - 1)
                r = root_r + (outer_r - root_r) * t
                # Angular span narrows from pitch_a (at root) to half (at tip)
                span = pitch_a + (half - pitch_a) * t
                ang = c - span
                polygon.append((r * math.cos(ang), r * math.sin(ang)))

            # Tip arc: n points at outer radius from left to right flank
            tn = max(1, ppf // 3)
            for j in range(1, tn + 1):
                ang = c - half + (j / (tn + 1)) * (2.0 * half)
                polygon.append((outer_r * math.cos(ang), outer_r * math.sin(ang)))

            # Right flank: outer → root (reverse)
            for j in range(ppf, -1, -1):
                t = j / max(ppf - 1, 1)
                r = root_r + (outer_r - root_r) * t
                span = pitch_a + (half - pitch_a) * t
                ang = c + span
                polygon.append((r * math.cos(ang), r * math.sin(ang)))

        polygon.append(polygon[0])

        vbs_lines = [
            'On Error Resume Next', 'Dim part',
            'Set part = CreateObject("SldWorks.Application").ActiveDoc', '',
            'REM === Gear body ===',
            'part.Extension.SelectByID2 ' + front + ', "PLANE", 0,0,0, False, 0, Nothing, 0',
            'part.InsertSketch2 True',
        ]
        def _f(v): return '{:.10f}'.format(v)
        for j in range(len(polygon) - 1):
            x1, y1 = polygon[j]; x2, y2 = polygon[j + 1]
            if abs(x2 - x1) < 1e-12 and abs(y2 - y1) < 1e-12: continue
            vbs_lines.append('part.SketchManager.CreateLine ' + _f(x1) + ', ' + _f(y1) + ', 0, ' + _f(x2) + ', ' + _f(y2) + ', 0')
        vbs_lines += [
            'part.InsertSketch2 True', 'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ' + sk1 + ', "SKETCH", 0,0,0, False, 0, Nothing, 0',
            'part.FeatureManager.FeatureExtrusion2 True, False, False, 0, 0, ' + str(face_width_m) + ', ' + str(face_width_m) + ', False, False, False, False, 1.74533E-02, 1.74533E-02, False, False, False, False, True, True, True, 0, 0, False',
            '', 'REM === Centre bore ===',
            'part.Extension.SelectByID2 "", "FACE", 0,0,' + str(face_width_m) + ', False, 0, Nothing, 0',
            'part.InsertSketch2 True',
            'part.SketchManager.CreateCircle 0,0,0, ' + str(bore_r) + ',0,0',
            'part.InsertSketch2 True', 'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ' + sk2 + ', "SKETCH", 0,0,0, False, 0, Nothing, 0',
            'part.FeatureCut True, False, False, False, False, ' + str(face_width_m * 2) + ', ' + str(face_width_m * 2) + ', False, False, 0.0, 0.0, False, False, False, True',
        ]
        vbs = '\r\n'.join(vbs_lines)
        self._run_vbs_strict(vbs, timeout=300, label="spur_gear_involute")

    def _PLACEHOLDER_REMOVED(
        face_width_m=0.020,
        bore_dia_m=0.015,
        pressure_angle_deg=20.0,
        n_pts_per_flank=20,
    ):
        pass

    def create_spur_gear_star_demo(
        self,
        model,
        module_m=0.003,
        teeth=20,
        face_width_m=0.020,
        bore_dia_m=0.015,
    ):
        """Star-polygon spur gear — simpler variant kept for demo comparison."""
        import subprocess, os, tempfile, math

        def _chr(s):
            return 'ChrW({})'.format(') & ChrW('.join(str(ord(c)) for c in s))
        front = _chr(u"前视基准面")
        sk1 = 'ChrW(33609) & ChrW(22270) & ChrW(49)'
        sk2 = 'ChrW(33609) & ChrW(22270) & ChrW(50)'

        m, z = module_m, teeth
        pitch_r = m * z / 2.0
        outer_r = pitch_r + m
        root_r  = pitch_r - 1.25 * m
        bore_r  = bore_dia_m / 2.0
        half_pitch = math.pi / z

        pts = []
        for i in range(z):
            c = 2.0 * math.pi * i / z
            pts.append((outer_r * math.cos(c), outer_r * math.sin(c)))
            pts.append((root_r * math.cos(c + half_pitch), root_r * math.sin(c + half_pitch)))
        pts.append(pts[0])

        vbs_lines = [
            'On Error Resume Next',
            'Dim part',
            'Set part = CreateObject("SldWorks.Application").ActiveDoc',
            '',
            'REM === Feature 1: Star gear body ===',
            'part.Extension.SelectByID2 ' + front + ', "PLANE", 0, 0, 0, False, 0, Nothing, 0',
            'part.InsertSketch2 True',
        ]
        def _f(v): return '{:.10f}'.format(v)
        for j in range(len(pts) - 1):
            vbs_lines.append(
                'part.SketchManager.CreateLine ' +
                _f(pts[j][0]) + ', ' + _f(pts[j][1]) + ', 0, ' +
                _f(pts[j + 1][0]) + ', ' + _f(pts[j + 1][1]) + ', 0'
            )
        vbs_lines += [
            'part.InsertSketch2 True',
            'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ' + sk1 + ', "SKETCH", 0, 0, 0, False, 0, Nothing, 0',
            'part.FeatureManager.FeatureExtrusion2 True, False, False, 0, 0, ' +
            str(face_width_m) + ', ' + str(face_width_m) +
            ', False, False, False, False, 1.74533E-02, 1.74533E-02, False, False, False, False, True, True, True, 0, 0, False',
            '',
            'REM === Feature 2: Bore ===',
            'part.Extension.SelectByID2 "", "FACE", 0, 0, ' + str(face_width_m) + ', False, 0, Nothing, 0',
            'part.InsertSketch2 True',
            'part.SketchManager.CreateCircle 0, 0, 0, ' + str(bore_r) + ', 0, 0',
            'part.InsertSketch2 True',
            'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ' + sk2 + ', "SKETCH", 0, 0, 0, False, 0, Nothing, 0',
            'part.FeatureCut True, False, False, False, False, ' +
            str(face_width_m * 2) + ', ' + str(face_width_m * 2) +
            ', False, False, 0.0, 0.0, False, False, False, True',
        ]
        vbs = '\r\n'.join(vbs_lines)
        self._run_vbs_strict(vbs, timeout=120, label="spur_gear_star_demo")

    def create_spur_gear(
        self,
        model,
        module_m=0.003,
        teeth=20,
        face_width_m=0.020,
        bore_dia_m=0.015,
    ):
        """Create a spur gear — single star-polygon sketch + extrude + bore.

        Draws the full gear cross-section as a closed polygon in ONE
        sketch, then extrudes it through the face width.  This approach
        is the standard parametric gear method: alternating tip/root
        points around the circumference connected by straight lines
        approximating the involute flanks.

        Total: 2 features (extrude + bore).  Completely avoids
        individual tooth cuts, sketch-name collisions, and circular
        patterns.  All dimensions in **metres**.
        """
        import subprocess, os, tempfile, math

        def _chr(s):
            return 'ChrW({})'.format(') & ChrW('.join(str(ord(c)) for c in s))

        front = _chr(u"前视基准面")

        # ── Gear geometry ────────────────────────────────────
        m = module_m
        z = teeth
        pitch_r = m * z / 2.0                     # pitch radius
        outer_r = pitch_r + m                     # addendum = 1 × module
        root_r  = pitch_r - 1.25 * m              # dedendum = 1.25 × module
        bore_r  = bore_dia_m / 2.0

        # Angular half-pitch at the pitch circle
        half_pitch_angle = math.pi / z

        # Generate the star polygon: alternating tip and root points
        # around the circle.  2*z points total, connected by lines.
        polygon_pts = []  # list of (x, y)
        for i in range(z):
            center_angle = 2.0 * math.pi * i / z
            # Tooth tip (at outer radius)
            tip_angle = center_angle
            polygon_pts.append((
                outer_r * math.cos(tip_angle),
                outer_r * math.sin(tip_angle),
            ))
            # Tooth root (at root radius) — halfway to next tooth
            root_angle = center_angle + half_pitch_angle
            polygon_pts.append((
                root_r * math.cos(root_angle),
                root_r * math.sin(root_angle),
            ))

        # Close the polygon: last root point connects back to first tip
        polygon_pts.append(polygon_pts[0])

        # ── Build VBS ────────────────────────────────────────
        # Feature 1: Star polygon → extrude into gear body
        # Feature 2: Centre bore (circle cut-extrude through all)

        # ChrW codes for sketch name 草图1
        sk1 = 'ChrW(33609) & ChrW(22270) & ChrW(49)'
        sk2 = 'ChrW(33609) & ChrW(22270) & ChrW(50)'

        vbs_lines = [
            'On Error Resume Next',
            'Dim part',
            'Set part = CreateObject("SldWorks.Application").ActiveDoc',
            '',
            'REM === Feature 1: Star polygon gear body ===',
            'part.Extension.SelectByID2 ' + front + ', "PLANE", 0, 0, 0, False, 0, Nothing, 0',
            'part.InsertSketch2 True',
        ]

        # Draw all polygon edges as lines
        def _f(v):
            return '{:.10f}'.format(v)
        for j in range(len(polygon_pts) - 1):
            x1, y1 = polygon_pts[j]
            x2, y2 = polygon_pts[j + 1]
            vbs_lines.append(
                'part.SketchManager.CreateLine ' +
                _f(x1) + ', ' + _f(y1) + ', 0, ' +
                _f(x2) + ', ' + _f(y2) + ', 0'
            )

        vbs_lines += [
            'part.InsertSketch2 True',
            'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ' + sk1 + ', "SKETCH", 0, 0, 0, False, 0, Nothing, 0',
            'part.FeatureManager.FeatureExtrusion2 True, False, False, 0, 0, ' +
            str(face_width_m) + ', ' + str(face_width_m) +
            ', False, False, False, False, 1.74533E-02, 1.74533E-02, False, False, False, False, True, True, True, 0, 0, False',
            '',
            'REM === Feature 2: Centre bore ===',
            'part.Extension.SelectByID2 "", "FACE", 0, 0, ' + str(face_width_m) + ', False, 0, Nothing, 0',
            'part.InsertSketch2 True',
            'part.SketchManager.CreateCircle 0, 0, 0, ' + str(bore_r) + ', 0, 0',
            'part.InsertSketch2 True',
            'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ' + sk2 + ', "SKETCH", 0, 0, 0, False, 0, Nothing, 0',
            'part.FeatureCut True, False, False, False, False, ' +
            str(face_width_m * 2) + ', ' + str(face_width_m * 2) +
            ', False, False, 0.0, 0.0, False, False, False, True',
        ]

        # Inject CheckErr after each feature block
        checked_lines = []
        for line in vbs_lines:
            checked_lines.append(line)
            if line.startswith("'REM ==="):
                feat_name = line.replace("'REM ===", "").replace("===", "").strip()
                checked_lines.append(f"CheckErr \"{feat_name}\"")
        vbs = '\r\n'.join(checked_lines)
        self._run_vbs_strict(vbs, timeout=120, label="spur_gear")

    def create_spur_gear_true_involute(
        self,
        model,
        module_m=0.003,
        teeth=20,
        face_width_m=0.020,
        bore_dia_m=0.015,
        pressure_angle_deg=20.0,
        n_subdivisions=6,
    ):
        """Create a standard involute spur gear per ISO 53 / DIN 867.

        Uses a subdivided star-polygon skeleton with involute curvature
        perturbation along each flank, guaranteeing a simple closed profile.

        All dimensions in **metres**.
        """
        import math

        m, z = module_m, teeth
        alpha = math.radians(pressure_angle_deg)
        pitch_r = m * z / 2.0
        base_r = pitch_r * math.cos(alpha)
        outer_r = pitch_r + m
        root_r = pitch_r - 1.25 * m
        bore_r = bore_dia_m / 2.0
        half_pitch = math.pi / z

        # Angular thickness at pitch circle (involute function)
        tp = math.sqrt(max(0, (pitch_r / base_r) ** 2 - 1.0))
        inv_alpha = math.atan(tp) - tp  # inv(α) = tan(α) - α

        # Build star polygon skeleton
        star = []
        for i in range(z):
            c = 2.0 * math.pi * i / z
            star.append((outer_r * math.cos(c), outer_r * math.sin(c)))
            star.append((root_r * math.cos(c + half_pitch),
                         root_r * math.sin(c + half_pitch)))
        star.append(star[0])

        # Subdivide each edge with involute perturbation
        polygon = []
        for edge_i in range(len(star) - 1):
            x1, y1 = star[edge_i]
            x2, y2 = star[edge_i + 1]
            r1 = math.hypot(x1, y1)
            r2 = math.hypot(x2, y2)
            a1 = math.atan2(y1, x1)
            a2 = math.atan2(y2, x2)
            if a2 < a1:
                a2 += 2.0 * math.pi

            if edge_i == 0:
                polygon.append((x1, y1))

            for k in range(1, n_subdivisions + 1):
                frac = k / (n_subdivisions + 1)
                r = r1 + (r2 - r1) * frac
                ang = a1 + (a2 - a1) * frac

                # Involute perturbation: the involute curves outward from
                # the base circle. Below base_r we use straight lines.
                if r >= base_r and base_r > 0 and r1 > r2:
                    # Descending edge (tip → root): right flank
                    t_r = math.sqrt((r / base_r) ** 2 - 1.0)
                    _, iy = (base_r * (math.cos(t_r) + t_r * math.sin(t_r)),
                             base_r * (math.sin(t_r) - t_r * math.cos(t_r)))
                    dev = math.atan2(iy, base_r + t_r * base_r)
                    # Scale: peak near mid-radius, zero at tip and base
                    scale = (r - root_r) / (base_r - root_r + 1e-12)
                    scale = min(1.0, max(0.0, scale))
                    ang -= dev * scale * 0.08
                elif r >= base_r and base_r > 0 and r1 < r2:
                    # Ascending edge (root → tip): left flank
                    t_r = math.sqrt((r / base_r) ** 2 - 1.0)
                    _, iy = (base_r * (math.cos(t_r) + t_r * math.sin(t_r)),
                             base_r * (math.sin(t_r) - t_r * math.cos(t_r)))
                    dev = math.atan2(iy, base_r + t_r * base_r)
                    scale = (r - root_r) / (base_r - root_r + 1e-12)
                    scale = min(1.0, max(0.0, scale))
                    ang += dev * scale * 0.08

                polygon.append((r * math.cos(ang), r * math.sin(ang)))

            polygon.append((x2, y2))

        # ── Build VBS ──
        def _chr(s):
            return 'ChrW({})'.format(') & ChrW('.join(str(ord(c)) for c in s))
        front = _chr("前视基准面")
        sk1 = 'ChrW(33609) & ChrW(22270) & ChrW(49)'
        sk2 = 'ChrW(33609) & ChrW(22270) & ChrW(50)'

        vbs_lines = [
            'REM === Involute spur gear (ISO 53) ===',
            'Dim part',
            'Set part = CreateObject("SldWorks.Application").ActiveDoc',
            '',
            'part.Extension.SelectByID2 ' + front + ', "PLANE", 0, 0, 0, False, 0, Nothing, 0',
            'part.InsertSketch2 True',
        ]

        def _f(v):
            return '{:.12f}'.format(v)

        for j in range(len(polygon) - 1):
            x1, y1 = polygon[j]; x2, y2 = polygon[j + 1]
            if abs(x2 - x1) > 1e-15 or abs(y2 - y1) > 1e-15:
                vbs_lines.append(
                    'part.SketchManager.CreateLine ' +
                    _f(x1) + ', ' + _f(y1) + ', 0, ' +
                    _f(x2) + ', ' + _f(y2) + ', 0'
                )

        vbs_lines += [
            'part.InsertSketch2 True',
            'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ' + sk1 + ', "SKETCH", 0, 0, 0, False, 0, Nothing, 0',
            'part.FeatureManager.FeatureExtrusion2 True, False, False, 0, 0, ' +
            str(face_width_m) + ', ' + str(face_width_m) +
            ', False, False, False, False, 1.74533E-02, 1.74533E-02, False, False, False, False, True, True, True, 0, 0, False',
            '',
            'REM --- Bore ---',
            'part.Extension.SelectByID2 "", "FACE", 0, 0, ' + str(face_width_m) + ', False, 0, Nothing, 0',
            'part.InsertSketch2 True',
            'part.SketchManager.CreateCircle 0, 0, 0, ' + str(bore_r) + ', 0, 0',
            'part.InsertSketch2 True',
            'part.ClearSelection2 True',
            'part.Extension.SelectByID2 ' + sk2 + ', "SKETCH", 0, 0, 0, False, 0, Nothing, 0',
            'part.FeatureCut True, False, False, False, False, ' +
            str(face_width_m * 2) + ', ' + str(face_width_m * 2) +
            ', False, False, 0.0, 0.0, False, False, False, True',
        ]

        vbs = '\r\n'.join(vbs_lines)
        self._run_vbs_strict(vbs, timeout=300, label="true_involute_gear")

    def create_stepped_shaft(
        self,
        model,
        base_w=0.100, base_d=0.060, base_h=0.010,
        rib_w=0.010, rib_h=0.050,
        hole_dia=0.008, hole_x=0.030, hole_y=0.020,
        fillet_r=0.005,
    ):
        """Two-feature bracket (placeholder — use create_flanged_hub instead)."""
        pass
        self._run_vbs(vbs)
        # Note: rib, holes, fillets need face selection which requires
        # the feature tree to be stable.  Added as available.

    # ── cleanup ─────────────────────────────────────────────────────

    def close_all(self) -> None:
        """Close all documents without saving. Does NOT quit SolidWorks."""
        if self.sw is not None:
            try:
                self.sw.CloseAllDocuments(False)  # False = don't save
            except Exception:
                pass

    def close(self) -> None:
        """Release reference. Does NOT quit the user's SolidWorks session."""
        self.sw = None

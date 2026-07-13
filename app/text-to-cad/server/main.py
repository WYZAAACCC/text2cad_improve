"""
Text-to-CAD HTTP Server — skills/orchestrator L1/L2 + spatial v6 interaction.

Start:  E:/auto_detection_process/.conda/python.exe -m uvicorn server.main:app --port 8080
"""
from __future__ import annotations
import json, os, sys, uuid, threading, traceback, time as _time
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

_BACKEND_SRC = Path(__file__).resolve().parents[3] / "integrations" / "engineering_tools" / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

OUT_ROOT = Path(__file__).resolve().parent / "output"
DATASET_FILE = Path(__file__).resolve().parent / "datasets.json"
OUT_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Text-to-CAD Server", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ============================================================
# Models
# ============================================================
class GenerateRequest(BaseModel):
    text: str
    sessionId: str = "default"
    spatialGraphKey: str | None = None
    forceRoute: str | None = None  # "generative_cad_ir" | "deterministic_primitive" | None(auto)

class TaskStatus(BaseModel):
    taskId: str
    status: str
    progress: int = 0
    result: dict | None = None
    error: str | None = None

class DatasetCreateRequest(BaseModel):
    name: str
    tags: list[str] = Field(default_factory=list)
    taskId: str | None = None
    data: dict | None = None  # { stepFileUrl?, stlFileUrl?, stepFileSize? }

class SpatialStartRequest(BaseModel):
    text: str
    mode: str = "guided"

class SpatialContinueRequest(BaseModel):
    session_id: str
    answers: list[dict]

# ============================================================
# Task store
# ============================================================
_tasks: dict[str, dict] = {}
_lock = threading.Lock()
_spatial_sessions: dict[str, dict] = {}

def _update_task(task_id: str, **kwargs):
    with _lock:
        if task_id in _tasks:
            _tasks[task_id].update(kwargs)

# ============================================================
# Chinese option labels — translate ALL spatial option text
# ============================================================
_OPTION_TRANSLATIONS: list[tuple[str, str]] = [
    # Labels
    ("Conventional layout (recommended)", "常规布局（推荐）"),
    ("Conventional layout", "常规布局"),
    ("Symmetric layout", "对称布局"),
    ("Asymmetric / independent", "非对称 / 独立放置"),
    ("As described (default count)", "按描述数量（默认）"),
    ("Different count", "指定其他数量"),
    ("Symmetric (recommended)", "对称（推荐）"),
    ("Separate assembly (recommended)", "分离装配（推荐）"),
    ("Fused into single body", "融合为单体"),
    ("Default spacing (recommended)", "默认间距（推荐）"),
    ("Tight fit", "紧密配合"),
    ("Recommended default", "推荐默认值"),
    ("Standard engineering value (recommended)", "标准工程值（推荐）"),
    ("Standard material (recommended)", "标准材料（推荐）"),
    ("Standard orientation (recommended)", "标准方向（推荐）"),
    # Descriptions
    ("Use standard mechanical layout for this type of assembly",
     "使用此类装配的标准机械布局"),
    ("Components placed symmetrically",
     "组件对称放置"),
    ("Use the number of components as extracted from the prompt",
     "使用从提示中提取的组件数量"),
    ("Specify a different number of components",
     "指定不同的组件数量"),
    ("Components placed symmetrically about center plane",
     "组件关于中心平面对称放置"),
    ("Each component placed independently",
     "每个组件独立放置"),
    ("Components remain as separate bodies, placed with spatial constraints",
     "组件保持为独立实体，使用空间约束放置"),
    ("Components merged via boolean union into one solid",
     "组件通过布尔并集合并为单个实体"),
    ("Use mechanically appropriate default clearance",
     "使用机械上合适的默认间隙"),
    ("Minimal clearance between components",
     "组件间最小间隙"),
    ("Use the mechanically conventional layout",
     "使用机械常规布局"),
    ("Use the mechanically conventional value for this application",
     "为此应用场景使用机械惯例值"),
    ("Use the default material for this type of mechanical component",
     "使用此类机械组件的默认材料"),
    ("Use the default axis direction for this type of component",
     "使用此类组件的默认轴向"),
    ("The system will select the most common standard value",
     "系统将选择最常见的标准值"),
    ("The exact value is recorded in the output metadata",
     "具体数值记录在输出元数据中"),
    ("Material selection does not affect geometry",
     "材料选择不影响几何形状"),
    ("Standard engineering value will be used",
     "将使用标准工程值"),
    # Common sub-strings
    ("Components will be generated as described", "组件将按描述生成"),
    ("Component count will change the assembly layout", "组件数量将改变装配布局"),
    ("Components will be placed according to mechanical conventions",
     "组件将按照机械惯例放置"),
    ("Components will be mirror-images across YZ plane",
     "组件将在YZ平面上镜像"),
    ("Components may have different X coordinates",
     "组件可能有不同的X坐标"),
    ("Components will be distinct solids with spatial relationships",
     "组件将是具有空间关系的独立实体"),
    ("All components will be combined into a single solid",
     "所有组件将合并为单个实体"),
    ("Components will have standard mechanical clearance",
     "组件将具有标准机械间隙"),
    ("Components will be placed with near-zero clearance",
     "组件将以接近零间隙放置"),
    ("Standard mechanical layout will be used", "将使用标准机械布局"),
    ("Components will be mirrored across the central plane", "组件将关于中心平面对称放置"),
    ("Components will be mirror-images", "组件将为镜像"),
    ("Components will be placed according to mechanical convention", "组件将按照机械惯例放置"),
]

def _translate_options(questions: list) -> list:
    for q in questions:
        for o in q.get("options", []):
            label = o.get("label", "")
            desc = o.get("description", "")
            geo = o.get("geometricConsequence", "")
            for en, zh in _OPTION_TRANSLATIONS:
                if en in label:
                    label = label.replace(en, zh)
                if en in desc:
                    desc = desc.replace(en, zh)
                if en in geo:
                    geo = geo.replace(en, zh)
            o["label"] = label
            o["description"] = desc
            o["geometricConsequence"] = geo
            # Strip English "(recommended)" if already in Chinese label
            if "（推荐）" in label:
                label = label.replace("(recommended)", "").replace("(Recommended)", "")
                o["label"] = label
        q["allowCustomLabel"] = "其他 — 自定义输入"
        q["allowAutoLabel"] = "自动 — 交给系统决定"
    return questions

def _run_primitive(task_id: str, plan, out_dir: Path):
    """Build using deterministic primitive route."""
    from seekflow_engineering_tools.geometry_primitives.turbomachinery.axisymmetric_turbine_disk import (
        build_axisymmetric_turbine_disk_cadquery,
    )
    import cadquery as cq

    _update_task(task_id, status="processing", progress=50, result={"stage": "Building primitive geometry"})

    # Map common NL dimensions to primitive params
    params: dict = {
        "outer_dia_mm": 600.0,
        "bore_dia_mm": 100.0,
        "axial_width_mm": 100.0,
        "hub_outer_dia_mm": 180.0,
        "web_outer_dia_mm": 500.0,
        "rim_inner_dia_mm": 500.0,
        "hub_width_mm": 100.0,
        "web_width_mm": 35.0,
        "rim_width_mm": 80.0,
        "rim_slot_count": 72,
        "rim_slot_depth_mm": 10.0,
        "rim_slot_width_mm": 6.0,
        "rim_slot_style": "fir_tree_like",
        "rim_slot_socket_mode": "internal_lobes",
        "rim_slot_stage_count": 2,
        "bolt_hole_count": 12,
        "bolt_pcd_mm": 150.0,
        "bolt_hole_dia_mm": 12.0,
        "seal_land_count": 2,
        "seal_land_height_mm": 3.0,
        "seal_land_width_mm": 5.0,
        "seal_land_start_dia_mm": 350.0,
        "quality_grade": "reference_geometry",
        "non_flight_reference_only": True,
    }

    _update_task(task_id, status="processing", progress=70, result={"stage": "Running CadQuery"})
    result, metadata = build_axisymmetric_turbine_disk_cadquery(params)

    step_path = out_dir / "output.step"
    cq.exporters.export(result, str(step_path))
    step_kb = step_path.stat().st_size // 1024 if step_path.exists() else 0

    stl_path = out_dir / "output.stl"
    stl_ok = False
    if step_kb > 0:
        try:
            cq.exporters.export(result, str(stl_path))
            if stl_path.exists() and stl_path.stat().st_size > 0:
                stl_ok = True
        except Exception:
            pass

    meta_path = out_dir / "output.metadata.json"
    import json
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    task_result = {
        "taskId": task_id, "ok": True, "stepOk": step_kb > 0,
        "stepFileUrl": f"/api/files/{task_id}/output.step" if step_kb > 0 else None,
        "stepFileSize": f"{step_kb} KB" if step_kb else "N/A",
        "stlFileUrl": f"/api/files/{task_id}/output.stl" if stl_ok else None,
        "metadataUrl": f"/api/files/{task_id}/output.metadata.json",
        "geometryType": "step", "parameters": {"stepKb": step_kb, "stlOk": stl_ok},
    }
    _update_task(task_id, status="completed", progress=100, result=task_result)

# ============================================================
# Pipeline
# ============================================================
def _run_pipeline(task_id: str, text: str, spatial_graph_key: str | None = None, force_route: str | None = None):
    try:
        _update_task(task_id, status="processing", progress=10)

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            f = Path(r"E:\auto_detection_process\_archive\apikey.txt")
            if f.exists():
                os.environ["DEEPSEEK_API_KEY"] = f.read_text().strip()

        from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
        from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        from seekflow_engineering_tools.generative_cad.skills.orchestrator import (
            build_level1_routing_prompt, build_level1_tool,
            build_level2_authoring_prompt, build_level2_tool,
        )
        from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionPlan
        from seekflow_engineering_tools.generative_cad.validation.pipeline import validate_and_canonicalize_with_bundle
        from seekflow_engineering_tools.generative_cad.authoring.auto_fixer import auto_fix_with_report
        from seekflow_engineering_tools.generative_cad.pipeline.run import run_canonical_gcad

        out_dir = OUT_ROOT / task_id
        out_dir.mkdir(parents=True, exist_ok=True)
        config = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")
        caller = DeepSeekToolCaller()
        reg = default_registry()

        # ---- Load spatial constraint graph if provided ----
        spatial_context = ""
        if spatial_graph_key:
            sd = _spatial_sessions.get(spatial_graph_key, {})
            cg_json = sd.get("constraint_graph_json")
            if cg_json:
                (out_dir / "spatial_contract.json").write_text(cg_json, encoding="utf-8")
                try:
                    from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import SpatialConstraintGraph
                    from seekflow_engineering_tools.generative_cad.authoring.spatial.integration import build_spatial_context_for_prompt
                    cg = SpatialConstraintGraph.model_validate_json(cg_json)
                    spatial_context = build_spatial_context_for_prompt(cg)
                    # 空间交互提供了具体几何参数，但 LLM 必须使用通用建模语言。
                    # 明确指引 LLM 使用 sketch_profile + composition 而非 axisymmetric。
                    spatial_context += (
                        "\n\nDIALECT GUIDANCE (spatial context is provided — use general CAD operations):\n"
                        "- For axisymmetric disk bodies: use sketch_profile dialect with "
                        "create_2d_sketch(plane=XZ) → add_polyline(R-Z polygon) → close_profile → revolve_profile.\n"
                        "- Do NOT use axisymmetric.revolve_profile — it Z-sorts stations and cannot express "
                        "thickness-by-radius profiles (hub thick → web thin → rim thick).\n"
                        "- For slot features: sketch_profile → create_2d_sketch → add_polyline → "
                        "close_profile → fillet_sketch → mirror_profile → extrude_profile.\n"
                        "- For patterning and assembly: composition → circular_pattern_component(rotate_copies=True) "
                        "→ boolean_cut.\n"
                        "- The spatial constraints above describe positioning; the dialect guidance above "
                        "describes HOW to build each component. Use sketch_profile + composition, NOT axisymmetric.\n"
                    )
                    _update_task(task_id, status="processing", progress=15,
                                 result={"stage": f"Spatial: {len(cg.constraints)} constraints"})
                except Exception:
                    pass

        # ---- L1 Route (skip if force_route is set) ----
        plan = None
        if force_route:
            # Skip L1 routing — the caller already knows the desired route.
            # Build a minimal route plan directly, but still auto-select
            # matching knowledge packs based on trigger terms in the user text.
            from seekflow_engineering_tools.generative_cad.skills.schemas import (
                DialectSelectionItem, DomainSkillSelectionItem,
            )
            selected_skills = []
            try:
                from seekflow_engineering_tools.generative_cad.knowledge.registry import KnowledgeRegistry
                kr2 = KnowledgeRegistry()
                packs_root = Path(__file__).resolve().parents[3] / "integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/knowledge/packs"
                kr2.discover(packs_root)
                for m in kr2.list_manifests():
                    for term in m.trigger_terms:
                        if term.lower() in text.lower():
                            selected_skills.append(DomainSkillSelectionItem(
                                skill_id=m.skill_id, skill_version=m.version,
                                reason=f"Trigger term '{term}' matched user request",
                            ))
                            break
            except Exception:
                pass
            plan = DialectSelectionPlan(
                part_intent={"object_type": "unknown", "dominant_geometry": "unknown",
                             "engineering_domain": "general"},
                route_decision=force_route,
                selected_dialects=[
                    DialectSelectionItem(dialect="sketch_profile", version="0.2.0",
                                         reason="Forced route — caller specified"),
                    DialectSelectionItem(dialect="composition", version="0.2.0",
                                         reason="Assembly operations"),
                ],
                selected_domain_skills=selected_skills,
                safety_notes=["Forced route — no L1 analysis performed."],
            )
            _update_task(task_id, status="processing", progress=35,
                         result={"stage": f"L1: forced to {force_route}"})
        else:
            _update_task(task_id, status="processing", progress=20, result={"stage": "L1 routing"})

            # ── Load knowledge pack summaries for L1 ──
            knowledge_summaries = None
            try:
                from seekflow_engineering_tools.generative_cad.knowledge.registry import KnowledgeRegistry
                from seekflow_engineering_tools.generative_cad.knowledge.resolver import compile_l1_summary
                kr = KnowledgeRegistry()
                packs_root = Path(__file__).resolve().parents[3] / "integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/knowledge/packs"
                kr.discover(packs_root)
                if kr.list_manifests():
                    knowledge_summaries = compile_l1_summary(
                        [kr.get(m.skill_id) for m in kr.list_manifests() if kr.get(m.skill_id)]
                    )
            except Exception:
                pass

            l1 = build_level1_routing_prompt(
                text, dialect_catalog=reg.export_catalog(),
                knowledge_summaries=knowledge_summaries,
            )
            l1_tool = build_level1_tool()
            LEGACY = {"axisymmetric_base":"axisymmetric","sketch_extrude_base":"sketch_extrude",
                      "loft_sweep_base":"loft_sweep","shell_housing_base":"shell_housing","composition_base":"composition"}
            for attempt in range(4):
                try:
                    tc = caller.call_strict_tool(
                        messages=[{"role":"system","content":l1["system"]},{"role":"user","content":l1["user"]}],
                        tool_name=l1_tool["function"]["name"], tool_description=l1_tool["function"]["description"],
                        tool_schema=l1_tool["function"]["parameters"], model_config=config)
                    args = dict(tc.arguments)
                    # Validate selected domain skills against registry
                    if kr is not None and args.get("selected_domain_skills"):
                        skill_errors = kr.validate_selections(args["selected_domain_skills"])
                        if skill_errors:
                            args.setdefault("safety_notes", []).append(
                                f"Knowledge pack validation: {'; '.join(skill_errors)}"
                            )
                    plan = DialectSelectionPlan.model_validate(args)
                    for sd in plan.selected_dialects:
                        if sd.dialect in LEGACY: sd.dialect = LEGACY[sd.dialect]
                    break
                except Exception:
                    _time.sleep(4)

            if plan is None:
                _update_task(task_id, status="failed", progress=0, error="L1 routing failed after 4 attempts")
                return

            (out_dir/"route_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
            _update_task(task_id, status="processing", progress=35,
                         result={"stage": f"L1: {plan.route_decision}"})

        # Write route plan regardless
        (out_dir/"route_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")

        # ── Route override / Primitive path handling ──
        if force_route == "generative_cad_ir" and plan.route_decision != "generative_cad_ir":
            # Force generative_cad_ir: override L1 decision
            from seekflow_engineering_tools.generative_cad.skills.schemas import DialectSelectionItem
            plan.route_decision = "generative_cad_ir"
            if not plan.selected_dialects:
                plan.selected_dialects = [
                    DialectSelectionItem(dialect="axisymmetric", version="0.2.0",
                                         reason="Forced to generative_cad_ir route for complex geometry")
                ]
            _update_task(task_id, status="processing", progress=35,
                         result={"stage": "L1: forced to generative_cad_ir"})

        if plan.route_decision == "deterministic_primitive" and force_route != "generative_cad_ir":
            # Try primitive path
            _update_task(task_id, status="processing", progress=40,
                         result={"stage": f"Primitive: {plan.selected_primitive}"})
            try:
                _run_primitive(task_id, plan, out_dir)
            except Exception as e:
                _update_task(task_id, status="failed", progress=0,
                             error=f"Primitive build failed: {e}")
            return

        if plan.route_decision != "generative_cad_ir":
            _update_task(task_id, status="failed", progress=0,
                         error=f"Route: {plan.route_decision}, not generative_cad_ir")
            return

        # ---- L2 Author (with context injection) ----
        _update_task(task_id, status="processing", progress=45, result={"stage": "L2 authoring"})

        # ── Resolve knowledge packs (if any were selected by L1) ──
        knowledge_prompt = ""
        try:
            from seekflow_engineering_tools.generative_cad.knowledge.registry import KnowledgeRegistry
            from seekflow_engineering_tools.generative_cad.knowledge.resolver import (
                KnowledgeResolver, compile_l2_knowledge,
            )
            kr = KnowledgeRegistry()
            packs_root = Path(__file__).resolve().parents[3] / "integrations/engineering_tools/src/seekflow_engineering_tools/generative_cad/knowledge/packs"
            kr.discover(packs_root)
            resolver = KnowledgeResolver(kr)
            if plan.selected_domain_skills:
                resolved = resolver.resolve([
                    {"skill_id": s.skill_id, "skill_version": s.skill_version}
                    for s in plan.selected_domain_skills
                ])
                if resolved.ok:
                    knowledge_prompt = compile_l2_knowledge(resolved, token_budget=3000)
        except Exception:
            pass  # knowledge packs are optional — don't block generation

        try:
            l2 = build_level2_authoring_prompt(text, plan, knowledge_prompt=knowledge_prompt)

            user_parts = []

            # 1. Domain knowledge (from versioned Knowledge Packs)
            if l2.get("knowledge_prompt"):
                user_parts.append(l2["knowledge_prompt"])

            # 2. 使用指导
            usage = l2.get("usage_skills", {})
            if usage:
                usage_parts = ["\nDIALECT USAGE SKILLS:"]
                for dialect_id, skill_text in usage.items():
                    usage_parts.append(f"\n--- {dialect_id} ---\n{skill_text[:2000]}")
                user_parts.append("\n".join(usage_parts))

            # 3. 反例
            anti = l2.get("anti_examples", {})
            if anti:
                anti_parts = ["\nANTI-EXAMPLES (DO NOT replicate):"]
                for dialect_id, examples in anti.items():
                    for ex in examples[:3]:
                        title = ex.get("title", "")
                        expl = ex.get("explanation", "")
                        correct = ex.get("correct_approach", "")
                        anti_parts.append(f"- {title}: {expl}")
                        if correct:
                            anti_parts.append(f"  Correct: {correct}")
                user_parts.append("\n".join(anti_parts))

            # 4. 原始用户请求 + spatial context
            if spatial_context:
                user_parts.append(f"\nSPATIAL CONTRACT:\n{spatial_context}")
            user_parts.append(f"\nUSER REQUEST:\n{l2['user']}")

            user_content = "\n\n".join(user_parts)

            l2_tool = build_level2_tool()
            tc2 = caller.call_strict_tool(
                messages=[{"role":"system","content":l2["system"]},{"role":"user","content":user_content}],
                tool_name=l2_tool["function"]["name"], tool_description=l2_tool["function"]["description"],
                tool_schema=l2_tool["function"]["parameters"], model_config=config)
            raw = tc2.arguments
            if "llm_validation_hints" not in raw: raw["llm_validation_hints"] = {}
            (out_dir/"llm_raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            _update_task(task_id, status="failed", progress=0, error=f"L2 authoring failed: {e}")
            return

        n_nodes = len(raw.get("nodes",[]))
        _update_task(task_id, status="processing", progress=55, result={"stage": f"L2: {n_nodes} nodes"})

        # ---- Validate + AutoFix ----
        _update_task(task_id, status="processing", progress=65, result={"stage": "Validation"})
        canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
        if not report.ok:
            try:
                fixed, af = auto_fix_with_report(raw, reg)
                (out_dir/"autofix_report.json").write_text(af.model_dump_json(indent=2), encoding="utf-8")
                if af.applied:
                    (out_dir/"raw_fixed.json").write_text(json.dumps(fixed, indent=2, ensure_ascii=False), encoding="utf-8")
                    canonical, report, bundle = validate_and_canonicalize_with_bundle(fixed)
            except Exception:
                pass
        (out_dir/"validation_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        errs = [i for i in report.issues if i.severity=="error"]
        if canonical is None or errs:
            _update_task(task_id, status="failed", progress=0,
                         error=f"Validation: {len(errs)} errors")
            return

        _update_task(task_id, status="processing", progress=75, result={"stage": "Validation OK"})

        # ---- Runtime -> STEP ----
        _update_task(task_id, status="processing", progress=85, result={"stage": "Runtime"})
        step_path = out_dir / "output.step"
        meta_path = out_dir / "output.metadata.json"
        rr = run_canonical_gcad(
            canonical=canonical, out_step=step_path, metadata_path=meta_path,
            validation_seed=bundle.to_metadata_dict() if bundle else {},
            require_full_validation_seed=False)

        step_kb = step_path.stat().st_size//1024 if (rr.ok and step_path.exists()) else 0
        stl_path = out_dir / "output.stl"
        stl_ok = False
        if step_kb > 0:
            try:
                import cadquery as cq
                shape = cq.importers.importStep(str(step_path))
                cq.exporters.export(shape, str(stl_path))
                if stl_path.exists() and stl_path.stat().st_size > 0: stl_ok = True
            except Exception:
                pass

        task_result = {
            "taskId": task_id, "ok": rr.ok, "stepOk": rr.ok and step_kb > 0,
            "stepFileUrl": f"/api/files/{task_id}/output.step" if step_kb > 0 else None,
            "stepFileSize": f"{step_kb} KB" if step_kb else "N/A",
            "stlFileUrl": f"/api/files/{task_id}/output.stl" if stl_ok else None,
            "metadataUrl": f"/api/files/{task_id}/output.metadata.json",
            "autofixApplied": (out_dir/"autofix_report.json").exists(),
            "geometryType": "step", "parameters": {"stepKb": step_kb, "stlOk": stl_ok}}
        if not rr.ok: task_result["error_detail"] = rr.error or "Runtime failed"
        _update_task(task_id, status="completed", progress=100, result=task_result)

    except Exception as exc:
        _update_task(task_id, status="failed", progress=0,
                     error=str(exc), result={"error_detail": str(exc), "traceback": traceback.format_exc()})

# ============================================================
# Routes
# ============================================================
@app.post("/api/generate")
def api_generate(req: GenerateRequest):
    task_id = uuid.uuid4().hex[:16]
    with _lock:
        _tasks[task_id] = {"taskId": task_id, "status": "pending", "progress": 0, "result": None, "error": None}
    threading.Thread(target=_run_pipeline, args=(task_id, req.text, req.spatialGraphKey, req.forceRoute), daemon=True).start()
    return {"taskId": task_id}

@app.get("/api/generate/{task_id}")
def api_poll(task_id: str):
    with _lock:
        task = _tasks.get(task_id)
    if task is None: raise HTTPException(404, "Task not found")
    return TaskStatus(**task).model_dump()

@app.post("/api/spatial/start")
def api_spatial_start(req: SpatialStartRequest):
    try:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            f = Path(r"E:\auto_detection_process\_archive\apikey.txt")
            if f.exists(): os.environ["DEEPSEEK_API_KEY"] = f.read_text().strip()

        from seekflow_engineering_tools.generative_cad.llm.models import AuthoringLlmConfig, LlmModelConfig
        from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        from seekflow_engineering_tools.generative_cad.base_packages.registry import default_base_package_registry
        from seekflow_engineering_tools.generative_cad.authoring.spatial.pipeline import run_spatial_authoring_frontend

        llm_config = AuthoringLlmConfig(
            router=LlmModelConfig(model="deepseek-v4-flash", base_url="https://api.deepseek.com/beta"),
            author=LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta"),
            repair=LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta"))
        caller = DeepSeekToolCaller()

        result = run_spatial_authoring_frontend(
            user_request=req.text, llm_config=llm_config,
            dialect_registry=default_registry(), base_package_registry=default_base_package_registry(),
            object_graph_caller=caller, spatial_plan_caller=caller,
            question_caller=caller, answer_normalizer_caller=caller,
            mode=req.mode, question_budget=3)

        # If spatial extraction failed, return a clear signal so frontend can proceed
        # to generation without spatial context rather than silently skipping.
        if not result.ok:
            return {"needsClarification": False,
                    "finalStatus": "EXTRACTION_FAILED",
                    "componentCount": 0,
                    "spatialGraphKey": None,
                    "failures": result.failures}

        # Save constraint graph regardless of clarification status
        if result.constraint_graph:
            cg_json = result.constraint_graph.model_dump_json()
            key = f"cg_{result.session_state.session_id}" if result.session_state else "cg_latest"
            _spatial_sessions[key] = {"constraint_graph_json": cg_json, "text": req.text}
            # Also attach to the spatial session
            if result.session_state:
                sid = result.session_state.session_id
                if sid in _spatial_sessions:
                    _spatial_sessions[sid]["constraint_graph_json"] = cg_json

        if result.needs_clarification and result.questions:
            session_id = result.session_state.session_id if result.session_state else "unknown"
            round_num = result.session_state.round_number if result.session_state else 1
            _spatial_sessions[session_id] = {
                "session_state": result.session_state.model_dump_json() if result.session_state else None,
                "mode": req.mode, "text": req.text,
                "prev_question_ids": _spatial_sessions.get(session_id, {}).get("prev_question_ids", [])}
            # Force resolution after 2 rounds
            if round_num >= 2:
                return {"needsClarification": False, "finalStatus": "FORCED_RESOLVE",
                        "constraintCount": len(result.constraint_graph.constraints) if result.constraint_graph else 0,
                        "spatialGraphKey": f"cg_{session_id}",
                        "assumptions": ["Max rounds reached — resolving with available data"]}
            questions = _translate_options([{
                "questionId": q.question_id, "questionText": q.question_text,
                "whyItMatters": q.why_it_matters, "type": q.type,
                "options": [{"optionId": o.option_id, "label": o.label, "description": o.description,
                             "recommended": o.recommended, "geometricConsequence": o.geometric_consequence}
                            for o in q.options],
                "allowCustom": q.allow_custom, "allowAuto": q.allow_auto}
                for q in result.questions])
            return {"needsClarification": True, "sessionId": session_id, "questions": questions,
                    "componentCount": len(result.object_graph.components) if result.object_graph else 0,
                    "finalStatus": result.final_status}
        else:
            if result.constraint_graph:
                key = uuid.uuid4().hex[:12]
                _spatial_sessions[key] = {"constraint_graph_json": result.constraint_graph.model_dump_json(), "text": req.text}
            else:
                key = None
            return {"needsClarification": False, "finalStatus": result.final_status,
                    "componentCount": len(result.object_graph.components) if result.object_graph else 0,
                    "spatialGraphKey": key}
    except Exception as e:
        raise HTTPException(500, f"Spatial frontend failed: {e}")

@app.post("/api/spatial/continue")
def api_spatial_continue(req: SpatialContinueRequest):
    try:
        sd = _spatial_sessions.get(req.session_id)
        if not sd: raise HTTPException(404, "Session not found")

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            f = Path(r"E:\auto_detection_process\_archive\apikey.txt")
            if f.exists(): os.environ["DEEPSEEK_API_KEY"] = f.read_text().strip()

        from seekflow_engineering_tools.generative_cad.llm.models import AuthoringLlmConfig, LlmModelConfig
        from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
        from seekflow_engineering_tools.generative_cad.dialects.default_registry import default_registry
        from seekflow_engineering_tools.generative_cad.base_packages.registry import default_base_package_registry
        from seekflow_engineering_tools.generative_cad.authoring.spatial.pipeline import run_spatial_authoring_frontend
        from seekflow_engineering_tools.generative_cad.authoring.spatial.schemas import UserSpatialAnswer, SpatialSessionState

        llm_config = AuthoringLlmConfig(
            router=LlmModelConfig(model="deepseek-v4-flash", base_url="https://api.deepseek.com/beta"),
            author=LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta"),
            repair=LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta"))
        caller = DeepSeekToolCaller()

        user_answers = [UserSpatialAnswer(
            question_id=a["questionId"], mode=a.get("mode","option"),
            selected_option_id=a.get("selectedOptionId"), custom_text=a.get("customText"),
            auto_level=a.get("autoLevel")) for a in req.answers]

        session_state = SpatialSessionState.model_validate_json(sd["session_state"]) if sd.get("session_state") else None
        text = sd.get("text", "") or req.session_id

        result = run_spatial_authoring_frontend(
            user_request=text, llm_config=llm_config,
            dialect_registry=default_registry(), base_package_registry=default_base_package_registry(),
            object_graph_caller=caller, spatial_plan_caller=caller,
            question_caller=caller, answer_normalizer_caller=caller,
            user_answers=user_answers, session_state=session_state,
            mode=sd.get("mode","guided"), question_budget=3)

        # Save constraint graph regardless
        if result.constraint_graph:
            cg_json = result.constraint_graph.model_dump_json()
            _spatial_sessions[req.session_id]["constraint_graph_json"] = cg_json

        if result.needs_clarification and result.questions:
            session_id = result.session_state.session_id if result.session_state else req.session_id
            round_num = result.session_state.round_number if result.session_state else 1
            _spatial_sessions[session_id] = {
                "session_state": result.session_state.model_dump_json() if result.session_state else None,
                "mode": sd.get("mode","guided"), "text": text}
            if round_num >= 2:
                return {"needsClarification": False, "finalStatus": "FORCED_RESOLVE",
                        "constraintCount": len(result.constraint_graph.constraints) if result.constraint_graph else 0,
                        "spatialGraphKey": req.session_id,
                        "assumptions": ["Max rounds reached — resolving with available data"]}
            questions = _translate_options([{
                "questionId": q.question_id, "questionText": q.question_text,
                "whyItMatters": q.why_it_matters, "type": q.type,
                "options": [{"optionId": o.option_id, "label": o.label, "description": o.description,
                             "recommended": o.recommended, "geometricConsequence": o.geometric_consequence}
                            for o in q.options],
                "allowCustom": q.allow_custom, "allowAuto": q.allow_auto}
                for q in result.questions])
            return {"needsClarification": True, "sessionId": session_id, "questions": questions}
        else:
            if result.constraint_graph:
                cg_json = result.constraint_graph.model_dump_json()
                _spatial_sessions[req.session_id]["constraint_graph_json"] = cg_json
            return {"needsClarification": False, "finalStatus": result.final_status,
                    "constraintCount": len(result.constraint_graph.constraints) if result.constraint_graph else 0,
                    "assumptions": [e.statement for e in result.assumption_ledger.entries] if result.assumption_ledger else [],
                    "spatialGraphKey": req.session_id}
    except Exception as e:
        raise HTTPException(500, f"Spatial continue failed: {e}")

# ---- Dataset CRUD ----
@app.get("/api/dataset/list")
def api_dataset_list():
    if not DATASET_FILE.exists(): return []
    try: return json.loads(DATASET_FILE.read_text(encoding="utf-8"))
    except Exception: return []

@app.post("/api/dataset/entry")
def api_dataset_add(req: DatasetCreateRequest):
    entries = []
    if DATASET_FILE.exists():
        try: entries = json.loads(DATASET_FILE.read_text(encoding="utf-8"))
        except Exception: pass
    entry_data = {}
    if req.data:
        entry_data = {k: v for k, v in req.data.items() if v}
    elif req.taskId:
        with _lock: task = _tasks.get(req.taskId)
        if task and task.get("result"):
            r = task["result"]
            entry_data = {"stepFileUrl": r.get("stepFileUrl",""), "stepFileSize": r.get("stepFileSize","")}
    entry = {"id": uuid.uuid4().hex[:12], "name": req.name, "thumbnailUrl": "", "tags": req.tags,
             "createdAt": datetime.now().timestamp()*1000, "data": entry_data}
    entries.append(entry)
    DATASET_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry

@app.get("/api/dataset/entry/{entry_id}")
def api_dataset_detail(entry_id: str):
    if not DATASET_FILE.exists(): raise HTTPException(404, "Entry not found")
    for e in json.loads(DATASET_FILE.read_text(encoding="utf-8")):
        if e["id"] == entry_id: return e.get("data",{})
    raise HTTPException(404, "Entry not found")

@app.delete("/api/dataset/entry/{entry_id}")
def api_dataset_delete(entry_id: str):
    if not DATASET_FILE.exists(): raise HTTPException(404, "Entry not found")
    entries = [e for e in json.loads(DATASET_FILE.read_text(encoding="utf-8")) if e["id"] != entry_id]
    DATASET_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}

@app.get("/api/files/{task_id}/{filename}")
def api_serve_file(task_id: str, filename: str):
    fp = OUT_ROOT / task_id / filename
    if not fp.exists(): raise HTTPException(404, f"File not found: {filename}")
    mt = "application/octet-stream" if filename.endswith((".stl",".step")) else "application/json"
    return FileResponse(str(fp), media_type=mt)

# ============================================================
# FEA Routes
# ============================================================
_fea_tasks: dict[str, dict] = {}
_fea_sessions: dict[str, dict] = {}
_fea_lock = threading.Lock()

@app.get("/api/fea/templates")
def api_fea_templates():
    from server.fea_pipeline import list_fea_templates
    return list_fea_templates()

class FeaExecuteBody(BaseModel):
    template_name: str
    parameters: dict = {}
    jobname: str = "fea_job"

@app.post("/api/fea/execute")
def api_fea_execute(req: FeaExecuteBody):
    task_id = uuid.uuid4().hex[:16]
    with _fea_lock:
        _fea_tasks[task_id] = {"task_id": task_id, "status": "pending", "progress": 0, "result": None, "error": None}
    from server.fea_pipeline import execute_fea_template
    threading.Thread(target=execute_fea_template, args=(
        req.template_name, req.parameters, req.jobname, _fea_tasks, task_id,
    ), kwargs={"lock": _fea_lock}, daemon=True).start()
    return {"task_id": task_id}

@app.get("/api/fea/result/{task_id}")
def api_fea_result(task_id: str):
    with _fea_lock:
        task = _fea_tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "FEA task not found")
    return task

@app.get("/api/fea/regions/{model_id}")
def api_fea_regions(model_id: str):
    # Load the metadata for the most recent generation with this model
    # For now, find the latest output directory with metadata
    candidates = sorted(OUT_ROOT.glob("*/output.metadata.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for meta_path in candidates:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            regions = compute_disc_regions(meta)
            return {"model_id": model_id, "regions": regions}
        except Exception:
            continue
    # Fallback: return default regions
    from server.fea_pipeline import compute_disc_regions
    return {"model_id": model_id, "regions": compute_disc_regions({})}

@app.get("/api/health")
def api_health():
    return {"status": "ok", "tasks": len(_tasks), "spatialSessions": len(_spatial_sessions),
            "fea_tasks": len(_fea_tasks)}

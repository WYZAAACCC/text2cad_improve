# generative_cad Architecture

> Node format: Chinese function label + English code identifier. Edges verified against actual import statements.
> Open `mermaid_viewer.html` for interactive viewing.

---

## 1. System Context

```mermaid
graph LR
    User["User<br/>NL text"] --> GCAD["generative_cad<br/>Text-to-CAD Engine"]
    GCAD --> STEP["output.step<br/>ISO 10303-21"]
    GCAD --> META["output.metadata.json<br/>GenerativeMetadataV3"]
    STEP --> SW["SolidWorks 2025<br/>native_importers.py"]
    STEP --> NX["Siemens NX<br/>native_importers.py"]
    GCAD --> DS["DeepSeek API<br/>v4-pro"]
    GCAD --> OCP["OCCT Kernel<br/>CadQuery"]
```

## 2. Pipeline Layers

```mermaid
graph TB
    subgraph L0["Entry"]
        builder["builder.py<br/>build_generative_cad_model()"]
        tools["tools.py<br/>9 Agent @tool functions"]
    end
    subgraph L1["Authoring"]
        bp["build_pipeline.py<br/>generate_validate_build_step()"]
        ap["pipeline.py<br/>generate_gcad_from_user_request()"]
        asm["raw_assembler.py<br/>assemble_raw_gcad_document()"]
        fix["auto_fixer.py<br/>auto_fix_with_report()"]
        ssch["strict_schema.py<br/>to_deepseek_strict_schema()"]
    end
    subgraph L2["LLM Interaction"]
        orch["orchestrator.py<br/>L1 + L2 prompt/tool builders"]
        dsc["deepseek_client.py<br/>DeepSeekToolCaller"]
        tc["tool_schema_compiler.py<br/>per-op JSON Schema"]
    end
    subgraph L3["IR"]
        raw["ir/raw.py<br/>RawGcadDocument"]
        can["ir/canonical.py<br/>CanonicalGcadDocument"]
        expr["ir/expr.py<br/>DimExpr / RefPath"]
    end
    subgraph L4["Validation"]
        vp["validation/pipeline.py<br/>14 stages"]
        vcan["canonicalize.py<br/>Raw to Canonical"]
        rh["repair_hints.py<br/>Repair hints"]
    end
    subgraph L5["Compiler Middle-End"]
        pm["pass_manager.py<br/>2 Passes"]
        fp["fact_propagation.py<br/>FactPropagation"]
        pl["planner.py<br/>Planning"]
    end
    subgraph L6["Dialects"]
        exec["executor.py<br/>execute_operation()"]
        reg["default_registry.py<br/>6 dialects"]
        gutils["geometry_utils/<br/>OCP wire/pipe/loft"]
    end
    subgraph L7["Runtime"]
        ctx["context.py<br/>RuntimeContext"]
        store["object_store.py<br/>ObjectStore"]
        cq["cadquery_runtime.py<br/>STEP export"]
        rec["recovery.py<br/>Failure recovery"]
        cs["constraint_resolver.py<br/>Placements"]
    end
    subgraph L8["Output"]
        run["pipeline/run.py<br/>run_canonical_gcad()"]
        art["artifact.py<br/>CanonicalStepArtifact"]
        meta3["metadata_v3.py<br/>Metadata proof"]
        gate["import_artifact.py<br/>Import gate"]
    end

    builder --> vp
    builder --> run
    tools --> builder
    bp --> ap
    ap --> asm
    ap --> fix
    ap --> vp
    orch --> dsc
    orch --> tc
    dsc --> ssch
    asm --> reg
    vp --> vcan
    vp --> rh
    vcan --> reg
    pm --> fp
    pm --> pl
    fp --> expr
    exec --> reg
    run --> pm
    run --> reg
    run --> cs
    run --> cq
    cq --> gutils
    meta3 --> ctx
    art --> meta3
    gate --> meta3
```

## 3. Data Flow: Text to STEP

```mermaid
graph LR
    A["1. User Text"] --> B["2. L1 Route<br/>orchestrator.py"]
    B --> C["3. DialectSelectionPlan<br/>schemas.py"]
    C --> D["4. L2 Author<br/>orchestrator.py"]
    D --> E["5. RawGcadDocument<br/>ir/raw.py"]
    E --> F["6. System Fill<br/>raw_assembler.py"]
    F --> G["7. Auto Fix<br/>auto_fixer.py"]
    G --> H["8. Validate<br/>14 stages"]
    H --> I["9. Canonicalize<br/>canonicalize.py"]
    I --> J["10. Compiler<br/>2 passes"]
    J --> K["11. Execute<br/>dialects/executor.py"]
    K --> L["12. Assemble<br/>composition"]
    L --> M["13. Export STEP<br/>cadquery_runtime.py"]
    M --> N["14. Metadata<br/>metadata_v3.py"]
    N --> O["output.step<br/>+ metadata.json"]
```

## 4. Validation Pipeline (14 stages)

```mermaid
graph TB
    subgraph Parse["ir/parse.py"]
        P1["Check top keys (10)"] --> P2["Check safety keys (7)"] --> P3["Check constraint keys (4)"] --> P4["model_validate()"]
    end
    subgraph RAW["RAW stages: validation/pipeline.py RAW_STAGES"]
        direction TB
        S1["structure<br/>structure.py"] --> S2["root_terminal<br/>root_terminal.py"]
        S2 --> S3["registry<br/>registry.py"]
        S3 --> S4["params<br/>params.py"]
        S4 --> S5["ownership<br/>ownership.py"]
        S5 --> S6["graph<br/>graph.py"]
        S6 --> S7["typecheck<br/>typecheck.py"]
        S7 --> S8["phase<br/>phase.py"]
        S8 --> S9["composition<br/>composition.py"]
        S9 --> S10["hole_semantics<br/>hole_semantics.py"]
        S10 --> S11["safety<br/>safety.py"]
    end
    subgraph Canon["canonicalize.py"]
        CAN["canonicalize()<br/>type resolution + contract_hash + graph_hash"]
    end
    subgraph CSTAGES["CANONICAL stages"]
        C1["dialect_semantics<br/>dialect_semantics.py"] --> C2["geometry_preflight<br/>geometry_preflight.py"]
    end
    subgraph Repair["Repair"]
        AF["auto_fixer.py<br/>20+ deterministic fixes"]
        RA["repair_agent.py<br/>LLM repair, max 3 rounds"]
        RH["repair_hints.py<br/>double-bind detection"]
    end
    P4 --> RAW
    S11 --> CAN
    CAN --> CSTAGES
    RAW -.->|failure| AF
    RAW -.->|failure| RA
    RH --> AF
    RH --> RA
    CAN --> RH
    CSTAGES --> RH
```

## 5. Compiler Middle-End

```mermaid
graph TB
    input["CanonicalGcadDocument<br/>ir/canonical.py"]
    gate["Gate: SEEKFLOW_GCAD_ENABLE_MIDDLE_END<br/>compiler/config.py, default=1"]

    subgraph Pass1["Pass 1: FactPropagationPass"]
        topo["Topological sort<br/>Kahn + DFS fallback"]
        process["Process each node"]
        rules["8 fact rules<br/>analysis/fact_rules.py"]
        eval["DimExpr eval<br/>analysis/expr_eval.py"]
        store["FactStore<br/>analysis/facts.py"]
    end

    subgraph Pass2["Pass 2: PlannerPass"]
        chk1["Pattern count vs<br/>BATCH=8, LARGE=120"]
        chk2["Destructive ops<br/>threshold=32"]
        chk3["Edge treatment<br/>ordering"]
    end

    diag["CompilerModule.diagnostics<br/>module.py"]
    report["PlanningReport<br/>planning_report.py"]

    input --> gate
    gate --> topo
    topo --> process
    process --> rules
    process --> eval
    eval --> store
    store --> process
    gate --> Pass2
    chk1 --> chk2 --> chk3
    Pass1 --> diag
    Pass2 --> report
```

## 6. Dialect Layer

```mermaid
graph LR
    subgraph Registry
        DR["default_registry.py<br/>@lru_cache singleton<br/>6 frozen dialects"]
    end
    subgraph Executor
        EX["executor.py<br/>execute_operation()<br/>cache -> handler -> normalize<br/>-> validate -> BRepCheck"]
    end
    subgraph Dialects
        AX["axisymmetric<br/>8 ops"]
        SE["sketch_extrude<br/>11 ops"]
        LS["loft_sweep<br/>4 ops"]
        SH["shell_housing<br/>2 ops"]
        CP["composition<br/>7 ops"]
        SP["sketch_profile<br/>9 ops"]
    end
    subgraph GeoUtils["geometry_utils/"]
        W["ocp_wire.py<br/>ocp_pipe.py"]
        L["ocp_loft.py<br/>ocp_cylinder.py"]
        B["boolean_safe.py<br/>boolean_batch.py"]
        H["hole_placement.py<br/>path_analysis.py"]
    end
    subgraph Contracts
        BD["base.py<br/>BaseDialect Protocol"]
        OS["operation.py<br/>OperationSpec"]
        RES["results.py<br/>OperationResult ABI"]
    end

    DR --> Dialects
    EX --> Dialects
    Dialects --> GeoUtils
    BD --> Dialects
    OS --> Dialects
    RES --> EX
```

## 7. Staged Authoring Pipeline

```mermaid
graph TB
    UT["User Text"] --> S0
    subgraph S0["Stage 0: Spatial (v6 optional)"]
        spa["spatial/pipeline.py<br/>run_spatial_authoring_frontend()"]
    end
    S0 --> S1
    subgraph S1["Stage 1: Route"]
        r1["LLM -> RoutePlan<br/>schemas.py"]
    end
    S1 --> S2
    subgraph S2["Stage 2: Context"]
        c1["context_builder.py<br/>load contracts + BasePackage"]
    end
    S2 --> S3
    subgraph S3["Stage 3: Feature Sequence"]
        f1["LLM -> FeatureSequenceDraft<br/>schemas.py"]
    end
    S3 --> S4
    subgraph S4["Stage 4: Node Params (per-node)"]
        n1["LLM x N -> NodeParamsDraft<br/>schemas.py"]
    end
    S4 --> S5
    subgraph S5["Stage 5: Assemble"]
        a1["raw_assembler.py<br/>system fills safety/constraints/wiring"]
    end
    S5 --> S6
    subgraph S6["Stage 6: Validate"]
        v1["validation/pipeline.py<br/>14 stages"]
    end
    S6 --> S7
    subgraph S7["Stage 7: Repair"]
        rp["auto_fixer.py + repair_agent.py<br/>deterministic + LLM loops"]
    end
```

## 8. Runtime Layer

```mermaid
graph TB
    subgraph State["RuntimeContext (context.py)"]
        OS["ObjectStore<br/>object_store.py"]
        GH["GeometryHealth<br/>health.py"]
        FR["handle_feature_failure()<br/>recovery.py"]
        PL["spatial_placements<br/>constraint_resolver.py"]
        SA["spatial_audit<br/>spatial_audit.py"]
    end
    subgraph Handles["Typed Handles (handles.py)"]
        SOL["SolidHandle"]
        FRM["FrameHandle"]
        PLN["PlaneHandle"]
        PNT["PointHandle"]
        CRV["CurveHandle"]
        EDG["EdgeHandle"]
        FAC["FaceHandle"]
    end
    subgraph Backend["Geometry Backend"]
        CQ["CadQueryRuntime<br/>cadquery_runtime.py"]
        CQ --> STEP["export_step()<br/>OCCT STEPControl_Writer"]
    end
    subgraph Validate["Post-checks"]
        PC["postconditions.py"]
        GC["geometry_postcheck.py"]
        SC["semantic_postcheck.py"]
    end

    OS --> Handles
    GH --> OS
    FR --> OS
    PL --> OS
    SA --> PL
    Backend --> OS
    Validate --> OS
```

## 9. Spatial Subsystem (v6)

```mermaid
graph TB
    subgraph PhaseA["Phase A: Symbolic (authoring/spatial/)"]
        OG["LLM: MechanicalObjectGraphDraft<br/>prompts.py + schemas.py"]
        ARCH["Archetype matching<br/>archetypes/ (4 types)"]
        CG["build_constraint_graph()<br/>constraint_graph.py"]
        SOLV["validate_constraint_graph()<br/>solver.py (cycle/contradiction)"]
        VAL["validate_spatial_contract()<br/>validators.py (V001/V002/V003/V008)"]
        Q["plan_questions()<br/>question_planner.py"]
    end
    subgraph PhaseC["Phase C: Numeric (runtime/)"]
        BB["measure_all_component_bboxes()<br/>bbox_tracker.py"]
        RS["resolve_placements()<br/>constraint_resolver.py"]
        AUD["run_geometry_spatial_audit()<br/>spatial_audit.py"]
    end
    subgraph Integration["Pipeline integration"]
        INJ["inject_placements_into_sequence()<br/>integration.py"]
        CTX["build_spatial_context_for_prompt()<br/>integration.py"]
    end

    OG --> ARCH
    ARCH --> CG
    CG --> SOLV
    SOLV --> VAL
    VAL --> Q
    CG --> INJ
    INJ --> PhaseC
    BB --> RS
    RS --> AUD
    CG --> CTX
```

## 10. DeepSeek API Adapter

```mermaid
graph TB
    IN["call_strict_tool()<br/>deepseek_client.py"]
    subgraph Transform["strict_schema.py"]
        T1["_inline_all_refs()"]
        T2["_transform_object()<br/>addProps=false, number->integer<br/>optional->anyOf[type,null]"]
        T3["_strip_unsupported()<br/>minLength/maxLength/minItems..."]
        T4["_fix_anyof_items()"]
    end
    subgraph Config["API workarounds"]
        W1["strict=False (#1069)"]
        W2["tool_choice=required (#1376)"]
        W3["thinking=disabled"]
    end
    subgraph Validate["Response checks"]
        V1["not empty"]
        V2["exactly 1 call"]
        V3["name matches"]
        V4["valid JSON"]
        V5["is dict"]
    end
    OUT["ToolCallResult<br/>provider.py"]

    IN --> T1 --> T2 --> T3 --> T4
    T4 --> W1
    IN --> Config
    Config --> V1 --> V2 --> V3 --> V4 --> V5
    V5 --> OUT
```

## 11. Two Paths: Primitive vs Non-Primitive

```mermaid
graph LR
    subgraph P["Primitive (deterministic)"]
        direction LR
        P1["Structured Spec"] --> P2["L1: deterministic_primitive"] --> P3["geometry_primitives<br/>(external package)"] --> P4["STEP"]
    end
    subgraph NP["Non-Primitive (LLM + Compiler)"]
        direction LR
        N1["NL Text"] --> N2["L1 Route<br/>DeepSeek"] --> N3["L2 Author<br/>DeepSeek"] --> N4["14-stage<br/>Validate"] --> N5["Compiler<br/>2 passes"] --> N6["6 Dialects<br/>Execute"] --> N7["STEP"]
    end
```

---

*Diagrams regenerated 2026-06-06. All edges verified against actual `from ... import` statements in source.*

"""Gen 3 描述重跑：对有效模型用 3 种描述各跑 pipeline 生成 3 个 Gen 变体（基础设施）。

每个变体显式继承源 design_id/model_id/family（写 source_ref.json，run_enrich 读取继承），
保证"同一几何模型的 3 种描述"捆绑正确。后处理链：run_enrich → run_filter → run_index。

LLM 密集（每源模型 × 3 次），默认 --limit 小规模验证，不触发完整构建。

用法:
  .conda/python.exe _param_experiment/run_gen_variants.py --limit 1     # 基础设施验证（LLM）
  .conda/python.exe _param_experiment/run_gen_variants.py --valid-only --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
OUTPUT = ROOT / "app" / "text-to-cad" / "server" / "output"
DATASETS = _HERE / "output" / "datasets"
sys.path.insert(0, str(ROOT / "app" / "text-to-cad" / "server"))
sys.path.insert(0, str(ROOT / "integrations" / "engineering_tools" / "src"))
sys.path.insert(0, str(_HERE))

STYLE_SHORT = {"cn_param": "cn_p", "cn_semantic": "cn_s", "en_mixed": "en_m"}


def _source_models(valid_only: bool) -> list:
    idx = json.loads((DATASETS / "index.json").read_text(encoding="utf-8"))
    return [m["task_id"] for m in idx.get("models", [])
            if (not valid_only or m.get("valid")) and (OUTPUT / m["task_id"] / "descriptions.json").exists()]


def _write_source_ref(new_tid: str, src: str) -> dict:
    try:
        en = json.loads((OUTPUT / src / "dataset_enrich.json").read_text(encoding="utf-8"))
        sr = {"source_task_id": src, "design_id": en.get("design_id"),
              "model_id": en.get("model_id"), "design_family_id": en.get("design_family_id")}
    except Exception:  # noqa: BLE001
        sr = {"source_task_id": src, "design_id": None, "model_id": None, "design_family_id": None}
    (OUTPUT / new_tid / "source_ref.json").write_text(
        json.dumps(sr, ensure_ascii=False, indent=2), encoding="utf-8")
    return sr


def _run_variant(src: str, style: str, text: str) -> str:
    import main
    new_tid = f"gen_{src}_{STYLE_SHORT[style]}"
    main._tasks[new_tid] = {"taskId": new_tid, "status": "pending", "progress": 0,
                            "result": None, "error": None}
    main._run_pipeline(new_tid, text, force_route="generative_cad_ir")
    _write_source_ref(new_tid, src)
    return main._tasks[new_tid].get("status", "?")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gen 3 描述重跑（3 变体生成 + design_id 继承）")
    ap.add_argument("--valid-only", action="store_true", help="只处理 index valid 模型（默认）")
    ap.add_argument("--all", action="store_true", help="处理全部有 descriptions 的任务")
    ap.add_argument("--limit", type=int, default=None, help="最多处理前 N 个源模型")
    ap.add_argument("--with-postprocess", action="store_true",
                    help="生成后跑 run_enrich/run_filter/run_index")
    args = ap.parse_args(argv)

    srcs = _source_models(not args.all)
    if args.limit:
        srcs = srcs[:args.limit]
    if not srcs:
        print("没有源模型（先跑 run_index + run_descriptions）")
        return 1

    print(f"Gen 3 描述重跑：{len(srcs)} 个源模型 × 3 变体（LLM）")
    gen_ok = 0
    for i, src in enumerate(srcs, 1):
        de = json.loads((OUTPUT / src / "descriptions.json").read_text(encoding="utf-8"))
        for desc in de.get("descriptions", []):
            style = desc.get("style")
            if style not in STYLE_SHORT:
                continue
            new_tid = f"gen_{src}_{STYLE_SHORT[style]}"
            print(f"  [{i}/{len(srcs)}] {src} → {new_tid} ...", end=" ", flush=True)
            try:
                status = _run_variant(src, style, desc.get("text", ""))
                print(f"{status}")
                if status == "completed":
                    gen_ok += 1
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL  {exc}")
            # 变体后处理（继承 design_id + 补 descriptions/SER，P1-1）
            try:
                import run_enrich
                run_enrich.run_one(new_tid)
            except Exception:  # noqa: BLE001
                pass
            try:
                import run_descriptions
                run_descriptions.run_one(new_tid)
            except Exception:  # noqa: BLE001
                pass

    if args.with_postprocess:
        import run_filter
        import run_index
        run_filter.main([])
        run_index.main([])

    print(f"DONE  {gen_ok} 变体生成成功（共 {len(srcs) * 3} 变体）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

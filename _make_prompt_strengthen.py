from pathlib import Path

PB = Path(r"E:\text_to_cad_improve\auto_detection_process\integrations\engineering_tools\src\seekflow_engineering_tools\generative_cad\authoring\prompt_builders.py")

def edit(old_lines, new_lines):
    s = PB.read_text(encoding="utf-8")
    old = "\n".join(old_lines)
    new = "\n".join(new_lines)
    n = s.count(old)
    if n != 1:
        raise SystemExit("not unique count=%d" % n)
    PB.write_text(s.replace(old, new), encoding="utf-8")

# 1. system prompt: sync allowed scope + allow whole-params replacement
edit([
    "- Only modify paths listed in ALLOWED PATHS (node params of the failing node).",
    "- Every change must provide the exact old_value from the current document.",
], [
    "- Only modify paths listed in ALLOWED PATHS (params of the failing node and its input-chain nodes).",
    "- You may replace the entire params dict of an allowed node when the fix requires rewriting its inputs.",
    "- Every change must provide the exact old_value from the current document.",
])

# 2. user prompt: add common failure patterns block
edit([
    "GEOMETRY HEALTH:",
    "{compact_json(geometry_health or {})}",
    "",
    "ALLOWED PATHS (you may ONLY modify these):",
], [
    "GEOMETRY HEALTH:",
    "{compact_json(geometry_health or {})}",
    "",
    "COMMON RUNTIME FAILURE PATTERNS AND GENERAL FIX DIRECTIONS:",
    "- zero_volume / degenerate profile: usually the profile has zero area (collinear, overlapping, or placeholder points). Replace the profile points with a closed, non-self-intersecting polygon with non-zero area whose dimensions match the design request.",
    "- boolean merge failure (multiple bodies): components do not actually intersect; check positions, radii, and pattern parameters so tool bodies overlap the target solid.",
    "- fillet/chamfer failure: radius too large for the edge or vertex index out of range; reduce radius or target existing vertices.",
    "- Profile points must use x_mm/y_mm keys and be consistent with the operation schema; do not leave placeholder values.",
    "- Do NOT weaken required/degradation_policy to mask the failure.",
    "",
    "ALLOWED PATHS (you may ONLY modify these):",
])


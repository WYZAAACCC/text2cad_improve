"""验证 DeepSeek strict=False 下 number 类型是否可用（隔离实验）。

对比三种 schema 变体，让 LLM 输出带小数的坐标：
  v_integer: to_deepseek_strict_schema 转换后（x_mm→integer，当前生产行为）
  v_number : strict 转换后把 integer 还原为 number
  v_raw    : 原始 schema（不经过 to_deepseek_strict_schema）

目的：判断"坐标强制整数"是否有解决方案。
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "integrations" / "engineering_tools" / "src"
sys.path.insert(0, str(SRC))

from seekflow_engineering_tools.generative_cad.llm.deepseek_client import DeepSeekToolCaller
from seekflow_engineering_tools.generative_cad.llm.models import LlmModelConfig
from seekflow_engineering_tools.generative_cad.authoring.strict_schema import (
    to_deepseek_strict_schema,
)

API_KEY_FILE = ROOT / "_archive" / "apikey.txt"
MODEL_CONFIG = LlmModelConfig(model="deepseek-v4-pro", base_url="https://api.deepseek.com/beta")

TOOL_NAME = "emit_coords"
TOOL_DESC = "Emit the requested 2D coordinates."


COORD_SCHEMA = {
    "type": "object",
    "properties": {
        "points": {
            "type": "array",
            "description": "2D 坐标点列表",
            "items": {
                "type": "object",
                "properties": {
                    "x_mm": {"type": "number", "description": "X 坐标，mm，可含小数"},
                    "y_mm": {"type": "number", "description": "Y 坐标，mm，可含小数"},
                },
                "required": ["x_mm", "y_mm"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["points"],
    "additionalProperties": False,
}


def _restore_numbers(node):
    """递归把 schema 中的 integer（原为 number）还原为 number。"""
    if isinstance(node, dict):
        if node.get("type") == "integer":
            node["type"] = "number"
        for v in node.values():
            _restore_numbers(v)
    elif isinstance(node, list):
        for v in node:
            _restore_numbers(v)


def build_variants():
    v_integer = to_deepseek_strict_schema(copy.deepcopy(COORD_SCHEMA))
    v_number = to_deepseek_strict_schema(copy.deepcopy(COORD_SCHEMA))
    _restore_numbers(v_number)
    v_raw = copy.deepcopy(COORD_SCHEMA)
    return {
        "v_integer": v_integer,
        "v_number": v_number,
        "v_raw": v_raw,
    }


def call(variant_name: str, schema: dict) -> dict | str:
    caller = DeepSeekToolCaller()
    messages = [
        {
            "role": "system",
            "content": (
                "You are a test harness. Return exactly 3 points with the requested decimals: "
                "p0=(12.5, -3.25), p1=(7.75, 1.5), p2=(-4.2, 9.9). "
                "Preserve the decimals exactly — do NOT round to integers."
            ),
        },
        {"role": "user", "content": "Return the 3 points."},
    ]
    try:
        r = caller.call_strict_tool(
            messages=messages,
            tool_name=TOOL_NAME,
            tool_description=TOOL_DESC,
            tool_schema=schema,
            model_config=MODEL_CONFIG,
        )
        return dict(r.arguments)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def main():
    key = API_KEY_FILE.read_text(encoding="utf-8").strip()
    os.environ["DEEPSEEK_API_KEY"] = key

    variants = build_variants()
    print("=== schema 变体中 x_mm 的类型 ===")
    for name, schema in variants.items():
        t = schema["properties"]["points"]["items"]["properties"]["x_mm"]["type"]
        print(f"  {name}: x_mm type = {t}")

    print("\n=== 调用 DeepSeek 结果 ===")
    for name, schema in variants.items():
        print(f"\n[{name}]")
        res = call(name, schema)
        if isinstance(res, str):
            print(f"  {res}")
            continue
        pts = res.get("points", [])
        print(f"  points = {json.dumps(pts, ensure_ascii=False)}")
        has_float = any(
            not float(p["x_mm"]).is_integer() or not float(p["y_mm"]).is_integer()
            for p in pts
        )
        print(f"  -> 保留小数? {'YES' if has_float else 'NO (全部整数/被取整)'}")


if __name__ == "__main__":
    main()
